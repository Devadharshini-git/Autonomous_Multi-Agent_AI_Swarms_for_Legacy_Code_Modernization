# agents/debugger.py
"""
Debugger Agent — Part 6 (Self-Healing Loop)
Reads a failing test result, asks the LLM to fix the code,
and re-tests in the Docker sandbox. Repeats until tests pass
or a max retry count is hit.

Includes a test-sanity check: before touching main.py, the system
judges whether the FAILURE is caused by broken application code, or
by a test whose expected value/fixture is itself wrong. This stops
the loop from repeatedly "fixing" correct code to satisfy a bad test.

Diagnosis has two layers:
1. A fast, deterministic heuristic that catches known bad-test patterns
   (e.g. an empty pytest fixture used by a test that expects populated
   data) without relying on LLM judgement at all.
2. An LLM-based diagnosis for everything else, with a retry on parse
   failure, and a SAFE DEFAULT of BAD_TEST (not CODE_BUG) if diagnosis
   still can't be parsed — application code should never be modified
   without a confident diagnosis.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import re
import ollama

from agents.planner import MODEL_NAME
from sandbox.runner import run_tests_in_sandbox


MAX_RETRIES = 5
DIAGNOSIS_LLM_ATTEMPTS = 2


def extract_error_lines(broken_code: str, failure_output: str) -> str:
    """
    Parses 'main.py:NN: ErrorType' patterns out of the pytest traceback
    and pulls the actual source line from broken_code, so the LLM sees
    exactly which line(s) to fix instead of hunting for them.
    """
    code_lines = broken_code.split("\n")
    matches = re.findall(r"main\.py:(\d+):\s*(\w+Error.*)", failure_output)

    if not matches:
        return "(Could not auto-extract — read the traceback above carefully.)"

    seen = set()
    highlighted = []
    for line_no_str, error_desc in matches:
        line_no = int(line_no_str)
        if line_no in seen:
            continue
        seen.add(line_no)
        if 0 < line_no <= len(code_lines):
            source_line = code_lines[line_no - 1].strip()
            highlighted.append(f'- Line {line_no}: "{source_line}"  →  {error_desc.strip()}')

    return "\n".join(highlighted) if highlighted else "(Could not auto-extract — read the traceback above carefully.)"


# ---------- HEURISTIC PRE-CHECK: deterministic bad-test detection ----------

def heuristic_check_empty_fixture(test_code: str):
    """
    Fast, deterministic pre-check for a specific known bad-test pattern:
    a pytest fixture that returns an empty container (e.g. an empty list),
    while a test using that fixture then asserts non-empty/populated
    results. This is detected mechanically, without relying on LLM
    diagnosis accuracy, since it's a common and unambiguous test-authoring
    bug: the fixture and the assertions it feeds simply don't agree.

    Returns a diagnosis dict if the pattern is found, otherwise None
    (meaning: fall through to LLM-based diagnosis).
    """
    fixture_pattern = re.compile(
        r"@pytest\.fixture\s*\ndef\s+(\w+)\s*\([^)]*\)\s*:\s*\n((?:[ \t]+.*\n?)+)"
    )

    empty_fixtures = []
    for match in fixture_pattern.finditer(test_code):
        fixture_name, body = match.group(1), match.group(2)
        return_lines = [l.strip() for l in body.splitlines() if l.strip().startswith("return")]
        if return_lines:
            last_return = return_lines[-1]
            if re.search(r"return\s*(\[\]|\{\}|\(\)|\"\"|'')\s*$", last_return):
                empty_fixtures.append(fixture_name)

    if not empty_fixtures:
        return None

    for fixture_name in empty_fixtures:
        test_func_pattern = re.compile(
            rf"def\s+(test_\w+)\s*\([^)]*\b{re.escape(fixture_name)}\b[^)]*\)\s*:\s*\n((?:[ \t]+.*\n?)+)"
        )
        for tmatch in test_func_pattern.finditer(test_code):
            test_name, test_body = tmatch.group(1), tmatch.group(2)
            expects_populated = (
                re.search(r"==\s*[1-9]\d*(\.\d+)?", test_body)
                or re.search(r"in\s+captured\.out", test_body)
            )
            if expects_populated:
                return {
                    "diagnosis": "BAD_TEST",
                    "reasoning": (
                        f"Fixture '{fixture_name}' returns an empty container, but test "
                        f"'{test_name}' asserts non-empty/populated results derived from it. "
                        f"The fixture itself does not match what the test expects — this is a "
                        f"test-authoring bug, not an application code bug."
                    ),
                    "bad_test_names": [test_name],
                }

    return None


# ---------- LLM-BASED DIAGNOSIS ----------

def build_diagnosis_prompt(main_code: str, test_code: str, failure_output: str) -> str:
    prompt = f"""You are a senior Python engineer triaging a failing test suite.

APPLICATION CODE (main.py):
```python
{main_code}
```

TEST FILE (test_main.py):
```python
{test_code}
```

PYTEST FAILURE OUTPUT:
```
{failure_output}
```

YOUR TASK:
For EACH failing test, independently recompute the expected result by hand from
the actual application code's logic and the actual input values used in that
test (including any fixture the test depends on — check what the fixture
actually returns, not what the test assumes it returns). Then decide, for each
failure, which of these it is:

- "CODE_BUG": the application code's logic is genuinely wrong (e.g. wrong
  operator, wrong formula, crashes, wrong type handling) — recomputing by hand
  confirms the test's expected value and input data are correct, and the code
  simply doesn't produce the right result.
- "BAD_TEST": the application code's logic is actually correct — recomputing by
  hand shows the code's real output does NOT match what the test's assert
  claims, OR the test's fixture/input data itself is invalid, incomplete, or
  inconsistent with what the test expects (e.g. a fixture returning an empty
  list while the test asserts on populated results).

Show your calculation for each failing test explicitly before deciding.

Respond with ONLY a JSON object in this exact format, no other text:
{{
  "diagnosis": "CODE_BUG" or "BAD_TEST" or "MIXED",
  "reasoning": "brief explanation referencing your hand calculations",
  "bad_test_names": ["list", "of", "test function names", "that have wrong expected values or bad fixtures, if any"]
}}

If ANY failing test has a wrong expected value, or relies on a fixture/input
that doesn't actually support what it asserts, include "BAD_TEST" or "MIXED" —
do not default to CODE_BUG just because tests are failing.
"""
    return prompt


def call_llm_for_diagnosis(prompt: str) -> str:
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0},
    )
    return response["message"]["content"]


def extract_json_from_response(raw_text: str):
    """
    Attempts to parse a JSON object out of the LLM's response.
    Returns None on failure (caller decides how to handle that —
    NEVER silently substitutes a CODE_BUG default here).
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None


def diagnose_failure(main_code: str, test_code: str, failure_output: str) -> dict:
    """
    Two-layer diagnosis:
    1. Deterministic heuristic check (fast, no LLM call, catches known
       bad-test patterns like empty-fixture mismatches with certainty).
    2. LLM-based diagnosis with a retry on parse failure.
    3. If the LLM diagnosis still can't be parsed after retries, default
       to BAD_TEST — never CODE_BUG — since application code must never
       be modified without a confident diagnosis.
    """
    heuristic_result = heuristic_check_empty_fixture(test_code)
    if heuristic_result:
        print("🔍 Heuristic pre-check found a deterministic bad-test pattern (empty fixture mismatch).")
        return heuristic_result

    for attempt in range(DIAGNOSIS_LLM_ATTEMPTS):
        prompt = build_diagnosis_prompt(main_code, test_code, failure_output)
        raw = call_llm_for_diagnosis(prompt)
        parsed = extract_json_from_response(raw)
        if parsed and parsed.get("diagnosis") in ("CODE_BUG", "BAD_TEST", "MIXED"):
            return parsed
        if attempt == 0:
            print("⚠️  Diagnosis JSON parse failed, retrying once...")

    print("⚠️  Diagnosis could not be reliably parsed after retries — "
          "defaulting to BAD_TEST (application code is never modified without a confident diagnosis).")
    return {
        "diagnosis": "BAD_TEST",
        "reasoning": "diagnosis parsing failed after retries; defaulting to reviewing the test "
                     "rather than risk corrupting correct application code",
        "bad_test_names": [],
    }


# ---------- FIX CODE (only when diagnosis says CODE_BUG) ----------

def build_fix_prompt(broken_code: str, test_code: str, failure_output: str) -> str:
    error_lines = extract_error_lines(broken_code, failure_output)

    prompt = f"""You are a senior Python engineer debugging a failing service.

CURRENT CODE (main.py):
```python
{broken_code}
```

TEST FILE (test_main.py):
```python
{test_code}
```

TEST FAILURE OUTPUT (from pytest, includes the traceback):
```
{failure_output}
```

THE EXACT LINE(S) CAUSING THE FAILURE (extracted from the traceback above):
{error_lines}

YOUR TASK:
The line(s) shown above are the root cause. You MUST change at least one of those
exact lines. Do not skip them. Do not "fix" unrelated code, add try/except blocks,
add finally blocks, or add logging anywhere else in the file — those will NOT fix
this failure and will be considered an incorrect answer.

RULES:
- Output ONLY the complete, corrected main.py file content.
- Wrap your entire response in a single ```python code fence — nothing before or after it.
- Keep all function/class names, the FastAPI app, and all routes exactly as they are.
- Do not modify the test file — only fix main.py.
- Make the smallest change that fixes the root cause shown in the traceback.
- Before answering, re-read the exact line(s) flagged above one more time and confirm your fix actually changes them.
"""
    return prompt


def call_llm_for_fix(prompt: str) -> str:
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    return response["message"]["content"]


# ---------- FIX TEST (only when diagnosis says BAD_TEST) ----------

def build_test_fix_prompt(main_code: str, broken_test_code: str, failure_output: str, bad_test_names: list) -> str:
    names_list = ", ".join(bad_test_names) if bad_test_names else "the failing test(s) shown in the failure output above"

    prompt = f"""You are a senior Python test engineer. The following test file has a
problem in: {names_list}. This may be a wrong expected value, OR a fixture that
supplies data inconsistent with what the test asserts (e.g. an empty fixture
used by a test expecting populated data).

APPLICATION CODE (main.py) — this code is CORRECT, do not suggest changing it:
```python
{main_code}
```

CURRENT TEST FILE (test_main.py) — contains the problem described above:
```python
{broken_test_code}
```

PYTEST FAILURE OUTPUT:
```
{failure_output}
```

YOUR TASK:
Fix the test file so it is internally consistent and correctly reflects the
application code's real, actual behavior. This may mean:
- Correcting a wrong expected numeric value (recompute it by hand from the
  actual application code logic and the actual input values), and/or
- Replacing a broken/empty fixture with valid input data, constructed directly
  inside the test function body (do NOT use a shared @pytest.fixture for input
  data — build the input objects inline in each test that needs them).

Do not change main.py logic. Do not change any test that is not part of the
problem described above.

RULES:
- Output ONLY the complete, corrected test_main.py file content.
- Wrap your entire response in a single ```python code fence — nothing before or after it.
- Keep all test function names and all passing tests exactly as they are.
- Add a comment showing the corrected calculation above each fixed numeric assert.
- Before answering, recompute every value one more time to confirm it's right.
"""
    return prompt


def call_llm_for_test_fix(prompt: str) -> str:
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    return response["message"]["content"]


# ---------- SHARED HELPERS ----------

def extract_code_from_response(raw_text: str) -> str:
    match = re.search(r"```python\s*\n(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def save_iteration_log(service_name: str, iteration: int, diagnosis: dict, old_code: str, new_code: str,
                        failure_output: str, target_file: str):
    """Saves a record of each self-healing attempt, for the demo ('here's how it healed itself')."""
    log_dir = os.path.join("generated", service_name, "healing_log")
    os.makedirs(log_dir, exist_ok=True)

    log_entry = {
        "iteration": iteration,
        "diagnosis": diagnosis,
        "target_file": target_file,
        "failure_output": failure_output,
        "old_code": old_code,
        "new_code": new_code,
    }

    log_path = os.path.join(log_dir, f"attempt_{iteration}.json")
    write_file(log_path, json.dumps(log_entry, indent=2))
    print(f"📝 Logged healing attempt {iteration} to {log_path}")


def self_heal(service_name: str) -> dict:
    """
    Runs the full self-healing loop:
    test → if fail: diagnose (code bug vs bad test) → fix the right file →
    re-test → repeat, up to MAX_RETRIES times.

    Used when running agents/debugger.py standalone. When orchestrated via
    LangGraph (pipeline/graph.py), the graph itself owns the retry loop and
    calls diagnose_failure() + the fix functions directly per node instead —
    the logic is identical either way.
    """
    main_path = os.path.join("generated", service_name, "main.py")
    test_path = os.path.join("generated", service_name, "test_main.py")

    summary = {
        "service_name": service_name,
        "healed": False,
        "attempts": 0,
        "final_status": None,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n{'='*50}")
        print(f"🔁 Self-heal attempt {attempt}/{MAX_RETRIES}")
        print(f"{'='*50}")

        print("🏃 Running tests in sandbox...")
        result = run_tests_in_sandbox(service_name)
        summary["attempts"] = attempt

        if not result["build_success"]:
            print("❌ Docker build itself failed — cannot proceed with healing.")
            summary["final_status"] = "build_failed"
            return summary

        if result["tests_passed"]:
            print(f"✅ Tests passed on attempt {attempt}! Self-healing complete.")
            summary["healed"] = True
            summary["final_status"] = "passed"
            return summary

        print(f"❌ Tests failed on attempt {attempt}. Diagnosing root cause...")

        main_code = read_file(main_path)
        test_code = read_file(test_path)
        failure_output = result["output"]

        diagnosis = diagnose_failure(main_code, test_code, failure_output)
        print(f"🩺 Diagnosis: {diagnosis.get('diagnosis')} — {diagnosis.get('reasoning', '')}")

        if diagnosis.get("diagnosis") == "BAD_TEST":
            print("🧪 Root cause is a bad test. Fixing test_main.py...")
            prompt = build_test_fix_prompt(
                main_code, test_code, failure_output, diagnosis.get("bad_test_names", [])
            )
            raw_fix = call_llm_for_test_fix(prompt)
            fixed_test_code = extract_code_from_response(raw_fix)

            save_iteration_log(service_name, attempt, diagnosis, test_code, fixed_test_code,
                                failure_output, target_file="test_main.py")
            write_file(test_path, fixed_test_code)
            print("🔧 Applied test fix. Re-testing next iteration...")

        else:
            print("🛠️  Root cause is application code. Fixing main.py...")
            prompt = build_fix_prompt(main_code, test_code, failure_output)
            raw_fix = call_llm_for_fix(prompt)
            fixed_main_code = extract_code_from_response(raw_fix)

            save_iteration_log(service_name, attempt, diagnosis, main_code, fixed_main_code,
                                failure_output, target_file="main.py")
            write_file(main_path, fixed_main_code)
            print("🔧 Applied code fix. Re-testing next iteration...")

    print(f"\n⚠️ Reached max retries ({MAX_RETRIES}) without passing all tests.")
    summary["final_status"] = "max_retries_reached"
    return summary


if __name__ == "__main__":
    SERVICE_NAME = "inventory_service"
    result = self_heal(SERVICE_NAME)
    print("\n--- Self-Healing Summary ---")
    print(json.dumps(result, indent=2))