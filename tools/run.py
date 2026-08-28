#!/usr/bin/env python3
"""tools/run.py - Review-Response AI's main loop: fetch -> decide -> draft -> queue.

    python3 tools/run.py --once
    python3 tools/run.py --watch
    python3 tools/run.py --once --dry-run
    python3 tools/run.py --once --limit 10

One pass: read every review the adapter knows about, drop anything already
marked responded on the platform itself, skip anything this agent has already
queued or posted, then run the deterministic engine (tools/engine.py) over
what is left. A 2-star-or-below review (when `escalate-low` is on) becomes a
`needs_human` item with no draft. Everything else becomes a `pending_review`
item with a drafted reply. Nothing is ever posted here - see
`workflows/80-review.md` and `python3 tools/review.py post`.

Exit codes: 0 ok, 1 a real error. There is no `interactive`-provider pending
state in this loop (drafting needs no model - see docs/how-it-works.md); the
optional cosmetic morning note in tools/narrate.py has its own exit code 3.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import Run, get_logger, summary_line  # noqa: E402
from core.store import Store, StoreError  # noqa: E402
from engine import process_reviews  # noqa: E402
from reviews_adapters import get_reviews  # noqa: E402

log = get_logger("run")


def agent_rules(settings) -> dict:
    return dict(settings.agent_get("rules", {}) or {})


def one_pass(settings, store: Store, *, limit: int, today_iso: str | None = None) -> dict:
    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0, "skipped": 0}
    today_iso = today_iso or date.today().isoformat()
    with Run("review-response", settings, store) as run:
        reviews_adapter = get_reviews(settings)
        all_reviews = reviews_adapter.list_reviews()
        unanswered = [r for r in all_reviews if not r.get("responded")][:limit] \
            if limit else [r for r in all_reviews if not r.get("responded")]
        seen = store.already_processed(
            "reviews", [str(r.get("id")) for r in unanswered if r.get("id")])
        new_reviews = [r for r in unanswered if str(r.get("id")) not in seen]
        stats["skipped"] = len(unanswered) - len(new_reviews)

        result = process_reviews(
            new_reviews, agent_rules(settings), today_iso,
            amenities=settings.agent_get("amenities", {}),
            signoff=settings.agent_get("signoff", {}),
            competitors=settings.agent_get("competitors", []),
            return_visit_line=settings.agent_get("return_visit_line"),
            hotel_name=settings.hotel.name)

        for entry in result.escalations:
            review = entry["review"]
            item = store.upsert_item("reviews", str(review["id"]), kind="review",
                                     payload=review, intent="escalated")
            store.transition(item.id, "needs_human", actor="agent",
                             detail={"reason": entry["reason"]})
            stats["processed"] += 1
            stats["needs_human"] += 1
            log.info("escalated", item_id=item.id, source=review.get("source"),
                     rating=review.get("rating"))

        for entry in result.drafts:
            review, draft = entry["review"], entry["draft"]
            item = store.upsert_item("reviews", str(review["id"]), kind="review",
                                     payload=review, intent=draft["band"])
            store.set_fields(item.id, draft=draft)
            store.transition(item.id, "pending_review", actor="agent",
                             detail={"band": draft["band"], "scrubbed": draft["scrubbed"]})
            stats["processed"] += 1
            stats["drafted"] += 1
            log.info("drafted", item_id=item.id, source=review.get("source"),
                     band=draft["band"])

        for line in result.steps:
            log.info("step", text=line)
        reaped = store.reap_stuck_sending()
        if reaped:
            log.warn("reaped stuck sends", count=len(reaped))
        run.stats = dict(stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="run a single pass (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep running on the configured interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute everything, write nothing, even in live mode")
    parser.add_argument("--limit", type=int, default=0, help="max reviews per pass (0 = all)")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 14400)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        if args.watch:
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 14400))
            while True:
                stats = one_pass(settings, store, limit=args.limit)
                print(summary_line(stats, settings.mode))
                time.sleep(poll_seconds)
        stats = one_pass(settings, store, limit=args.limit)
        print(summary_line(stats, settings.mode))
        return 0
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
