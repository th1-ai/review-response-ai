"""tools/reviews_adapters.py - the review-platform connectors.

``core/adapters/base.py`` already defines the ``Reviews`` interface
(``list_reviews`` / ``reply``) as a stub family, alongside POS, Accounting and
the rest. No platform is wired into ``core``'s registry the way PMS or Email
are, because there is no real implementation to register: Google Business
Profile, Booking.com, TripAdvisor and Vrbo each have their own auth model and
none exposes the same shape (see docs/integrations.md).

This module ships the two adapters that actually work with zero credentials
or a plain CSV, plus the factory that reads ``config/agent.yaml: reviews.adapter``
and hands back the right one:

``mock``   fixtures/inbound/*.json - what ``make demo`` and the tests use.
``csv``    data/imports/reviews.csv - a CSV export from your review tool.
``stub``   the generic core stub - every method raises with a recipe.

Both real adapters log a posted reply instead of calling a platform API - see
each class's docstring for exactly what "posting" means for that adapter.
This lives in ``tools/`` rather than ``core/`` because ``core/`` is vendored
byte-for-byte into every repo in this family (see docs/how-it-works.md and
the factory's ARCHITECTURE.md section 2); a "Core request" to promote this
into ``core/adapters/__init__.py``'s registry is noted in this repo's build
report.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.adapters.base import AdapterNotConfigured, HealthCheck, Reviews, guarded_write
from core.config import Settings, repo_root, sub_data_dir

KNOWN_FIELDS = {"id", "source", "rating", "guest_name", "review_date", "title", "body",
               "category", "responded", "response_text"}


def _key(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _row_get(row: dict, *names: str, default: Any = "") -> Any:
    normalised = {_key(k): v for k, v in row.items() if k}
    for name in names:
        value = normalised.get(_key(name))
        if value not in (None, ""):
            return value
    return default


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "responded")


def _normalise(raw: dict) -> dict:
    """Coerce a loosely-typed source dict into the shape the engine expects."""
    review = {k: raw.get(k) for k in KNOWN_FIELDS if k in raw}
    review.setdefault("id", raw.get("id") or raw.get("external_id") or "")
    review["rating"] = float(raw.get("rating") or 0)
    review["responded"] = bool(raw.get("responded", False))
    review["extra"] = {k: v for k, v in raw.items() if k not in KNOWN_FIELDS}
    return review


class ReviewsMock(Reviews):
    """Fixture-backed reviews. No credentials, no network.

    Reads one review per file from ``fixtures/inbound/*.json`` - the same
    per-file convention the other mock adapters in this family use, so a new
    sample review is one new file, not an edit to a shared array.

    Posting a reply appends to ``data/exports/review_replies.jsonl`` instead
    of calling any platform. That is what ``make demo`` shows you at the end.
    """

    status, name = "universal", "reviews_mock"

    def __init__(self, settings: Settings, config: Any = None) -> None:
        super().__init__(settings, config)
        self.dir = Path(self.opt("fixtures_dir") or (repo_root() / "fixtures" / "inbound"))
        self.outbox = sub_data_dir("exports") / "review_replies.jsonl"

    def ping(self) -> HealthCheck:
        if not self.dir.exists():
            return HealthCheck(False, self.name, f"no fixtures at {self.dir}",
                               "Add fixtures/inbound/*.json, or switch reviews.adapter "
                               "in config/agent.yaml to csv.")
        n = len(self._files())
        return HealthCheck(True, self.name, f"{n} sample review(s) in {self.dir}")

    def capabilities(self) -> set[str]:
        return {"list_reviews", "reply"}

    def _files(self) -> list[Path]:
        return sorted(p for p in self.dir.glob("*.json") if p.is_file())

    def list_reviews(self, since: str | None = None) -> list[dict]:
        out = []
        for path in self._files():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            review = _normalise(raw)
            if since and str(review.get("review_date") or "") < since:
                continue
            out.append(review)
        return out

    @guarded_write("publish")
    def reply(self, review_id: str, text: str) -> dict:
        """Log the reply. Nothing leaves the machine - see the class docstring."""
        record = {"posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "review_id": review_id, "text": text}
        with self.outbox.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "message_id": f"mock-{abs(hash(review_id)) % 10**10}",
                "logged_to": str(self.outbox)}


class ReviewsCsv(Reviews):
    """Reads a CSV export from your review-management tool or aggregator.

    Expected file: ``data/imports/reviews.csv`` with columns ``id, source,
    rating, guest_name, review_date, title, body, category, responded,
    response_text`` (extra columns are kept in ``extra``; headers are matched
    loosely, so ``reviewDate``, ``review_date`` and ``Review Date`` all work).

    **Posting never calls a platform.** No review platform's write API is
    implemented here (see docs/integrations.md). A reply is appended to
    ``data/exports/review_replies_to_apply.csv`` with everything a person
    needs to paste it into the platform by hand. That is the honest behaviour
    for a system this repo cannot call - and it doubles as a way to check the
    agent's drafts before you ever wire up a real posting adapter.
    """

    status, name = "universal", "reviews_csv"

    def __init__(self, settings: Settings, config: Any = None) -> None:
        super().__init__(settings, config)
        configured = self.opt("imports_dir")
        self.dir = Path(configured) if configured else sub_data_dir("imports")
        self.to_apply = sub_data_dir("exports") / "review_replies_to_apply.csv"

    def ping(self) -> HealthCheck:
        path = self.dir / "reviews.csv"
        if not path.exists():
            return HealthCheck(
                False, self.name, f"no {path}",
                "Export your reviews to CSV and save it as data/imports/reviews.csv "
                "(see docs/integrations.md).")
        return HealthCheck(True, self.name, f"{len(self._read())} review(s) in {path}")

    def capabilities(self) -> set[str]:
        return {"list_reviews", "reply"} if (self.dir / "reviews.csv").exists() else set()

    def _read(self) -> list[dict]:
        path = self.dir / "reviews.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return [dict(row) for row in csv.DictReader(fh)]

    def list_reviews(self, since: str | None = None) -> list[dict]:
        out = []
        for row in self._read():
            review = {
                "id": _row_get(row, "id", "review_id", "external_id"),
                "source": _row_get(row, "source", "platform"),
                "rating": float(_row_get(row, "rating", "score", default=0) or 0),
                "guest_name": _row_get(row, "guest_name", "guest", "author"),
                "review_date": _row_get(row, "review_date", "date"),
                "title": _row_get(row, "title", "headline"),
                "body": _row_get(row, "body", "text", "comment"),
                "category": _row_get(row, "category", "theme") or None,
                "responded": _bool(_row_get(row, "responded", "answered", default="false")),
                "response_text": _row_get(row, "response_text", "reply"),
                "extra": {},
            }
            if since and str(review["review_date"]) < since:
                continue
            out.append(review)
        return out

    @guarded_write("publish")
    def reply(self, review_id: str, text: str) -> dict:
        is_new = not self.to_apply.exists()
        with self.to_apply.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(["logged_at", "review_id", "text"])
            writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            review_id, text])
        return {"ok": True, "message_id": None, "logged_to": str(self.to_apply),
                "note": "CSV mode cannot post to a live platform - paste this reply in "
                       "by hand, then mark the row responded in your export."}


def get_reviews(settings: Settings) -> Reviews:
    """The reviews connector named in ``config/agent.yaml: reviews.adapter``."""
    name = str(settings.agent_get("reviews.adapter", "mock") or "mock").lower()
    if name == "mock":
        return ReviewsMock(settings)
    if name == "csv":
        return ReviewsCsv(settings)
    if name == "stub":
        from core.adapters import get_stub
        return get_stub("reviews", settings)
    raise AdapterNotConfigured(
        f"reviews.adapter is '{name}', which does not exist.\n"
        f"  Available: mock, csv, stub.\n"
        f"  Edit config/agent.yaml, or write your own - see "
        f"docs/integrations.md#implement-your-own.")
