# agents/planner.py
"""
Planner Agent — Part 2
Takes parsed legacy code structure (from parser.py) and prompts
the local LLM (via Ollama) to generate a modernization roadmap.
"""

import json
import ollama
from agents.parser import parse_legacy_file


MODEL_NAME = "llama3.2:latest"


def build_prompt(parsed_structure: dict) -> str:
    """
    Builds a prompt that forces the LLM to return ONLY valid JSON,
    describing a modernization roadmap for the parsed file.
    """
    structure_json = json.dumps(parsed_structure, indent=2)

    prompt = f"""You are a senior Python engineer specializing in legacy code modernization.

Below is the parsed structure of a legacy Python 2 file, including detected Python 2-specific issues.

PARSED STRUCTURE:
{structure_json}

Your task: generate a modernization roadmap as a JSON object with this EXACT schema:

{{
  "file": "<the filepath>",
  "summary": "<one sentence describing what this file does>",
  "conversion_steps": [
    "<step 1 description>",
    "<step 2 description>",
    "..."
  ],
  "risk_flags": [
    {{"issue": "<python2 issue>", "severity": "low|medium|high", "fix": "<how to fix it>"}}
  ],
  "estimated_complexity": "low|medium|high"
}}

RULES:
- Return ONLY the JSON object. No explanation, no markdown code fences, no extra text before or after.
- Base conversion_steps on the actual classes/functions/python2_flags provided above.
- risk_flags must cover every item in python2_flags, plus any other risks you notice.
- Be specific — reference actual function/class names from the structure, not generic advice.
"""
    return prompt


def call_llm(prompt: str) -> str:
    """Sends the prompt to the local Ollama model and returns raw text response."""
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2},  # low temperature = more consistent/structured output
    )
    return response["message"]["content"]


def clean_json_response(raw_text: str) -> str:
    """
    LLMs sometimes wrap JSON in markdown fences (```json ... ```)
    even when told not to. Strip those out before parsing.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def generate_roadmap(filepath: str) -> dict:
    """
    Full pipeline: parse the file, prompt the LLM, and return
    a validated roadmap dict. Retries once if JSON parsing fails.
    """
    parsed = parse_legacy_file(filepath)
    prompt = build_prompt(parsed)

    for attempt in range(2):  # try twice before giving up
        raw = call_llm(prompt)
        cleaned = clean_json_response(raw)
        try:
            roadmap = json.loads(cleaned)
            return roadmap
        except json.JSONDecodeError:
            if attempt == 0:
                print("⚠️  First attempt returned invalid JSON, retrying...")
                continue
            else:
                print("❌ LLM failed to return valid JSON after 2 attempts.")
                print("Raw output was:\n", raw)
                raise

    return {}


if __name__ == "__main__":
    roadmap = generate_roadmap("legacy_samples/inventory.py")
    print(json.dumps(roadmap, indent=2))