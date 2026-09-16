# agents/quality.py
"""
Quality Agent — Part 8 (Phase 5)
Runs Radon (cyclomatic complexity + maintainability index) and pylint
against a generated service, then asks the LLM to summarize code
health in plain language.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import re
import subprocess
import ollama

from agents.planner import MODEL_NAME


def run_radon_complexity(main_path: str) -> list:
    """Runs `radon cc` (cyclomatic complexity) with JSON output."""
    try:
        result = subprocess.run(
            ["radon", "cc", main_path, "-j"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            parsed = json.loads(result.stdout)
            # Radon's JSON keys output by filepath; flatten to a single list
            return parsed.get(main_path, [])
        return []
    except FileNotFoundError:
        return [{"error": "radon not installed or not on PATH"}]
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return [{"error": str(e)}]


def run_radon_maintainability(main_path: str) -> dict:
    """Runs `radon mi` (maintainability index) with JSON output."""
    try:
        result = subprocess.run(
            ["radon", "mi", main_path, "-j"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            parsed = json.loads(result.stdout)
            return parsed.get(main_path, {})
        return {}
    except FileNotFoundError:
        return {"error": "radon not installed or not on PATH"}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"error": str(e)}


def run_pylint(main_path: str) -> dict:
    """
    Runs pylint and extracts its overall score (e.g. "Your code has been
    rated at 8.50/10"). Pylint doesn't have a clean JSON score field for
    this in older versions, so we parse it from the text output alongside
    the JSON messages.
    """
    try:
        result = subprocess.run(
            ["pylint", main_path, "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        messages = json.loads(result.stdout) if result.stdout.strip() else []

        # Run again in text mode just to extract the numeric score line
        score_result = subprocess.run(
            ["pylint", main_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        score_match = re.search(r"rated at ([\-\d\.]+)/10", score_result.stdout)
        score = float(score_match.group(1)) if score_match else None

        return {"score_out_of_10": score, "messages": messages}
    except FileNotFoundError:
        return {"score_out_of_10": None, "messages": [], "error": "pylint not installed or not on PATH"}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"score_out_of_10": None, "messages": [], "error": str(e)}


def build_summary_prompt(complexity: list, maintainability: dict, pylint_result: dict) -> str:
    prompt = f"""You are a senior software engineer summarizing a code quality report for a non-technical audience.

CYCLOMATIC COMPLEXITY (per function, lower is simpler):
{json.dumps(complexity, indent=2)}

MAINTAINABILITY INDEX (0-100 scale, higher is better):
{json.dumps(maintainability, indent=2)}

PYLINT SCORE (0-10 scale, higher is better):
{json.dumps(pylint_result, indent=2)}

YOUR TASK:
Write a short, plain-language summary (3-5 sentences) of this code's overall
quality and maintainability. Mention the pylint score and maintainability
rank/score if present. Only reference numbers that actually appear above —
do not invent or estimate any score. If data is missing or shows an error,
say so plainly rather than guessing a number.

Output ONLY the summary text, no headers, no JSON, no markdown formatting.
"""
    return prompt


def summarize_with_llm(complexity: list, maintainability: dict, pylint_result: dict) -> str:
    prompt = build_summary_prompt(complexity, maintainability, pylint_result)
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2},
    )
    return response["message"]["content"].strip()


def run_quality_scan(service_name: str) -> dict:
    """Full quality scan: Radon complexity + maintainability + pylint + LLM summary."""
    service_dir = os.path.join("generated", service_name)
    main_path = os.path.join(service_dir, "main.py")

    print("📊 Measuring cyclomatic complexity (radon cc)...")
    complexity = run_radon_complexity(main_path)
    print(f"   {len(complexity)} function(s) measured.")

    print("📊 Measuring maintainability index (radon mi)...")
    maintainability = run_radon_maintainability(main_path)
    mi_rank = maintainability.get("rank", "N/A")
    print(f"   Maintainability rank: {mi_rank}")

    print("📊 Running pylint...")
    pylint_result = run_pylint(main_path)
    print(f"   Pylint score: {pylint_result.get('score_out_of_10', 'N/A')}/10")

    print("📝 Generating plain-language summary...")
    summary = summarize_with_llm(complexity, maintainability, pylint_result)

    report = {
        "service_name": service_name,
        "cyclomatic_complexity": complexity,
        "maintainability_index": maintainability,
        "pylint": pylint_result,
        "summary": summary,
    }

    report_path = os.path.join(service_dir, "quality_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2))

    print(f"✅ Quality report saved to: {report_path}")
    return report


if __name__ == "__main__":
    SERVICE_NAME = "inventory_service"
    report = run_quality_scan(SERVICE_NAME)
    print("\n--- Quality Summary ---")
    print(report["summary"])
    print(f"\nMaintainability rank: {report['maintainability_index'].get('rank', 'N/A')}")
    print(f"Pylint score: {report['pylint'].get('score_out_of_10', 'N/A')}/10")