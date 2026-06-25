"""Main orchestrator for the Mystery YouTube Agent.

Runs the full daily pipeline, or a subset of steps for testing. Agents are
imported lazily per step so you can run e.g. research+script+tts without having
the heavier animation/upload dependencies installed yet.

Examples:
    python run_pipeline.py                                  # full pipeline
    python run_pipeline.py --steps research,script,tts      # partial run
    python run_pipeline.py --steps research,script --topic "Dyatlov Pass Incident"
"""
from __future__ import annotations

import argparse

from agents.common import get_logger, load_env

log = get_logger("pipeline")

# Canonical order of the pipeline.
ALL_STEPS = [
    "research",
    "script",
    "tts",
    "animation",
    "assembly",
    "thumbnail",
    "upload",
    "alert",
]


def run(steps: list[str] | None = None, topic_override: str | None = None) -> dict:
    """Execute the pipeline steps in order, threading state between them."""
    load_env()
    steps = steps or ALL_STEPS
    state: dict = {}
    step = "init"
    try:
        if "research" in steps:
            step = "research"
            from agents import research_agent

            state["topic"] = research_agent.run(topic_override=topic_override)
            log.info("Topic: %s", state["topic"]["topic"])

        if "script" in steps:
            step = "script"
            from agents import script_agent

            state["script"] = script_agent.run(state["topic"])

        if "tts" in steps:
            step = "tts"
            from agents import tts_agent

            state["audio"] = tts_agent.run(state["script"])

        if "animation" in steps:
            step = "animation"
            from agents import animation_agent

            state["scenes"] = animation_agent.run(state["script"])

        if "assembly" in steps:
            step = "assembly"
            from agents import assembly_agent

            state["video"] = assembly_agent.run(state["scenes"], state["audio"])

        if "thumbnail" in steps:
            step = "thumbnail"
            from agents import thumbnail_agent

            state["thumb"] = thumbnail_agent.run(state["topic"])

        if "upload" in steps:
            step = "upload"
            from agents import upload_agent

            state["url"] = upload_agent.run(
                state["video"], state["thumb"], state["topic"]
            )

        if "alert" in steps:
            step = "alert"
            from agents import alert_agent

            alert_agent.success(state["topic"]["topic"], state.get("url", "n/a"))

    except Exception as exc:  # notify on any failure, then re-raise
        log.exception("Pipeline failed at step '%s'", step)
        try:
            from agents import alert_agent

            alert_agent.error(step, str(exc))
        except Exception:  # never let alerting mask the real error
            log.warning("Could not send failure alert.")
        raise

    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Mystery YouTube Agent pipeline.")
    parser.add_argument(
        "--steps",
        help="Comma-separated subset of steps to run (default: all).",
        default=",".join(ALL_STEPS),
    )
    parser.add_argument("--topic", help="Force a specific topic for the research step.")
    args = parser.parse_args()

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        parser.error(f"Unknown step(s): {unknown}. Valid: {ALL_STEPS}")

    run(steps=steps, topic_override=args.topic)


if __name__ == "__main__":
    main()
