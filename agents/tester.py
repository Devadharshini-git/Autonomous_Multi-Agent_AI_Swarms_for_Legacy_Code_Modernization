# agents/tester.py
"""
Tester Agent — Part 4
Generates PyTest test cases for a converted service using the LLM,
then builds/runs a Docker sandbox to execute them safely.
"""

import json
import os
import re
import subprocess
import ollama

from agents.planner import MODEL_NAME


def build_test_prompt(service_code: str, service_name: str) -> str:
    prompt = f"""You are a senior Python test engineer. Write PyTest test cases for the following Python code.

CODE TO TEST:
```python
{service_code}
```

CRITICAL RULES — read carefully, these prevent common mistakes:
- Import EVERY class and function you actually use in your tests, including data classes like InventoryItem. Check your imports against every name you reference.
- Test ONLY the actual behavior visible in the code above. Do NOT assume a function reads files, takes arguments, or has side effects unless you can see that in the code itself. Do not invent file I/O, mocking, or external state.
- If a function's job is to print output (uses print()) and does not return a value, do NOT assert on its return value. Instead use pytest's built-in `capsys` fixture to capture and assert on printed output, e.g.:
  def test_foo(capsys):
      foo()
      captured = capsys.readouterr()
      assert "expected text" in captured.out
- If a function returns a value, assert on the actual return value, not on printed output.
- Before writing each test, re-read the function's actual signature and body above to confirm what it takes in and gives back.

OUTPUT FORMAT:
- Output ONLY valid Python test code, wrapped in a single ```python code fence.
- Import needed names with: from main import <name1>, <name2>, ...
- Do NOT test the FastAPI routes (no TestClient) — only test the underlying business logic functions/classes directly.
- Cover normal/expected input and one genuine edge case per function (e.g. empty list, zero values) — only if that edge case is plausible given the actual code.
- Use plain `assert` statements, standard PyTest style, no unittest.TestCase classes.
- Name test functions descriptively: test_<function_name>_<scenario>.
"""
    return prompt

def call_llm_for_tests(prompt: str) -> str:
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
    )
    return response["message"]["content"]


def extract_code_from_response(raw_text: str) -> str:
    match = re.search(r"```python\s*\n(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", raw_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw_text.strip()


def generate_tests(service_name: str) -> str:
    """Reads the generated service and asks the LLM to write tests for it."""
    service_path = os.path.join("generated", service_name, "main.py")
    with open(service_path, "r") as f:
        service_code = f.read()

    prompt = build_test_prompt(service_code, service_name)
    raw_response = call_llm_for_tests(prompt)
    test_code = extract_code_from_response(raw_response)

    test_path = os.path.join("generated", service_name, "test_main.py")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(test_code)

    print(f"✅ Saved generated tests to: {test_path}")
    return test_path


if __name__ == "__main__":
    SERVICE_NAME = "inventory_service"
    print("Generating tests for:", SERVICE_NAME)
    generate_tests(SERVICE_NAME)