from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GenerationAgentResult:
    artifact: Any
    raw_response: str
    validation_errors: list[str]
    attempts: int
    transcript: list[dict[str, str]]


def _call_chat(model_cfg: dict, messages: list[dict[str, str]], temperature: float) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=model_cfg["base_url"], api_key=model_cfg["api_key"])
    response = client.chat.completions.create(
        model=model_cfg["model"],
        messages=messages,
        max_tokens=model_cfg.get("max_output_tokens", 8192),
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def run_generation_agent(
    *,
    model_cfg: dict,
    task_prompt: str,
    system_prompt: str,
    extract_artifact: Callable[[str], Any],
    validate_artifact: Callable[[Any], list[str]],
    max_steps: int = 4,
    temperature: float = 0.25,
) -> GenerationAgentResult:
    """Run a simple plan/draft/validate/repair loop for AI-generated project artifacts."""

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\n"
                "You are operating as a standard generation agent. Work in this loop:\n"
                "1. Build a short plan for the artifact.\n"
                "2. Draft the complete artifact in the exact requested format.\n"
                "3. When validation errors are returned, repair the complete artifact instead of patching fragments.\n"
                "4. Stop only when the artifact satisfies the requested structure.\n"
                "Do not ask follow-up questions. Make conservative assumptions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{task_prompt}\n\n"
                "Return the complete artifact. You may include a brief plan before it, but the artifact itself "
                "must be in the exact requested code block or JSON format so it can be extracted automatically."
            ),
        },
    ]

    last_artifact: Any = None
    last_raw = ""
    last_errors: list[str] = ["The generation agent did not run."]

    for attempt in range(1, max(1, max_steps) + 1):
        raw = _call_chat(model_cfg, messages, temperature)
        last_raw = raw
        messages.append({"role": "assistant", "content": raw})

        try:
            artifact = extract_artifact(raw)
            errors = validate_artifact(artifact)
        except Exception as e:
            artifact = None
            errors = [f"Artifact extraction or validation failed: {e}"]

        last_artifact = artifact
        last_errors = errors
        if not errors:
            return GenerationAgentResult(
                artifact=artifact,
                raw_response=raw,
                validation_errors=[],
                attempts=attempt,
                transcript=messages,
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    "Local validation found these problems:\n"
                    + "\n".join(f"- {err}" for err in errors)
                    + "\n\nRepair the artifact and return the complete corrected artifact again. "
                    "Do not return only a diff or partial snippet."
                ),
            }
        )

    return GenerationAgentResult(
        artifact=last_artifact,
        raw_response=last_raw,
        validation_errors=last_errors,
        attempts=max(1, max_steps),
        transcript=messages,
    )
