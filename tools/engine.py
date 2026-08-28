"""tools/engine.py - Review-Response AI's drafting logic. Deterministic, no LLM.

Every function here is a pure function over plain dicts: no I/O, no model
call, no randomness. Given the same review and the same rules, you always get
the same draft. That is the whole point (see docs/how-it-works.md, "The
central design choice") - it is what makes a rule toggle provable, and it is
why every rule below is a unit test in tests/test_review_response_engine.py
rather than something you have to run the agent to see.

The shape mirrors the behavioural spec step by step:

    read_inbox()        -> step 1, counts and the oldest waiting review
    pick_detail()        -> the one line quoted back to the guest
    scrub_competitor()   -> drop that line if it names a rival
    band()               -> thank / acknowledge / recover, from the rating
    amenity_for()         -> which team the feedback reaches
    build_draft()         -> template + slots -> the reply text
    process_reviews()    -> the whole pass: escalate or draft every review

tools/run.py and tools/demo.py both call process_reviews() so the real loop
and the zero-credential walkthrough exercise exactly the same code.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

# Verbatim reason recorded on every escalated review. No em dash - see
# docs/safety.md "Guest-facing text" for why this repo avoids them everywhere.
ESCALATION_REASON = "2 stars and below is a human conversation - rule: escalate-low"

DEFAULT_AMENITY = "the team"
DEFAULT_RETURN_VISIT_LINE = "We would love to welcome you back on your next visit."
DEFAULT_UNSIGNED_SIGNOFF = "The {hotel_name} team"

_QUOTE_STRIP = re.compile(r'^["\'“”\s]+|["\'“”.,;:!\s]+$')


def format_stars(rating: float) -> str:
    """``4`` -> ``"4★"``; ``4.5`` -> ``"4.5★"``. One decimal only when needed."""
    rating = float(rating)
    if rating == int(rating):
        return f"{int(rating)}★"
    return f"{rating:.1f}★"


def band(rating: float) -> str:
    """thank (>=4) / acknowledge (>=3) / recover (else). The only content branch."""
    rating = float(rating)
    if rating >= 4:
        return "thank"
    if rating >= 3:
        return "acknowledge"
    return "recover"


def amenity_for(category: str | None, amenities: dict[str, str] | None = None) -> str:
    """Which team a category's feedback reaches. Unknown/missing -> the default."""
    amenities = amenities or {}
    default = amenities.get("default", DEFAULT_AMENITY)
    if not category:
        return default
    return amenities.get(str(category).lower(), default)


def first_name(guest_name: str) -> str:
    """First token of a guest's name, stripped to letters/marks/apostrophe/hyphen.

    Falls back to the trimmed full name, then to ``"there"`` for an empty or
    unreadable name - never leaves a reply addressed to nobody.
    """
    name = (guest_name or "").strip()
    if not name:
        return "there"
    tokens = name.split()

    def _clean(token: str) -> str:
        return "".join(ch for ch in token
                       if ch in ("'", "-") or unicodedata.category(ch)[0] in ("L", "M"))

    first = _clean(tokens[0])
    # "Familie Wagner", "Family Smith", "Famille Dupont": a household, not a person.
    if first.lower() in FAMILY_MARKERS and len(tokens) > 1:
        surname = _clean(tokens[-1])
        return f"{surname} family" if surname else "there"
    # "Herr Wagner", "Mrs Smith", "Dr Rossi": keep the title with the surname.
    if first.lower().rstrip(".") in TITLE_MARKERS and len(tokens) > 1:
        surname = _clean(tokens[-1])
        return f"{first} {surname}" if surname else "there"
    return first or name or "there"


#: Leading words that mean "a family / group booking", in the languages a
#: European hotel sees most. Lower-case, no punctuation.
FAMILY_MARKERS = frozenset({"familie", "family", "famille", "familia", "famiglia", "fam", "the"})
#: Honorifics that precede a surname rather than being a first name.
TITLE_MARKERS = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "herr", "frau", "hr",
                           "fr", "sig", "sigra", "sr", "sra", "srta", "m", "mme", "mlle",
                           "monsieur", "madame", "mademoiselle", "señor", "señora", "senhor",
                           "senhora", "dhr", "mevr"})


def pick_detail(title: str | None, body: str | None) -> str | None:
    """The one line quoted back to the guest.

    The title, if it is at least 6 characters after trimming quotes and
    surrounding punctuation; otherwise the body's opening, cut at 60
    characters on a word boundary (never mid-word); otherwise nothing at all.
    """
    candidate = _QUOTE_STRIP.sub("", (title or "").strip())
    if len(candidate) >= 6:
        return candidate
    text = (body or "").strip()
    if not text:
        return None
    if len(text) <= 60:
        return text if len(text) >= 6 else None
    cut = text[:60]
    space = cut.rfind(" ")
    if space > 20:
        cut = cut[:space]
    cut = _QUOTE_STRIP.sub("", cut.strip())
    return cut if len(cut) >= 6 else None


def scrub_competitor(detail: str | None, competitors: list[str],
                     enabled: bool = True) -> tuple[str | None, bool]:
    """Drop ``detail`` if it names a competitor and the rule is on.

    Returns ``(detail_or_none, scrubbed)``. Matching is a case-insensitive
    substring check against the quoted line only - the rest of the reply is
    never touched, and the reply still goes out, just without that line.
    """
    if not detail or not enabled or not competitors:
        return detail, False
    lowered = detail.lower()
    for name in competitors:
        if name and name.lower() in lowered:
            return None, True
    return detail, False


@dataclass
class Draft:
    """The result of :func:`build_draft` - everything a review needs recorded."""

    body: str
    band: str
    detail: str | None
    scrubbed: bool
    amenity: str
    signed: bool

    def as_dict(self) -> dict:
        return {"body": self.body, "band": self.band, "detail": self.detail,
                "scrubbed": self.scrubbed, "amenity": self.amenity, "signed": self.signed}


_LINES = {
    "thank": [
        "Thank you for the {stars} on {source}. This is the kind of review "
        "that brings the next guest through the door.",
        'Your line about "{detail}" made our morning meeting.',
        "I have passed it straight to {amenity}, who will be glad to hear it.",
        "{return_visit_line}",
    ],
    "acknowledge": [
        "Thank you for the honest write-up, and I am sorry we finished at "
        "{stars} rather than the stay you booked.",
        'You were right to raise "{detail}".',
        "That is not the standard we hold {amenity} to, and it is being "
        "worked on this week.",
        "If you give us another go, I would like to look after the booking "
        "myself.",
    ],
    "recover": [
        "I am sorry. {stars} is not the stay we intend for anyone, and I "
        "would far rather hear it straight than not at all.",
        'Reading "{detail}", I understand why you left disappointed.',
        "This sits with {amenity}, and I have raised it with the head of "
        "department today.",
        "I would like to put it right with you directly. Reply here and I "
        "will pick it up personally.",
    ],
}
_DETAIL_LINE_INDEX = 1  # the quoted-line sentence, dropped whole when there is none


def build_draft(review: dict, rules: dict, *, amenities: dict | None = None,
                signoff: dict | None = None, competitors: list[str] | None = None,
                return_visit_line: str | None = None, hotel_name: str = "Your Hotel") -> Draft:
    """Template + slot fill. The only place reply text is assembled.

    ``review`` needs ``rating``, ``source``, ``title``, ``body``, ``category``
    and ``guest_name``. ``rules`` is the five-key dict from
    ``config/agent.yaml`` (a missing key defaults to on, matching "a row is
    absent" in the original product).
    """
    rules = rules or {}
    signoff = signoff or {}
    rating = float(review.get("rating") or 0)
    reply_band = band(rating)
    stars = format_stars(rating)
    source = review.get("source") or "the platform"
    amenity = amenity_for(review.get("category"), amenities)

    personalise = rules.get("personalise", True)
    detail = pick_detail(review.get("title"), review.get("body")) if personalise else None
    detail, scrubbed = scrub_competitor(detail, competitors or [],
                                        enabled=rules.get("no-comp-mentions", True))

    greeting = f"Dear {first_name(review.get('guest_name', ''))}," if personalise \
        else "Dear guest,"

    lines = list(_LINES[reply_band])
    if detail is None:
        lines.pop(_DETAIL_LINE_INDEX)
    filled = [
        line.format(stars=stars, source=source, detail=detail or "", amenity=amenity,
                   return_visit_line=return_visit_line or DEFAULT_RETURN_VISIT_LINE)
        for line in lines
    ]

    signed = rules.get("brand-voice", True)
    if signed:
        name = signoff.get("name", "")
        role = signoff.get("role", "Guest Relations")
        sign = f"{name}, {role}" if name else role
    else:
        sign = (signoff.get("unsigned") or DEFAULT_UNSIGNED_SIGNOFF).format(hotel_name=hotel_name)

    body_text = "\n\n".join([greeting, " ".join(filled), sign])
    return Draft(body=body_text, band=reply_band, detail=detail, scrubbed=scrubbed,
                amenity=amenity, signed=signed)


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def read_inbox(reviews: list[dict], today_iso: str) -> dict:
    """Step 1: counts per platform and how long the oldest review has waited."""
    if not reviews:
        return {"count": 0, "by_source": {}, "avg_rating": None, "oldest_days": 0,
                "headline": "Nothing unanswered - every listing is caught up."}
    by_source: dict[str, int] = {}
    for r in reviews:
        by_source[r.get("source", "unknown")] = by_source.get(r.get("source", "unknown"), 0) + 1
    avg = round(sum(float(r.get("rating") or 0) for r in reviews) / len(reviews), 1)
    today = date.fromisoformat(today_iso)
    oldest = 0
    for r in reviews:
        raw = str(r.get("review_date") or "")[:10]
        try:
            days = (today - date.fromisoformat(raw)).days
        except ValueError:
            continue
        oldest = max(oldest, days)
    ordered = sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)
    platform_line = ", ".join(f"{n} on {s}" for s, n in ordered)
    return {"count": len(reviews), "by_source": by_source, "avg_rating": avg,
            "oldest_days": oldest,
            "headline": f"{len(reviews)} unanswered ({platform_line}), "
                       f"average {avg}★, oldest waiting {oldest} day(s)."}


@dataclass
class RunResult:
    """Everything one pass produced: what to draft, what to escalate, why."""

    drafts: list[dict] = field(default_factory=list)      # {review, draft}
    escalations: list[dict] = field(default_factory=list)  # {review, reason}
    steps: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def process_reviews(reviews: list[dict], rules: dict, today_iso: str, *,
                    amenities: dict | None = None, signoff: dict | None = None,
                    competitors: list[str] | None = None,
                    return_visit_line: str | None = None,
                    hotel_name: str = "Your Hotel") -> RunResult:
    """The whole pass: escalate or draft every unanswered review in ``reviews``.

    Pure function - no store, no adapter. tools/run.py and tools/demo.py both
    call this, then write the results to core.store.
    """
    rules = rules or {}
    inbox = read_inbox(reviews, today_iso)
    steps = [f"1. Read the inbox: {inbox['headline']}"]

    rule_bits = []
    for key, on_text, off_text in (
        ("escalate-low", "2 stars and below goes to a human", "2 stars and below is drafted like any other review"),
        ("brand-voice", "replies are signed by a named person", "replies go out unsigned from the house account"),
        ("personalise", "replies quote the guest's own words", "replies are generic, no quotes, no name"),
        ("no-comp-mentions", "competitor names are never quoted back", "a competitor name may appear in a quoted line"),
        ("same-day", "drafts are ready to post today", "drafts wait for the next scheduled batch"),
    ):
        rule_bits.append(on_text if rules.get(key, True) else off_text)
    steps.append("2. Rules: " + "; ".join(rule_bits) + ".")

    result = RunResult()
    thanks = acknowledges = recovers = comp_scrubs = 0
    for review in reviews:
        rating = float(review.get("rating") or 0)
        if rules.get("escalate-low", True) and rating <= 2:
            result.escalations.append({"review": review, "reason": ESCALATION_REASON})
            continue
        draft = build_draft(review, rules, amenities=amenities, signoff=signoff,
                            competitors=competitors, return_visit_line=return_visit_line,
                            hotel_name=hotel_name)
        if draft.scrubbed:
            comp_scrubs += 1
        if draft.band == "thank":
            thanks += 1
        elif draft.band == "acknowledge":
            acknowledges += 1
        else:
            recovers += 1
        result.drafts.append({"review": review, "draft": draft.as_dict()})

    total_drafted = thanks + acknowledges + recovers
    step3 = (f"3. Drafted {_plural(total_drafted, 'reply', 'replies')}: {thanks} thank, "
            f"{acknowledges} acknowledge, {recovers} recover.")
    if comp_scrubs:
        step3 += f" {_plural(comp_scrubs, 'quoted line')} dropped for naming a competitor."
    steps.append(step3)

    if result.escalations:
        names = ", ".join(
            f"{e['review'].get('guest_name', 'a guest')} "
            f"({format_stars(e['review'].get('rating') or 0)}, {e['review'].get('source', '')})"
            for e in result.escalations)
        steps.append(f"4. Escalated to the duty manager, full record attached: {names}.")
    elif not rules.get("escalate-low", True):
        low = [r for r in reviews if float(r.get("rating") or 0) <= 2]
        if low:
            names = ", ".join(r.get("guest_name", "a guest") for r in low)
            steps.append(f"4. escalate-low is off - drafted anyway, even though 2 stars or "
                        f"below: {names}.")
        else:
            steps.append("4. No review this pass was 2 stars or below.")
    else:
        steps.append("4. No review this pass was 2 stars or below.")

    if inbox["oldest_days"]:
        steps.append(f"5. This run pulls the oldest waiting review down from "
                    f"{inbox['oldest_days']} day(s) to zero, once it is posted. "
                    f"Response speed is a ranking factor on every platform you watch.")
    else:
        steps.append("5. Nothing was waiting long enough to affect ranking speed.")

    platforms = sorted({r.get("source", "unknown") for r in reviews})
    headline = (f"{_plural(len(result.drafts), 'reply', 'replies')} drafted across "
               f"{_plural(len(platforms), 'platform')}")
    if result.escalations:
        headline += f", {len(result.escalations)} escalated to a human"
    headline += (f" - the inbox goes from {len(reviews)} unanswered to "
                f"{len(result.escalations)}.")
    steps.append(f"6. {headline}")

    result.steps = steps
    result.summary = {
        "unanswered": len(reviews), "drafted": len(result.drafts),
        "escalated": len(result.escalations), "thank": thanks, "acknowledge": acknowledges,
        "recover": recovers, "competitor_scrubs": comp_scrubs,
        "oldest_days": inbox["oldest_days"], "platforms": platforms,
    }
    return result
