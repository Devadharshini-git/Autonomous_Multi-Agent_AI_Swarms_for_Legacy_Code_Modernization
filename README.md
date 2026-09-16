# Phoenix — Autonomous Multi-Agent AI Swarm for Legacy Code Modernization

A self-healing multi-agent pipeline that autonomously converts legacy Python 2
code into modern, tested, containerized Python 3 / FastAPI microservices.

## Status: Review 1 (~25% complete)

## Team
| Member | Responsibility |
|---|---|
| Deva | Legacy Code Analysis + Parser + Planner Agent + Docker Sandbox |
| Saitharun | Coder Agent + Code Generation |
| Rithiga | LangGraph Orchestration + Debugger Agent |
| Subhiksha | Basic Testing + Self-Healing Loop wiring |

## Architecture
Legacy Python 2 file
↓
[Parser Agent] — ast + regex fallback, detects Python 2-specific syntax
↓
[Planner Agent] — Ollama/llama3.2 generates a JSON modernization roadmap
↓
[Coder Agent] — converts to Python 3, wraps as a FastAPI microservice
↓
[Tester Agent] — generates PyTest cases, runs in an isolated Docker sandbox
↓
tests pass? ──No──→ [Debugger Agent] ──→ back to Tester
│ │
│ diagnoses CODE_BUG vs BAD_TEST
│ before deciding which file to fix
│
Yes
↓
Done

All of this is orchestrated as a formal LangGraph state machine (`pipeline/graph.py`).

## Tech Stack
- LLM: Ollama, `llama3.2:latest` (local, free, no API key)
- Orchestration: LangGraph
- Parsing: Python `ast` + regex fallback
- API layer: FastAPI
- Testing: PyTest
- Sandbox: Docker (via the `docker` Python SDK)
- Dev environment: Windows, PowerShell, VS Code

## Setup
1. Install Python 3.11, Docker Desktop, Ollama
2. `ollama pull llama3.2:latest`
3. `python -m venv venv` then activate it
4. `pip install -r requirements.txt`

## Run the full pipeline
```powershell
python pipeline/graph.py
```

## Known limitations (honest, current state)
- Uses `llama3.2:latest` (2GB local model), not `llama3.1:8b` as originally
  scoped — chosen for speed on limited hardware. Smaller models are more
  prone to arithmetic and JSON-formatting errors, which shaped several
  design decisions below.
- The Debugger Agent diagnoses whether a test failure is caused by broken
  application code or by an incorrect/invalid test (e.g. a bad expected
  value or a mismatched fixture) before deciding what to fix — this was
  added after discovering the LLM would otherwise "fix" correct code to
  satisfy a wrong test.
- The Coder Agent's FastAPI route generation is currently hardcoded to the
  sample file's entrypoint pattern, not yet fully automatic for arbitrary
  legacy files.
- Security Agent, Quality Agent, CI/CD, and the Streamlit dashboard are
  out of scope for this review (~25% milestone) — planned for later phases.

## Project Structure
legacy-modernization-swarm/
├── agents/ # Parser, Planner, Coder, Tester, Debugger
├── sandbox/ # Docker sandbox runner
├── pipeline/ # LangGraph state machine
├── legacy_samples/ # Sample legacy Python 2 files
├── generated/ # Output: converted services + tests + healing logs
└── requirements.txt