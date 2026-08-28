#!/usr/bin/env python3
"""tools/demo.py - the whole loop on the bundled fixtures, zero credentials.

    make demo
    python3 tools/demo.py

Forces `mode=shadow` regardless of config/hotel.yaml and the `mock` reviews
adapter regardless of config/agent.yaml, so this always works on a fresh
clone with a blank .env. It runs against its own database
(data/demo/demo.db) so running it twice always shows the same reviews, and
never touches data/agent.db (that is `make run`'s file).

Prints one line every check reads for the pass/fail signal:

    DEMO OK - 7 items processed, 6 drafted, 0 sent (shadow)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store, StoreError  # noqa: E402
from engine import process_reviews  # noqa: E402
from reviews_adapters import ReviewsMock  # noqa: E402


def main() -> int:
    try:
        settings = load_settings(mode="shadow")
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    store = Store(settings, path=demo_db)
    try:
        return _run_demo(settings, store)
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


def _run_demo(settings, store: Store) -> int:
    reviews_adapter = ReviewsMock(settings)
    all_reviews = reviews_adapter.list_reviews()
    unanswered = [r for r in all_reviews if not r.get("responded")]
    if not unanswered:
        print("no fixtures found in fixtures/inbound/ - nothing to demo", file=sys.stderr)
        return 1

    rules = dict(settings.agent_get("rules", {}))
    result = process_reviews(
        unanswered, rules, date.today().isoformat(),
        amenities=settings.agent_get("amenities", {}),
        signoff=settings.agent_get("signoff", {}),
        competitors=settings.agent_get("competitors", []),
        return_visit_line=settings.agent_get("return_visit_line"),
        hotel_name=settings.hotel.name)

    print(f"Review-Response AI demo - {len(unanswered)} unanswered review(s) from "
         f"fixtures/inbound/\n")

    stats = {"processed": 0, "drafted": 0, "needs_human": 0, "sent": 0}
    for entry in result.escalations:
        review = entry["review"]
        item = store.upsert_item("reviews", str(review["id"]), kind="review",
                                 payload=review, intent="escalated")
        store.transition(item.id, "needs_human", actor="agent",
                         detail={"reason": entry["reason"]})
        stats["processed"] += 1
        stats["needs_human"] += 1
        print(f"  {review['id']}: {review.get('rating')}★ on {review.get('source')} "
             f"from {review.get('guest_name')} -> ESCALATED ({entry['reason']})")

    for entry in result.drafts:
        review, draft = entry["review"], entry["draft"]
        item = store.upsert_item("reviews", str(review["id"]), kind="review",
                                 payload=review, intent=draft["band"])
        store.set_fields(item.id, draft=draft)
        store.transition(item.id, "pending_review", actor="agent",
                         detail={"band": draft["band"]})
        stats["processed"] += 1
        stats["drafted"] += 1
        scrub_note = " (competitor mention scrubbed)" if draft["scrubbed"] else ""
        print(f"  {review['id']}: {review.get('rating')}★ on {review.get('source')} "
             f"from {review.get('guest_name')} -> {draft['band']}{scrub_note}")

    print("\n" + "\n".join(result.steps))
    print(f"\n{stats['needs_human']} of {stats['processed']} need a person to look first "
         f"(2 stars and below, when escalate-low is on - see docs/safety.md).")
    print("Nothing was posted: mode is shadow, and demo never calls reply() at all.")
    print("Next: `make review` to see the drafts, or read workflows/10-review-response.md.\n")

    print(f"DEMO OK - {summary_line(stats, settings.mode)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
