# Workflow: troubleshooting

Read the whole error before doing anything - every tool here is written to
say what broke and what to do about it. If you fix something not covered
below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'Hotel Aurora'.** Expected on a fresh
  clone. Edit `config/hotel.yaml`.
- **`reviews adapter`: FAIL.** `reviews.adapter` in `config/agent.yaml` is set
  to something other than `mock`/`csv`/`stub`, or `csv` mode has no
  `data/imports/reviews.csv` yet. See `docs/integrations.md`.
- **`sign-off`: WARN, brand-voice is on but signoff.name is blank.** Set
  `signoff.name` and `signoff.role` in `config/agent.yaml`.
- **`pms adapter` or `email adapter` show something other than `ok`.** This
  agent does not use either - see `docs/integrations.md`. Safe to ignore.

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` forces `mode=shadow` and reads `fixtures/inbound/*.json` -
  if you deleted or renamed those files, restore them from git.
- Read the traceback if there is one; `tools/demo.py` does not swallow errors
  on purpose, so a fixture problem shows up immediately.

## A draft looks wrong

- **No quoted line at all, on every review.** Check `personalise` in
  `config/agent.yaml` - it may be off. If it is on, the review's title and
  body may both be too short to quote (`pick_detail()` needs at least 6
  characters); that is working as intended, not a bug.
- **A quoted line is missing that you expected to see.** Check whether it
  matched something in `competitors` - `no-comp-mentions` drops it silently
  by design. `make run` and `python3 tools/review.py show <id>` both surface
  the `scrubbed` flag on the draft.
- **The wrong team gets credited ("the team" instead of something specific).**
  The review's `category` either was not set by your review source, or is not
  a key in `config/agent.yaml`'s `amenities`. Add it, or fix the source.
- **A 2-star review was drafted instead of escalated (or the reverse).**
  Check `escalate-low` in `config/agent.yaml` - it is the only thing that
  controls this, at exactly 2.0 stars and below.

## `python3 tools/review.py notify <id>` says "blocked"

Expected while `mode: shadow` - see `workflows/80-review.md` step 4. Shadow
blocks every write, including a duty-manager alert, and an escalated item has
no draft to approve past that. Handle the review yourself for now, or go
live (`workflows/90-go-live.md`).

## An item is stuck at `sending`

A process died between claiming an item and finishing the post.
`tools/run.py` calls `core.store.Store.reap_stuck_sending()` on every pass,
which moves anything stuck for more than 30 minutes to `failed` so you see it
in the queue instead of it vanishing. Use
`python3 tools/review.py retry <id>` once the cause is fixed.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py` directly
from the repo root.

## `make review` shows sample fixtures mixed in with my real reviews

You ran `make run` on the `mock` adapter (the default, or while trying
`tools/narrate.py`) before switching `reviews.adapter` to `csv` in
`config/agent.yaml`. Both adapters share `data/agent.db`, so the sample items
do not disappear when you switch - they sit in the same queue. Run
`make clean` (clears the database, logs and exports only; `config/` and
`.env` are untouched), then run the real adapter again.

## I deleted `data/agent.db` and now old reviews are drafted again

That is expected, not a bug - but worth knowing before you do it on a real
property. `data/agent.db` is also the agent's only memory of what it has
already seen and posted. Deleting it (or `make clean`) does not just clear
runtime state; it means the next `make run` treats every review as new
again, including ones you already replied to, and redrafts them from
scratch. If you only meant to clear a mixed mock/csv queue (see above),
`make clean` is still the right move - just expect a full re-draft on the
next run, and check `make review` before posting anything twice.

## Still stuck

`data/logs/*.jsonl` has every decision, in order, with a run id: the agent's
own six-step narrative from `docs/how-it-works.md` (`make run` / `make demo`),
and every human decision - approve, edit, reject, retry, notify, post, stale
- logged from `tools/review.py` as it happens.
`python3 tools/review.py show <id>` has the full event trail for one item. If
neither explains it, that is a real bug - describe exactly what you ran and
what you expected, and ask.
