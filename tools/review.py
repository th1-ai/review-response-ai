#!/usr/bin/env python3
"""tools/review.py - work the review queue: list / show / approve / edit / reject / notify / post.

    python3 tools/review.py list [--status pending_review] [--kind review]
    python3 tools/review.py show <id>
    python3 tools/review.py approve <id> [--note "..."]
    python3 tools/review.py edit <id> --body-file draft.txt [--note "..."]
    python3 tools/review.py reject <id> --reason "wrong tone"
    python3 tools/review.py notify <id>            # alert the duty manager (needs_human items)
    python3 tools/review.py post                   # post everything approved/edited
    python3 tools/review.py retry <id>              # re-queue a failed post
    python3 tools/review.py stale                   # go-live step: see below

Only this tool writes `approved` / `edited` / `rejected` (core/review.py).
Only `post` writes `sending` / `sent`. Nothing here bypasses `mode: shadow` -
`mode: shadow` blocks every write, approved or not; only `mode: live` lets an
approved item actually post - see docs/safety.md.

`needs_human` items (2 stars and below, when `escalate-low` is on) have no
draft to approve. `notify` tells your duty manager about one; once it is
handled outside this tool, clear it from the queue with `reject --reason`.

`stale` is a `workflows/90-go-live.md` step: it moves every item still
waiting (drafted, escalated, approved or edited) to `stale` so nothing built
up while you were only testing in shadow goes out by surprise the moment you
flip to `live`. Every approve / edit / reject / notify / post decision is
also written to today's `data/logs/*.jsonl`, alongside the run-level log
lines, with the item id and actor - see `docs/safety.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.review import (WriteBlocked, approve, edit, list_queue, reject, retry,  # noqa: E402
                         show, stale_backlog)
from core.store import Store, StoreError  # noqa: E402
from reviews_adapters import get_reviews  # noqa: E402

log = get_logger("review")


def _print_item_line(item) -> None:
    payload = item.payload or {}
    title = (payload.get("title") or payload.get("body") or "")[:45]
    rating = payload.get("rating", "-")
    # `item.is_sample` is set by core (core/store.py) for anything read
    # through a mock adapter outside `make demo` - see docs/integrations.md
    # "Sample data is labelled". A human working the real queue must never
    # mistake a shipped fixture for a real guest review.
    marker = "  [SAMPLE DATA]" if item.is_sample else ""
    print(f"  {item.id}  {item.review_status:<14} {item.intent or '-':<11} "
         f"{str(payload.get('source', '-')):<12} {rating}★  {title}{marker}")


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind="review", limit=args.limit)
    if not items:
        print("Nothing is waiting for you.")
        return 0
    print(f"{len(items)} item(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    print("\nRun `python3 tools/review.py show <id>` for the full draft.")
    return 0


def cmd_show(store, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if (detail["item"].get("payload") or {}).get("_sample"):
        print("[SAMPLE DATA] this item was read through a mock adapter, not your "
             "property - see docs/integrations.md.\n")
    print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_approve(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    if not item.draft:
        print(f"error: {args.id} has no draft to approve (it may be escalated - "
             f"see `python3 tools/review.py show {args.id}`)", file=sys.stderr)
        return 1
    approve(store, args.id, note=args.note or "")
    log.info("human decision", action="approve", item_id=args.id, note=args.note or "")
    print(f"approved {args.id} - now in the post queue")
    return 0


def cmd_edit(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    body = Path(args.body_file).read_text(encoding="utf-8")
    new_draft = dict(item.draft or {})
    new_draft["body"] = body
    edit(store, args.id, new_draft, note=args.note or "")
    log.info("human decision", action="edit", item_id=args.id, note=args.note or "")
    print(f"edited {args.id} - now in the post queue")
    return 0


def cmd_reject(store, args) -> int:
    reject(store, args.id, reason=args.reason or "")
    log.info("human decision", action="reject", item_id=args.id, reason=args.reason or "")
    print(f"rejected {args.id}")
    return 0


def cmd_retry(store, args) -> int:
    retry(store, args.id)
    log.info("human decision", action="retry", item_id=args.id)
    print(f"queued {args.id} for another post attempt")
    return 0


def cmd_stale(store, args) -> int:
    moved = stale_backlog(store)
    log.info("human decision", action="stale", count=len(moved), item_ids=moved)
    print(f"marked {len(moved)} item(s) stale. Nothing from before go-live will be sent.")
    return 0


def cmd_notify(store, settings, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    if item.review_status != "needs_human":
        print(f"error: {args.id} is '{item.review_status}', not needs_human", file=sys.stderr)
        return 1
    payload = item.payload or {}
    text = (f"Review needs a person: {payload.get('rating', '?')} stars on "
           f"{payload.get('source', '?')} from {payload.get('guest_name', 'a guest')}. "
           f"\"{(payload.get('title') or payload.get('body') or '')[:120]}\"")
    try:
        messaging = get_messaging(settings)
        result = messaging.notify_staff(text, item=item)
    except WriteBlocked:
        if settings.mode == "shadow":
            print(f"blocked: {args.id} is a needs_human escalation with no draft to approve -\n"
                 "  shadow mode blocks every write, including this internal staff alert. For\n"
                 "  now, tell your duty manager directly. Once you trust the escalation flow,\n"
                 "  workflows/90-go-live.md covers switching to live mode, which is what\n"
                 "  actually lets `notify` send.")
        else:
            print(f"blocked: {args.id} could not be sent - see `make doctor` for what is missing.")
        return 1
    log.info("human decision", action="notify", item_id=args.id)
    print(f"notified the duty manager about {args.id}: {result}")
    print(f"Once it is handled, clear it with: "
         f"python3 tools/review.py reject {args.id} --reason \"handled by duty manager\"")
    return 0


def cmd_post(store, settings, args) -> int:
    claimed = store.claim_for_send(limit=args.limit)
    if not claimed:
        print("Nothing approved or edited is waiting to post.")
        return 0
    reviews = get_reviews(settings)
    sent, failed = 0, 0
    for item in claimed:
        draft = item.draft or {}
        review_id = (item.payload or {}).get("id") or item.external_id
        try:
            result = reviews.reply(review_id, draft.get("body", ""), item=item)
        except WriteBlocked as exc:
            # Not a failure: the mode blocked it. The approval stands for go-live.
            store.transition(item.id, "approved", "agent", {"blocked": str(exc)[:200]})
            log.warn("human decision", action="post_blocked", item_id=item.id, reason=str(exc))
            print(f"blocked {item.id} (approval kept): {exc}")
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on, never crash the batch
            store.mark_send_failed(item.id, str(exc))
            log.warn("human decision", action="post_failed", item_id=item.id, reason=str(exc))
            print(f"failed {item.id}: {exc}")
            failed += 1
            continue
        store.mark_sent(item.id, result.get("message_id"))
        log.info("human decision", action="post", item_id=item.id,
                 message_id=result.get("message_id"))
        note = f" ({result['note']})" if result.get("note") else ""
        print(f"posted {item.id}{note}")
        sent += 1
    print(f"\n{sent} posted, {failed} failed.")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a human")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one item")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="approve the draft unchanged")
    p_approve.add_argument("id")
    p_approve.add_argument("--note", default="")

    p_edit = sub.add_parser("edit", help="rewrite the draft, then queue it")
    p_edit.add_argument("id")
    p_edit.add_argument("--body-file", required=True)
    p_edit.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="discard the draft, or clear a handled escalation")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", default="")

    p_retry = sub.add_parser("retry", help="re-queue a failed post")
    p_retry.add_argument("id")

    p_notify = sub.add_parser("notify", help="alert the duty manager about a needs_human item")
    p_notify.add_argument("id")

    p_post = sub.add_parser("post", help="post everything approved or edited")
    p_post.add_argument("--limit", type=int, default=20)

    sub.add_parser("stale", help="go-live step: mark everything still un-sent as stale "
                                 "(the shadow-era queue was never sent and is out of date)")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "approve":
            return cmd_approve(store, args)
        if args.command == "edit":
            return cmd_edit(store, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "retry":
            return cmd_retry(store, args)
        if args.command == "notify":
            return cmd_notify(store, settings, args)
        if args.command == "post":
            return cmd_post(store, settings, args)
        if args.command == "stale":
            return cmd_stale(store, args)
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
