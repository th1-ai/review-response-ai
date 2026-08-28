#!/usr/bin/env python3
"""tools/narrate.py - an optional, cosmetic one-paragraph morning note.

    python3 tools/narrate.py

The ONLY place this repo calls a model. It reads the stats from the most
recent `python3 tools/run.py` pass and writes a short paragraph for a person -
never a word of it reaches a guest, and it never touches a draft (see
docs/how-it-works.md, "The central design choice").

Off by default: set `narrate.enabled: true` in config/agent.yaml to turn it
on. Uses whatever `llm.provider` is set in config/hotel.yaml, so with the
default `mock` provider it prints a canned paragraph from
fixtures/expected/narrate/, and with `interactive` it will park a prompt in
data/pending/ like any other reasoning step - see core/llm.py.

Exit codes: 0 ok (prints the note, or says narrate is off), 3 waiting on an
`interactive` answer, 1 a real error. A schema or provider error here never
fails the main loop - it only means no note this time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive, complete  # noqa: E402
from core.store import Store  # noqa: E402
from core.templates import build_prompt  # noqa: E402

SCHEMA = json.loads((REPO_ROOT / "prompts" / "schemas" / "narrate.json").read_text())


def latest_run_stats(store: Store) -> dict:
    row = store.db.execute(
        "SELECT stats_json FROM runs WHERE workflow='review-response' AND stats_json IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1").fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["stats_json"])
    except (TypeError, json.JSONDecodeError):
        return {}


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    if not settings.agent_get("narrate.enabled", False):
        print("narrate.enabled is false in config/agent.yaml - nothing to do. "
             "This is optional and off by default; see docs/how-it-works.md.")
        return 0

    store = Store(settings)
    try:
        stats = latest_run_stats(store)
        if not stats:
            print("no run stats yet - run `make run` or `make demo` first.")
            return 0
        prompt = build_prompt("narrate", settings=settings, item=stats,
                              knowledge=settings.agent_get("narrate.knowledge"),
                              fixture_id="morning-note")
        try:
            result = complete("narrate", prompt, SCHEMA, settings=settings,
                              store=store, fixture_id="morning-note")
        except LLMPendingInteractive as exc:
            print(str(exc))
            return 3
        print(result.data["narrative"])
        return 0
    except LLMError as exc:
        print(f"note skipped: {exc}", file=sys.stderr)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
