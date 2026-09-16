
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from langgraph.graph import StateGraph, END

from pipeline.state import PipelineState
from agents.planner import generate_roadmap
from agents.coder import convert_legacy_code, wrap_as_fastapi_service, save_service
from agents.tester import generate_tests
from agents.debugger import (
    diagnose_failure,
    build_fix_prompt,
    call_llm_for_fix,
    build_test_fix_prompt,
    call_llm_for_test_fix,
    extract_code_from_response,
    save_iteration_log,
    read_file,
    write_file,
)
from agents.security import run_security_scan
from agents.quality import run_quality_scan
from sandbox.runner import run_tests_in_sandbox


# ---------- NODE FUNCTIONS ----------

def planner_node(state: PipelineState) -> dict:
    print("\n🧭 [Planner Node] Generating modernization roadmap...")
    roadmap = generate_roadmap(state["legacy_filepath"])
    print(json.dumps(roadmap, indent=2))
    return {"roadmap": roadmap, "status": "planned"}


def coder_node(state: PipelineState) -> dict:
    print("\n🛠️  [Coder Node] Converting legacy code + wrapping as FastAPI service...")
    converted = convert_legacy_code(state["legacy_filepath"], state["roadmap"])
    service_code = wrap_as_fastapi_service(converted, state["service_name"])
    save_service(service_code, state["service_name"])

    print("🧪 [Coder Node] Generating tests for the new service...")
    generate_tests(state["service_name"])

    return {"generated": True, "status": "coded"}


def tester_node(state: PipelineState) -> dict:
    print("\n🏃 [Tester Node] Running tests in Docker sandbox...")
    result = run_tests_in_sandbox(state["service_name"])
    return {
        "tests_passed": result["tests_passed"],
        "test_output": result["output"],
        "status": "tested",
    }


def debugger_node(state: PipelineState) -> dict:
    attempt = state["heal_attempts"] + 1
    print(f"\n🔧 [Debugger Node] Self-heal attempt {attempt}/{state['max_heal_attempts']}...")

    main_path = os.path.join("generated", state["service_name"], "main.py")
    test_path = os.path.join("generated", state["service_name"], "test_main.py")

    main_code = read_file(main_path)
    test_code = read_file(test_path)
    failure_output = state["test_output"]

    print("🩺 [Debugger Node] Diagnosing root cause (code bug vs bad test)...")
    diagnosis = diagnose_failure(main_code, test_code, failure_output)
    print(f"🩺 Diagnosis: {diagnosis.get('diagnosis')} — {diagnosis.get('reasoning', '')}")

    if diagnosis.get("diagnosis") == "BAD_TEST":
        print("🧪 [Debugger Node] Root cause is a bad test. Fixing test_main.py...")
        prompt = build_test_fix_prompt(
            main_code, test_code, failure_output, diagnosis.get("bad_test_names", [])
        )
        raw_fix = call_llm_for_test_fix(prompt)
        fixed_test_code = extract_code_from_response(raw_fix)

        save_iteration_log(state["service_name"], attempt, diagnosis, test_code, fixed_test_code,
                            failure_output, target_file="test_main.py")
        write_file(test_path, fixed_test_code)

    else:
        print("🛠️  [Debugger Node] Root cause is application code. Fixing main.py...")
        prompt = build_fix_prompt(main_code, test_code, failure_output)
        raw_fix = call_llm_for_fix(prompt)
        fixed_main_code = extract_code_from_response(raw_fix)

        save_iteration_log(state["service_name"], attempt, diagnosis, main_code, fixed_main_code,
                            failure_output, target_file="main.py")
        write_file(main_path, fixed_main_code)

    return {"heal_attempts": attempt, "status": "healing"}


def security_node(state: PipelineState) -> dict:
    print("\n🔒 [Security Node] Running Bandit + safety scans...")
    report = run_security_scan(state["service_name"])
    print(f"   Summary: {report['summary']}")
    return {"security_report": report, "status": "security_scanned"}


def quality_node(state: PipelineState) -> dict:
    print("\n📊 [Quality Node] Running Radon + pylint scans...")
    report = run_quality_scan(state["service_name"])
    print(f"   Summary: {report['summary']}")
    return {"quality_report": report, "status": "quality_scanned"}


def finish_node(state: PipelineState) -> dict:
    if state["tests_passed"]:
        final_status = "success"
    else:
        final_status = "max_retries_reached"
    print(f"\n🏁 [Finish Node] Pipeline complete. Final status: {final_status}")
    return {"status": final_status, "healed": state["tests_passed"]}


# ---------- CONDITIONAL EDGE LOGIC ----------

def route_after_tester(state: PipelineState) -> str:
    """Decides where to go after the Tester node runs."""
    if state["tests_passed"]:
        return "security"
    if state["heal_attempts"] >= state["max_heal_attempts"]:
        return "finish"
    return "debugger"


# ---------- BUILD THE GRAPH ----------

def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("planner", planner_node)
    graph.add_node("coder", coder_node)
    graph.add_node("tester", tester_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("security", security_node)
    graph.add_node("quality", quality_node)
    graph.add_node("finish", finish_node)

    graph.set_entry_point("planner")

    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "tester")

    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {
            "debugger": "debugger",
            "security": "security",
            "finish": "finish",
        },
    )

    graph.add_edge("debugger", "tester")
    graph.add_edge("security", "quality")
    graph.add_edge("quality", "finish")

    graph.add_edge("finish", END)

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()

    initial_state: PipelineState = {
        "legacy_filepath": "legacy_samples/inventory.py",
        "service_name": "inventory_service",
        "roadmap": None,
        "generated": False,
        "tests_passed": None,
        "test_output": None,
        "heal_attempts": 0,
        "max_heal_attempts": 5,
        "healed": None,
        "security_report": None,
        "quality_report": None,
        "status": "starting",
    }

    final_state = app.invoke(initial_state)

    print("\n--- FINAL PIPELINE STATE ---")
    print(json.dumps(
        {k: v for k, v in final_state.items()
         if k not in ("roadmap", "test_output", "security_report", "quality_report")},
        indent=2
    ))

    if final_state.get("security_report"):
        print("\n--- Security Summary ---")
        print(final_state["security_report"]["summary"])

    if final_state.get("quality_report"):
        print("\n--- Quality Summary ---")
        print(final_state["quality_report"]["summary"])