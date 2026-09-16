# agents/security.py
"""
Security Agent — Part 7 (Phase 5)
Runs Bandit (static analysis) and safety (dependency CVE checks)
against a generated service, then asks the LLM to summarize the
findings in plain language for the dashboard/demo.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import subprocess
import ollama

from agents.planner import MODEL_NAME


def run_bandit(service_dir: str) -> dict:
    """
    Runs Bandit against the generated service's main.py.
    Bandit's own JSON output format is used directly — no LLM involved
    in the scan itself, only deterministic static analysis.
    """
    main_path = os.path.join(service_dir, "main.py")

    try:
        result = subprocess.run(
            ["bandit", "-f", "json", main_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Bandit exits with a non-zero code when it FINDS issues — that's
        # expected behavior, not a crash. Only treat it as an error if
        # stdout isn't valid JSON at all.
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {"results": [], "errors": [{"reason": result.stderr}]}
    except FileNotFoundError:
        return {"results": [], "errors": [{"reason": "bandit not installed or not on PATH"}]}
    except subprocess.TimeoutExpired:
        return {"results": [], "errors": [{"reason": "bandit scan timed out"}]}
    except json.JSONDecodeError:
        return {"results": [], "errors": [{"reason": "could not parse bandit output"}]}


def run_safety(service_dir: str) -> dict:
    """
    Runs safety against the generated service's requirements.txt.
    Checks installed/pinned package versions against known CVE databases.
    """
    req_path = os.path.join(service_dir, "requirements.txt")

    if not os.path.exists(req_path):
        return {"vulnerabilities": [], "errors": [{"reason": "requirements.txt not found"}]}

    try:
        result = subprocess.run(
            ["safety", "check", "-r", req_path, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout.strip():
            parsed = json.loads(result.stdout)
            # safety's JSON shape varies by version; normalize to a list either way
            if isinstance(parsed, dict) and "vulnerabilities" in parsed:
                return parsed
            elif isinstance(parsed, list):
                return {"vulnerabilities": parsed, "errors": []}
            return {"vulnerabilities": [], "errors": []}
        return {"vulnerabilities": [], "errors": [{"reason": result.stderr}]}
    except FileNotFoundError:
        return {"vulnerabilities": [], "errors": [{"reason": "safety not installed or not on PATH"}]}
    except subprocess.TimeoutExpired:
        return {"vulnerabilities": [], "errors": [{"reason": "safety scan timed out"}]}
    except json.JSONDecodeError:
        return {"vulnerabilities": [], "errors": [{"reason": "could not parse safety output"}]}


def build_summary_prompt(bandit_results: dict, safety_results: dict) -> str:
    prompt = f"""You are a security engineer summarizing a scan report for a non-technical audience.

BANDIT STATIC ANALYSIS RESULTS (code-level issues):
{json.dumps(bandit_results.get("results", []), indent=2)}

SAFETY DEPENDENCY SCAN RESULTS (known CVEs in dependencies):
{json.dumps(safety_results.get("vulnerabilities", []), indent=2)}

YOUR TASK:
Write a short, plain-language summary (3-5 sentences) of the security posture
of this generated service. Mention the number and severity of any real findings.
If there are zero findings in both scans, say so clearly and positively.
Do not invent findings that aren't in the data above. Do not use technical
jargon without briefly explaining it.

Output ONLY the summary text, no headers, no JSON, no markdown formatting.
"""
    return prompt


def summarize_with_llm(bandit_results: dict, safety_results: dict) -> str:
    prompt = build_summary_prompt(bandit_results, safety_results)
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2},
    )
    return response["message"]["content"].strip()


def run_security_scan(service_name: str) -> dict:
    """
    Full security scan: Bandit + safety + LLM summary.
    Returns a structured report saved to the service's folder.
    """
    service_dir = os.path.join("generated", service_name)

    print("🔎 Running Bandit static analysis...")
    bandit_results = run_bandit(service_dir)
    bandit_issue_count = len(bandit_results.get("results", []))
    print(f"   Found {bandit_issue_count} Bandit finding(s).")

    print("🔎 Running safety dependency scan...")
    safety_results = run_safety(service_dir)
    safety_issue_count = len(safety_results.get("vulnerabilities", []))
    print(f"   Found {safety_issue_count} dependency vulnerability finding(s).")

    print("📝 Generating plain-language summary...")
    summary = summarize_with_llm(bandit_results, safety_results)

    report = {
        "service_name": service_name,
        "bandit_issue_count": bandit_issue_count,
        "safety_issue_count": safety_issue_count,
        "bandit_findings": bandit_results.get("results", []),
        "safety_findings": safety_results.get("vulnerabilities", []),
        "summary": summary,
    }

    report_path = os.path.join(service_dir, "security_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(report, indent=2))

    print(f"✅ Security report saved to: {report_path}")
    return report


if __name__ == "__main__":
    SERVICE_NAME = "inventory_service"
    report = run_security_scan(SERVICE_NAME)
    print("\n--- Security Summary ---")
    print(report["summary"])
    print(f"\nBandit findings: {report['bandit_issue_count']}")
    print(f"Dependency vulnerabilities: {report['safety_issue_count']}")