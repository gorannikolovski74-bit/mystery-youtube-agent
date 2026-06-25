# CLAUDE.md — Mystery YouTube Agent

Instructions for any AI agent (or developer) working in this repo.

## What this is
A fully automated, faceless YouTube channel for unsolved mysteries. A daily
cron job runs `run_pipeline.py`, which chains eight agents: research → script →
tts → animation → assembly → thumbnail → upload → alert.

## Project map
- `run_pipeline.py` — orchestrator. Supports `--steps a,b,c` and `--topic "..."`.
- `agents/common.py` — shared paths, env loading, logging, topics_done state,
  Anthropic client. Import helpers from here; don't re-implement them.
- `agents/research_agent.py` — Reddit + Wikipedia candidates, Claude ranking.
- `agents/script_agent.py` — Claude Sonnet, style from `config/style_profile.md`.
- `agents/{tts,animation,assembly,thumbnail,upload}_agent.py` — to be built.
- `agents/alert_agent.py` — Telegram success/error notifications.
- `config/style_profile.md` — single source of truth for tone & visuals.
- `config/apis.env` — secrets (git-ignored; copy from `apis.env.example`).
- `config/topics_done.json` — used topics, for dedup. Append-only.

## Conventions
- Code comments in **English**.
- Each agent exposes a `run()` entry point so the orchestrator can call it.
- Agents degrade gracefully when optional credentials are missing (log a
  warning, return empty) rather than crashing the whole pipeline.
- Heavy/optional deps (praw, anthropic, manim, …) are imported lazily inside
  the function that needs them, so partial runs work without installing all.
- Never commit `config/apis.env` or anything under `output/`.

## Local testing (no keys required)
```bash
python -m py_compile run_pipeline.py agents/*.py
python -m agents.research_agent --topic "Dyatlov Pass incident"   # Wikipedia only
python run_pipeline.py --steps research --topic "Tunguska event"
```
Steps that call Claude (ranking, script) need `ANTHROPIC_API_KEY` and the
`anthropic` SDK installed.

## Setup
See `README.md` for install + API key setup. After filling `config/apis.env`:
```bash
pip install -r requirements.txt
python run_pipeline.py --steps research,script --topic "Dyatlov Pass incident"
```
