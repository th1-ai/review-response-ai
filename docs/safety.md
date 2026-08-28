# Guardrails and safety

This agent talks to your guests and touches your systems. Everything below is
built in, not optional, and this page explains what it does and what is left for
you to decide.

## What Review-Response AI specifically will not do

- **Never posts a reply without an explicit human approval.** Every band -
  5-star `thank`, 3-star `acknowledge`, 1-star `recover` - goes through
  `python3 tools/review.py approve` (or `edit`) before `post` can touch it.
  `reviews.reply()` is a `@guarded_write("publish")` method and `publish` is
  in `review.require_approval_for` by default. This is how the roster's "won't
  auto-publish negative-review replies without approval" is kept for every
  rating, not just negative ones - see `docs/how-it-works.md`, decision 10.
- **Never drafts a reply to a review at 2 stars or below**, while
  `escalate-low` is on (the default). That review goes straight to
  `needs_human` with the reason recorded, and a person handles it - see
  `workflows/80-review.md`.
- **Never quotes a competitor's name back to a guest.** `no-comp-mentions`
  scrubs the quoted line entirely rather than editing around the name -
  see `tools/engine.py:scrub_competitor`.
- **Never invents a detail.** The one line quoted back to a guest is always a
  substring of that guest's own title or body - `tools/engine.py:pick_detail`
  - never generated, never paraphrased.
- **Never touches your PMS.** There is no PMS adapter in this repo at all -
  see `docs/integrations.md`.
- **Never detects or translates a language.** Every draft is English, whatever
  language the review is in - a French, German, or Japanese review still gets
  an English reply that quotes the guest's own foreign-language words back
  verbatim (nothing is invented; see the bullet above). If a real share of
  your reviews are in another language, read `docs/how-it-works.md`, decision
  8, before trusting these drafts as-is - see also README, "Customising".

### Guest-facing text: no em dashes

Every template in `tools/engine.py` uses plain punctuation - periods and
commas, not em dashes - even where the behaviour this agent was built from
used one. This is a house style rule for anything a hotel might paste into
a guest-facing reply, not a functional guardrail, but it is enforced the same
way: `tests/test_review_response_engine.py`'s
`test_build_draft_never_contains_an_em_dash` fails the build if one creeps
back in.

### Escalation, in practice

An escalated review has **no draft and no autonomous next step**. The
"assign to the duty manager" action is `python3 tools/review.py notify <id>`,
and it is blocked outright while `mode: shadow` - shadow blocks every write,
including an internal staff alert, and there is no per-item approval for an
item that was never drafted. While you are in shadow, the review queue itself
(`make review`) is your alert: check it, and call the guest or your duty
manager directly. This is a deliberate consequence of the shared write guard
(`core/review.py`), not a bug - see `workflows/80-review.md` step 4 and
`workflows/99-troubleshooting.md`.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The agent reads, thinks, drafts and queues. It **never** sends a message and **never** writes to your PMS. |
| `live` | Items you approved are really sent. Everything else still waits. |

`mode` lives in `config/hotel.yaml`. It is a global kill switch: flipping it back
to `shadow` stops every outbound action immediately, mid-schedule, with no other
change. `config/agent.yaml` can be stricter than `hotel.yaml`, never looser.

Two more brakes:

- `make run ARGS="--dry-run"` computes everything and writes nothing, even in
  live mode. Use it when you change a prompt.
- `review.require_approval_for` in `config/hotel.yaml` lists the actions that
  need a human even in live mode. The defaults are `send_email`, `send_message`,
  `pms_write`, `payment`, `publish`. Shortening that list is how you hand the
  agent more rope, one action at a time.

Every outbound action in the codebase goes through one function,
`core/review.py:assert_write_allowed`. There is no second path.

## The review queue

Nothing reaches a guest without passing through the queue.

```bash
make review                       # what is waiting
python3 tools/review.py show <id>  # the full draft and how it got there
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file my-version.txt
python3 tools/review.py reject <id> --reason "wrong tone"
python3 tools/review.py post       # posts everything approved or edited
```

A review moves straight from `new` to either `pending_review` (drafted) or
`needs_human` (escalated, 2 stars or below) - there is no intermediate
classification step, since drafting is deterministic (`docs/how-it-works.md`).
Only `tools/review.py` can write `approved`, `edited` or `rejected`; only
`python3 tools/review.py post` can write `sent`. A crash between "about to
post" and "sent" is picked up on the next pass and shown to you as failed
rather than silently retried.

**Your edits teach it.** When you rewrite a draft, the before and after are
stored. Over time that is what makes the drafts sound like your hotel instead of
like a machine.

## What the agent will not do

- Send anything while `mode: shadow`.
- Send an item a human has not approved, when the action needs approval.
- Take a payment, issue a refund, or move money. Payment adapters are read-only
  by design.
- Invent a fact that is not in `knowledge/` or in the data it was given. When it
  is not sure, it queues the item as `needs_human` instead of guessing.
- Argue. Complaints, refund requests, legal or medical topics, and anything that
  reads as distressed go straight to a person.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or `claude-code`,
the prompt goes to Anthropic. That prompt contains the guest message and the
relevant property facts. With `llm.provider: mock` or `interactive`, nothing
leaves the machine at all.

**What is stored, and where.** Everything lives in `data/` inside this folder:
`agent.db` (SQLite), `logs/*.jsonl`, `exports/`. `data/` is gitignored. There is
no cloud service behind this repo and no telemetry.

**Card numbers are redacted on the way in.** Every inbound message passes through
`core/redact.py` before it is stored, logged or put into a prompt. A payment card
number is replaced with `[CARD REDACTED ****1234]`, and labelled CVC and expiry
values in the same message go with it. Detection requires a real card prefix and
a valid Luhn checksum, so booking references and door codes survive. IBANs are
masked the same way. Nothing you can do in config turns this off.

**Retention.** `privacy.retention_days` (default 365) is how long processed items
stay in the database. Deleting `data/agent.db` deletes everything the agent knows.

## GDPR, in practice

If you are in the EU or handle EU guests' data, the short version:

- **You are the controller.** This software runs on your machine, under your
  control, on your data. TH1 does not receive it.
- **Your model provider is a processor.** If you use the `anthropic` or
  `claude-code` provider, Anthropic processes guest data on your behalf. Check
  their data processing terms and record them in your processing register.
- **Purpose and minimisation.** The agent sees the message and the property facts
  it needs. Do not put staff phone numbers, card data or full guest histories in
  `knowledge/`.
- **Right to erasure.** A guest asking to be deleted means removing their rows
  from `data/agent.db` and any exported CSVs. Ask your Claude session:
  *"Delete every item in data/agent.db whose payload mentions this email address,
  and tell me how many rows you removed."*
- **Retention.** Set `privacy.retention_days` to what your own policy says, not
  to the default.

This is a practical summary, not legal advice.

## Telling guests they are talking to AI

The EU AI Act (Article 50) requires that a person is told when they are
interacting with an AI system, unless it is obvious. Whether it applies to you
depends on where you and your guests are, but it is good practice everywhere and
guests react well to it.

For this agent, that means the review reply itself, since it is the one
message a guest actually reads. There is no `knowledge/signature.md` here (see
"Subscription or API" below for why) - add a short line to the end of your
`return_visit_line` or sign-off in `config/agent.yaml`, or ask your Claude
session to add one more line to the templates in `tools/engine.py`, for
example:

> This reply was drafted with AI assistance and reviewed by our team before
> posting.

Some review platforms have their own length limits and tone expectations for
owner responses - check that a disclosure line still reads naturally there
before adding it everywhere.

## Subscription or API: an honest note

This section applies to every other agent in this family, but barely to this
one. **Drafting a reply costs nothing and calls no model at all** - see
`docs/how-it-works.md`, "The central design choice". `llm.provider` in
`config/hotel.yaml` only matters for the one optional, cosmetic feature this
agent has: the morning note (`tools/narrate.py`), which is off by default
(`narrate.enabled: false` in `config/agent.yaml`) and, even switched on, is a
few sentences a day.

If you do turn it on: `interactive` or `claude-code` (your own Claude Code
subscription) cost nothing extra and are more than enough for one short note a
day. `anthropic` (a metered API key) is the right choice only if you have a
reason to want it running unattended on a server with no Claude Code login at
all. `python3 tools/report.py` shows the running total either way, and it will
normally read `$0.0`.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`. Every
   outbound action stops on the next pass.
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order: the
   agent's own drafting/escalation steps and every human approve / edit /
   reject / retry / notify / post / stale decision from `tools/review.py`.
