# Workflow: the review-response loop

Objective: run one pass over the review inbox and see what Review-Response AI
did with it. Nothing here posts a reply - see `workflows/80-review.md` for
that.

## Inputs

- A configured `reviews.adapter` in `config/agent.yaml` (`mock` by default -
  see `workflows/00-setup.md` step 4 to connect a real source).
- The five rules in `config/agent.yaml`: `escalate-low`, `brand-voice`,
  `personalise`, `no-comp-mentions`, `same-day`. The defaults (all on) match
  the behaviour this agent was built from.

## Steps

1. **Run one pass.**
   ```bash
   make run
   make run ARGS="--limit 10"       # just the first ten reviews
   make run ARGS="--dry-run"        # compute everything, write nothing
   ```
   Every unanswered review not already seen by this agent goes through
   `tools/engine.py`, deterministically - no model call, no waiting on a
   provider. See `docs/how-it-works.md` for the full step-by-step.

2. **See what happened.**
   ```bash
   make review
   ```
   A review at 3 stars or above (or any rating, if `escalate-low` is off)
   is `pending_review` with a drafted reply. A review at 2 stars or below
   (when `escalate-low` is on) is `needs_human` with no draft at all - it
   goes to a person, not into the drafting logic.

3. **Work the queue.** `workflows/80-review.md` covers approve / edit /
   reject / notify / post in full.

4. **Try a rule toggle.** Flip one in `config/agent.yaml`, run `make run`
   again, and read the difference:
   - `escalate-low: false` - the same low-star review that was escalated
     last time is now drafted, in the `recover` band.
   - `personalise: false` - every new draft opens `Dear guest,` with no
     quoted line.
   - `no-comp-mentions: false` - a quoted line naming a competitor is no
     longer dropped.
   - `brand-voice: false` - drafts are unsigned.
   Each of these changes real drafted text, not just a log line - that is the
   point of the deterministic design (`docs/how-it-works.md`).

5. **Keep it running.**
   ```bash
   make watch                       # loop on the configured interval
   ```
   Or schedule it - `make schedule` and `scheduler/` have cron, launchd and
   systemd examples. Read `docs/how-it-works.md`, "the 24-hour promise",
   before picking a cadence: how often you run this loop is what actually
   delivers same-day coverage, not the `same-day` rule itself.

## Edge cases

- **No new reviews.** `make run` prints `0 items processed, 0 drafted, 0 sent`
  and exits 0.
- **A review with no title and a body too short to quote.** `pick_detail()`
  returns nothing; the draft simply has no quoted line, same as
  `personalise: false`.
- **A review with no `category`.** `amenity_for()` falls back to
  `amenities.default` ("the team" unless you changed it).
- **A re-run sees the same review again.** `(source, external_id)` is unique
  on `items` - see `core.store.Store.upsert_item`. Nothing is redrafted.
- **A review the platform already shows as answered.** Dropped before it ever
  reaches the store - see `fixtures/inbound/review-08-already-answered.json`
  for an example.
