# The business case

**Why.** Response rate and speed directly move ranking and conversion; nobody
has time to reply to them all.

**Output.** 100% review-response coverage within 24h; responded-to listings
convert higher.

**ROI.** +11% Listing conversion (revenue).

(Quoted verbatim from the roster - see `README.md` for the full promise.)

## The problem this solves

Every major platform - Google, Booking.com, TripAdvisor, and increasingly
Vrbo - treats response rate and response speed as a ranking signal, and
guests read the responses, not just the ratings. A small property gets a
handful of reviews a week across four platforms with four different
dashboards; writing four thoughtful replies a week, every week, without ever
missing one, is the kind of unglamorous consistency that is easy to promise
and hard to keep up by hand. That gap - a response rate that quietly slips
from 100% to 60% over a busy season - is what this agent closes.

## What to measure

`python3 tools/report.py` reads straight from `core.store` and shows:

- **Coverage**: reviews posted versus everything the agent has ever seen -
  the roster's "100% review-response coverage" as a number you can check.
- **Escalation rate**: the share that went to `needs_human` (2 stars and
  below, by default) instead of being drafted - this is a property of your
  review mix and your `escalate-low` setting, not something to try to drive
  to zero.
- **Edit rate**: the share of drafted replies a person rewrote before
  posting. A falling edit rate over time is the signal that the templates and
  rule settings match your voice, and that going live is worth considering
  (`workflows/90-go-live.md`).
- **Competitor scrubs**: how often `no-comp-mentions` actually caught
  something, which is otherwise invisible.
- **Average time to post**: from first seen to posted - the practical measure
  of "within 24h", alongside the scheduling cadence you picked
  (`docs/how-it-works.md`, "the 24-hour promise").
- **Spend**: effectively zero. Drafting is deterministic; see
  `docs/safety.md`, "Subscription or API".

`python3 tools/report.py --export` writes the same numbers to
`systems.sheets.adapter` so you can hand a GM a file instead of a terminal.

## Honest caveats

- **"Pulls in booking context" is not built.** A draft uses only the review's
  own text - no stay dates, no room type, no folio. See
  `docs/how-it-works.md`, decision 2, and `docs/integrations.md`.
- **No platform posts automatically.** `mock` and `csv` both log a reply for
  you to check or paste in by hand rather than calling a real API - see
  `docs/integrations.md`. The coverage number above measures drafting speed
  and human review speed, not an unattended pipeline all the way to the
  platform.
- **The "within 24h" promise is a scheduling choice, not a built-in clock.**
  Nothing pages anyone about an ageing review; how often you run `make run`
  is what actually delivers it.
- **Three templates, five toggles, no language detection.** At real volume,
  or for a property with many non-English-speaking guests, this reads as
  repetitive or wrong-language faster than a hand-written reply would. See
  `docs/how-it-works.md`, decisions 4 and 8, before promising bespoke replies
  at scale.
