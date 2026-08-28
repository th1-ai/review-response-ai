---
name: review-response-ai
description: Run Review-Response AI ("The Reputation Knight") — Watches Google, TripAdvisor, Booking.com, and Vrbo reviews and drafts a personalised, on-brand reply to each that thanks the guest, addresses complaints, and pulls in booking context.. Use when the user asks to run the agent, check what is waiting for review, approve or reject a draft, or asks how the agent is doing. Trigger phrases: "run The Reputation Knight", "/review-response-ai", "check the queue", "what is waiting for me", "approve that draft".
---

# Review-Response AI

Runs Review-Response AI and works its review queue. Everything happens from the
repo root; every command below exists and works.

## Before anything else

Read `README.md` if you have not this session, and `workflows/10-review-response.md`
for the main loop. If the user has never run this agent, start at
`workflows/00-setup.md` instead and walk them through it.

## The loop

**1. Check the agent is healthy.**

```bash
make doctor
```

Any `FAIL` line has a fix hint. Fix it before going further. `WARN` lines are
worth mentioning but do not stop the run. The `pms adapter` and `email adapter`
lines are not relevant to this agent - see `docs/integrations.md`.

**2. Run one pass.**

```bash
make run                        # one pass over new reviews
make run ARGS="--limit 10"      # just the first ten
make run ARGS="--dry-run"       # compute everything, write nothing
```

Drafting is deterministic - template + slot fill on the review's own text, no
model call - so this never pauses waiting on an answer. It sorts every new
review into a drafted reply (`pending_review`) or an escalation
(`needs_human`, 2 stars and below by default).

**3. Show what is waiting.**

```bash
make review
python3 tools/review.py show <id>
```

Summarise it for the user in plain language: which platform, what rating, what
the agent drafted (or why it escalated instead). Do not paste raw JSON at them.

**4. Act on their decision.**

```bash
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file <path>
python3 tools/review.py reject <id> --reason "<why>"
python3 tools/review.py notify <id>      # escalated items only - alert the duty manager
python3 tools/review.py post             # posts everything approved or edited
```

Read the draft back to them before approving. If they want changes, write the
new version to a file and use `edit` - the before/after is stored. `notify` is
blocked outright while `mode: shadow` (see `docs/safety.md`) - say so plainly
rather than looking for a workaround.

**5. Report.**

```bash
make report
```

## Rules

- **Never post in shadow mode**, and never work around a blocked write. The
  error message says what to do.
- **Going live is the hotel's decision.** Only raise it after
  `workflows/90-go-live.md` has been worked through.
- **Confirm before posting anything**, even an approved item, the first few
  times - it goes out under the hotel's name, in public.
- **A 2-star-or-below review is always a person's call**, never yours to
  draft around.
- **Never print or paste a credential.**
- If a run fails, read the whole error, fix the cause, re-run, and note what
  you learned in `workflows/99-troubleshooting.md`.
