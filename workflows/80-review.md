# Workflow: working the review queue

Objective: turn a drafted reply into a decision - approve, edit, or reject -
and, once approved, actually post it. Turn an escalated review into a handled
one.

Nothing reaches a guest without going through this. `mode: shadow` blocks
`publish` for everything except an item you have approved or edited; see
`docs/safety.md` for the full guard.

## Steps

1. **See what is waiting.**
   ```bash
   make review
   ```
   Each line shows the item id, its status (`pending_review` or
   `needs_human`), the band or `escalated`, the platform, the rating and the
   title.

2. **Read one in full.**
   ```bash
   python3 tools/review.py show <id>
   ```
   This prints the original review, the drafted reply (if any), and the full
   event history for that item. Read the draft to the hotel in plain language
   before approving - do not just paste the JSON at them.

3. **Decide, for a drafted item.**
   ```bash
   python3 tools/review.py approve <id>
   python3 tools/review.py edit <id> --body-file my-version.txt
   python3 tools/review.py reject <id> --reason "wrong tone"
   ```
   `edit` records the before/after pair as a `learnings` row. This agent has
   no weekly pass that reads it (see `docs/how-it-works.md`, decision 9) -
   the row is there if you build one later.

4. **Decide, for an escalated item (`needs_human`, no draft).**
   ```bash
   python3 tools/review.py notify <id>
   ```
   Alerts your duty manager via `systems.messaging.adapter`. **This is
   blocked while `mode: shadow`** - shadow blocks every write, including an
   internal alert, and an escalated item has no draft to "approve" its way
   past that. While you are in shadow, treat `make review`'s output as your
   own alert: read it, call the guest or the duty manager yourself. Once it
   is handled, either way, clear it from the queue:
   ```bash
   python3 tools/review.py reject <id> --reason "handled by duty manager"
   ```

5. **Post what was approved.**
   ```bash
   python3 tools/review.py post
   ```
   This claims everything `approved`/`edited`, calls the reviews adapter's
   `reply()`, and records the result. `mode: shadow` blocks this too, even
   for an item you just approved - `mode: shadow` is a true kill switch, not
   a per-item exception (see `core/review.py`). Approving in shadow only
   records the decision; nothing actually posts until you switch to
   `mode: live` (`workflows/90-go-live.md`). With the `mock` or `csv`
   adapter, "posting" logs the reply for you to check or paste in by hand -
   see `docs/integrations.md`.

6. **A failed post.** `post` marks the item `failed` with the error attached.
   ```bash
   python3 tools/review.py retry <id>
   ```
   re-queues it for another attempt.

## Rules

- Only `tools/review.py` writes `approved` / `edited` / `rejected`.
- A 2-star-or-below review, when `escalate-low` is on, is never drafted at
  all - it is `needs_human` from the moment `make run` sees it. Never
  approve your way around that; there is nothing to approve.
- Every posted reply - 5 stars or 2 - needed an explicit `approve` or `edit`
  first. There is no autonomous posting path in this repo, for any rating.
- Confirm with the hotel before posting anything, even an approved item, the
  first few times. `workflows/90-go-live.md` covers when to stop doing that.
