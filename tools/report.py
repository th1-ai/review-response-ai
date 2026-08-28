#!/usr/bin/env python3
"""tools/report.py - what the agent did, and what it cost.

    make report
    python3 tools/report.py
    python3 tools/report.py --export

The numbers the roster promises are about coverage and speed, not volume:
"100% review-response coverage within 24h; responded-to listings convert
higher." This prints the numbers that let you check that promise against
what actually happened, plus the two numbers every agent in this family
reports: the edit rate (how much you are still rewriting the drafts) and the
spend (near-zero here - see below).

`--export` also writes the same rows to `systems.sheets.adapter` (csv by
default: `data/exports/review_response_report.csv`), so you can hand a GM a
file instead of a terminal.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_sheets  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.store import Store  # noqa: E402


def gather(store: Store) -> dict:
    counts = store.counts()
    total = sum(counts.values())
    drafted = sum(counts.get(s, 0) for s in
                 ("pending_review", "approved", "edited", "sending", "sent", "rejected", "stale"))
    escalated = counts.get("needs_human", 0)
    posted = counts.get("sent", 0)

    edited_ids = {r["item_id"] for r in store.db.execute(
        "SELECT DISTINCT item_id FROM events WHERE action='status:edited'").fetchall()
        if r["item_id"]}
    scrubbed = store.db.execute(
        "SELECT COUNT(*) AS n FROM items WHERE draft_json LIKE '%\"scrubbed\": true%'"
    ).fetchone()["n"]

    ages = []
    for row in store.db.execute(
        "SELECT created_at, sent_at FROM items WHERE sent_at IS NOT NULL").fetchall():
        try:
            created = datetime.fromisoformat(row["created_at"])
            sent = datetime.fromisoformat(row["sent_at"])
            ages.append((sent - created).total_seconds() / 3600)
        except (TypeError, ValueError):
            continue

    cost_usd = 0.0
    for row in store.db.execute(
        "SELECT detail_json FROM events WHERE action='llm_call'").fetchall():
        try:
            cost_usd += float((json.loads(row["detail_json"]) or {}).get("cost_usd") or 0.0)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    return {
        "total_items": total, "drafted": drafted, "escalated": escalated, "posted": posted,
        "coverage_pct": round(100 * posted / total, 1) if total else 0.0,
        "edit_rate_pct": round(100 * len(edited_ids) / drafted, 1) if drafted else 0.0,
        "competitor_scrubs": scrubbed,
        "avg_hours_to_post": round(sum(ages) / len(ages), 1) if ages else None,
        "llm_cost_usd": round(cost_usd, 4),
        "by_status": counts,
    }


def print_report(stats: dict, mode: str) -> None:
    print("Review-Response AI - report\n")
    print(f"  Reviews seen so far:     {stats['total_items']}")
    print(f"  Drafted:                 {stats['drafted']}")
    print(f"  Escalated to a human:    {stats['escalated']}")
    print(f"  Posted:                  {stats['posted']} "
         f"({stats['coverage_pct']}% of everything seen)")
    print(f"  Edit rate:               {stats['edit_rate_pct']}% of drafted items were "
         f"rewritten before posting")
    print(f"  Competitor mentions scrubbed: {stats['competitor_scrubs']}")
    avg = stats["avg_hours_to_post"]
    print(f"  Average time to post:    {avg} hour(s)" if avg is not None
         else "  Average time to post:    no items posted yet")
    print(f"  LLM spend so far:        ${stats['llm_cost_usd']} "
         f"(drafting is deterministic - this is only the optional morning note)")
    print(f"\n  By status: " + ", ".join(f"{k}={v}" for k, v in sorted(stats["by_status"].items())))
    print(f"\n  Mode: {mode}. The roster's promise is 100% coverage within 24h - "
         f"coverage above is against everything the agent has ever seen; check "
         f"`docs/how-it-works.md` for what actually delivers the 24h part "
         f"(it is your schedule cadence, not a feature).")


def export_csv(settings, stats: dict) -> str:
    sheets = get_sheets(settings)
    row = [datetime.now(timezone.utc).isoformat(timespec="seconds"), stats["total_items"],
          stats["drafted"], stats["escalated"], stats["posted"], stats["coverage_pct"],
          stats["edit_rate_pct"], stats["competitor_scrubs"], stats["avg_hours_to_post"] or "",
          stats["llm_cost_usd"]]
    header = ["generated_at", "total_items", "drafted", "escalated", "posted",
             "coverage_pct", "edit_rate_pct", "competitor_scrubs", "avg_hours_to_post",
             "llm_cost_usd"]
    sheets.append("review_response_report", [header, row])
    return "review_response_report"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", action="store_true",
                        help="also write the numbers via systems.sheets.adapter")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        stats = gather(store)
        print_report(stats, settings.mode)
        if args.export:
            sheet = export_csv(settings, stats)
            print(f"\nExported to: {sheet} "
                 f"({settings.systems.sheets.adapter} adapter)")
        return 0
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
