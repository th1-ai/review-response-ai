# Connecting your systems

Every connector in this repo is one of three things, and the table says which.
We will not tell you an integration exists when it does not.

| Badge | Means |
|---|---|
| **built** | Written against the real API and tested against it. |
| **universal** | Works with any system through a common protocol: CSV, a webhook, a fixture reader. |
| **stub** | Interface only. Calling it raises a clear error with a recipe for adding it. |

Check what is actually working on your machine at any time:

```bash
make doctor
```

This agent uses three systems: **reviews** (what it reads and, once approved,
posts to), **messaging** (the duty-manager alert), and **sheets** (the
optional report export). It does not use a PMS or a mailbox at all - see
"Not used by this agent" below.

## Reviews - `config/agent.yaml: reviews.adapter`

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `mock` | universal | nothing | Reads `fixtures/inbound/*.json`. What `make demo` uses. |
| `csv` | universal | a CSV export | Reads `data/imports/reviews.csv`. **Start here for a real property.** |
| `stub` | stub | nothing | The generic core stub - every method raises. Only useful to see the error. |

**No platform's write API is implemented.** Neither `mock` nor `csv` posts a
reply anywhere. This is the honest state of things, not a corner cut for the
demo:

- **Google Business Profile** has a public Business Profile API, gated behind
  OAuth and a verified, claimed listing. It is the most realistic one to
  build first - see "Implement your own" below.
- **Booking.com and TripAdvisor** do not offer a general-purpose public API
  for posting review replies. In practice, properties manage these through
  each platform's own extranet, or through a paid review-management /
  reputation aggregator that has a partner integration. That is exactly what
  `csv` is for: export from whatever aggregator you already use, and use its
  own posting flow (or paste in what this agent drafted).
- **Vrbo** (the roster's fourth platform) sits behind Expedia Partner
  Central's partner program - API access needs a partner agreement, not just
  a signup.

**`mock`.** One review per file in `fixtures/inbound/*.json`. Posting a reply
appends to `data/exports/review_replies.jsonl` - nothing leaves the machine.

**`csv`.** Export your reviews to `data/imports/reviews.csv` with columns
`id, source, rating, guest_name, review_date, title, body, category,
responded, response_text` (extra columns are kept; headers are matched
loosely - `Review Date`, `review_date` and `reviewDate` all work). Posting a
reply appends to `data/exports/review_replies_to_apply.csv` with everything
you need to paste it into the platform by hand, and never calls an API. That
is a feature, not a limitation: it is how you check the agent's drafts before
you ever wire up a real posting adapter.

**Switching `reviews.adapter` between `mock` and `csv`?** Run `make clean`
first. Both adapters write into the same `data/agent.db` queue, so items
drafted from the sample fixtures do not disappear when you switch to `csv` -
they sit in `make review` alongside your real reviews. `make clean` only
clears `data/` (database, logs, exports); `config/` and `.env` are untouched.

## Messaging - `systems.messaging.adapter` (used for the duty-manager alert)

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `mock` | universal | nothing | `python3 tools/review.py notify` logs instead of sending. |
| `unipile` | built | your own UniPile account | WhatsApp on your own number. |
| `webhook` | universal | any URL | POST to Zapier, Make, n8n, or your own endpoint. |

Set `systems.messaging` in `config/hotel.yaml` the same way any other agent
in this family does. See the shared `core/adapters/messaging_unipile.py` and
`messaging_webhook.py` for exact env vars. Note that `notify` is blocked
outright while `mode: shadow` - see `docs/safety.md`.

## Sheets - `systems.sheets.adapter` (used by `python3 tools/report.py --export`)

| Adapter | Status | Needs | Notes |
|---|---|---|---|
| `csv` | universal | nothing | Writes `data/exports/review_response_report.csv`. |
| `google` | built | service account JSON | A live shared spreadsheet. |

## Not used by this agent

**PMS.** The roster says drafts "pull in booking context"; the drafting logic
this repo was built from never actually reads a reservation - see
`docs/how-it-works.md`, decision 2. There is no PMS adapter wired up here at
all. `make doctor` still prints a `pms adapter` line (every repo in this
family shares the same generic health check) - it is not relevant to this
agent and safe to ignore.

**Email.** Replies go out through the reviews adapter's `reply()`, not
through a mailbox. `make doctor`'s `email adapter` line is likewise not
relevant here.

## Implement your own

<a id="implement-your-own"></a>

The interface is small on purpose. Open `claude` in this folder and paste:

> Read `docs/integrations.md#implement-your-own`, `tools/reviews_adapters.py`
> and `core/adapters/base.py`. I need a real posting adapter for
> **<your platform>**. Its API docs are at **<url>** and I have credentials
> in `.env` as `<VAR names>`. Copy `tools/reviews_adapters.py`'s `ReviewsCsv`
> class as the shape, implement `ping`, `capabilities`, `list_reviews` and
> `reply` (keep the `@guarded_write("publish")` decorator), register it in
> `get_reviews()`, and stop before wiring it into `config/agent.yaml` by
> default so I can check the reads with `make doctor` first.

### The steps

**1. Copy `tools/reviews_adapters.py`'s `ReviewsCsv`** as the shape - it is
short and heavily commented, and shows the pattern this whole family uses.

**2. Implement `ping()` and `capabilities()` first.** `make doctor` reads
both; getting them right first gives you a feedback loop for the rest.

**3. Implement `list_reviews(since)`.** Return plain dicts with `id, source,
rating, guest_name, review_date, title, body, category, responded,
response_text` - the same shape `tools/engine.py` already expects, so nothing
downstream needs to change. Put anything you cannot map into `extra` rather
than dropping it.

**4. Implement `reply(review_id, text)`, with the guard:**

```python
from core.adapters.base import guarded_write

@guarded_write("publish")
def reply(self, review_id: str, text: str) -> dict:
    ...
```

The decorator is not optional. Without it your adapter can post while the
agent is in shadow mode, which defeats the entire safety model.

**5. Register it** in `get_reviews()` in `tools/reviews_adapters.py`:

```python
if name == "yourplatform":
    return YourPlatformReviews(settings)
```

Then set `reviews.adapter: yourplatform` in `config/agent.yaml` and run
`make doctor`.

### Rules that matter

- **`ping()` never raises.** Return `HealthCheck(ok=False, ...)` with a hint.
- **The write is decorated.** No exceptions.
- **Respect each platform's rate limits and reply-length caps** - build a
  `RateLimiter` per `core/adapters/_http.py` if you are calling a real API.
- **Never log a credential.** `core/log.py` masks anything whose key looks
  like a secret, but do not rely on it.
- **Write a test.** Copy `tests/test_review_response_loop.py`'s
  `test_csv_adapter_reads_loosely_matched_headers` - feed your parser a
  fixture, check the dict that comes out.

### Promoting this into `core/`

This repo keeps its reviews adapters in `tools/` rather than `core/adapters/`
because `core/` is vendored byte-for-byte into all 28 repos in this family
from a single factory source - see this repo's build report for the "Core
request" to add a `reviews` entry to `core/adapters/__init__.py`'s registry
the way `pms`/`email`/`messaging`/`sheets` already work, once a second agent
in the family needs the same thing.
