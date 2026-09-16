# pipeline/state.py
"""
Shared state object passed between all nodes in the LangGraph pipeline.
Every node reads from and writes to this same structure.
"""

from typing import TypedDict, Optional


class PipelineState(TypedDict):
    # Input
    legacy_filepath: str
    service_name: str

    # Planner output
    roadmap: Optional[dict]

    # Coder output
    generated: bool

    # Tester output
    tests_passed: Optional[bool]
    test_output: Optional[str]

    # Debugger output
    heal_attempts: int
    max_heal_attempts: int
    healed: Optional[bool]

    # Security Agent output
    security_report: Optional[dict]

    # Quality Agent output
    quality_report: Optional[dict]

    # Final status
    status: Optional[str]
    