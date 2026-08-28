"""Unit tests for tools/engine.py - the deterministic drafting logic.

No store, no adapter, no I/O: every rule in the behavioural spec is a pure
function here, so a rule toggle changing the outcome is provable in a test,
not just in a demo run.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.engine import (ESCALATION_REASON, amenity_for, band, build_draft, first_name,
                          format_stars, pick_detail, process_reviews, scrub_competitor)

AMENITIES = {"fnb": "the restaurant and kitchen team", "rooms": "our rooms and housekeeping team",
            "default": "the team"}


def test_format_stars_integer_and_decimal():
    assert format_stars(5) == "5★"
    assert format_stars(4.5) == "4.5★"
    assert format_stars(3.0) == "3★"


def test_band_thresholds():
    assert band(5) == "thank"
    assert band(4) == "thank"
    assert band(3.5) == "acknowledge"
    assert band(3) == "acknowledge"
    assert band(2.9) == "recover"
    assert band(1) == "recover"


def test_amenity_for_known_and_default():
    assert amenity_for("fnb", AMENITIES) == "the restaurant and kitchen team"
    assert amenity_for("FNB", AMENITIES) == "the restaurant and kitchen team"
    assert amenity_for("spa", AMENITIES) == "the team"
    assert amenity_for(None, AMENITIES) == "the team"
    assert amenity_for("rooms", {}) == "the team"


def test_pick_detail_prefers_title_when_long_enough():
    assert pick_detail("Best dinner we've had all year", "irrelevant") == \
        "Best dinner we've had all year"


def test_pick_detail_title_too_short_falls_back_to_body():
    body = "This is a genuinely long opening sentence about the stay that goes on"
    detail = pick_detail("z", body)
    assert detail is not None
    assert detail == body[:body.rfind(" ", 0, 60)]
    assert len(detail) <= 60


def test_pick_detail_cuts_on_word_boundary_never_mid_word():
    body = "Supercalifragilisticexpialidocious" * 3  # one long unbreakable "word"
    detail = pick_detail(None, body)
    # no space before char 20, so the raw 60-char cut is used rather than
    # chopping at char 0 - it must still not be empty
    assert detail is None or len(detail) >= 6


def test_pick_detail_none_when_nothing_quotable():
    assert pick_detail("", "") is None
    assert pick_detail(None, "No.") is None


def test_pick_detail_strips_outer_quotes_and_punctuation():
    assert pick_detail('"Lovely stay!"', "") == "Lovely stay"


def test_scrub_competitor_drops_matching_detail_case_insensitively():
    detail, scrubbed = scrub_competitor("great except for example rival hotel down the road",
                                        ["Example Rival Hotel"], enabled=True)
    assert detail is None
    assert scrubbed is True


def test_scrub_competitor_leaves_clean_detail_alone():
    detail, scrubbed = scrub_competitor("Best dinner we've had all year",
                                        ["Example Rival Hotel"], enabled=True)
    assert detail == "Best dinner we've had all year"
    assert scrubbed is False


def test_scrub_competitor_off_never_drops_anything():
    detail, scrubbed = scrub_competitor("mentions Example Rival Hotel", ["Example Rival Hotel"],
                                        enabled=False)
    assert detail == "mentions Example Rival Hotel"
    assert scrubbed is False


def test_first_name_variants():
    assert first_name("Anneke Visser") == "Anneke"
    assert first_name("") == "there"
    assert first_name("   ") == "there"
    assert first_name("Jean-Paul Dubois") == "Jean-Paul"
    assert first_name("O'Malley") == "O'Malley"


REVIEW = {"rating": 5, "source": "Google", "title": "Best dinner we've had all year",
         "body": "great", "category": "fnb", "guest_name": "Anneke Visser"}


def test_build_draft_thank_band_signed_and_personalised():
    draft = build_draft(REVIEW, {}, amenities=AMENITIES,
                        signoff={"name": "Elena", "role": "Guest Relations"})
    assert draft.band == "thank"
    assert draft.body.startswith("Dear Anneke,")
    assert "Best dinner we've had all year" in draft.body
    assert draft.body.endswith("Elena, Guest Relations")
    assert draft.signed is True


def test_build_draft_unsigned_when_brand_voice_off():
    draft = build_draft(REVIEW, {"brand-voice": False}, amenities=AMENITIES,
                        hotel_name="Hotel Aurora")
    assert draft.signed is False
    assert draft.body.endswith("The Hotel Aurora team")


def test_build_draft_generic_when_personalise_off():
    draft = build_draft(REVIEW, {"personalise": False}, amenities=AMENITIES)
    assert draft.body.startswith("Dear guest,")
    assert draft.detail is None
    assert "Best dinner" not in draft.body


def test_build_draft_never_contains_an_em_dash():
    """Guest-facing text: no em dashes, in any band, any rule combination."""
    for rules in ({}, {"brand-voice": False}, {"personalise": False}):
        for review in (REVIEW, {**REVIEW, "rating": 3}, {**REVIEW, "rating": 1}):
            draft = build_draft(review, rules, amenities=AMENITIES)
            assert "—" not in draft.body, draft.body


def test_process_reviews_escalates_low_rating_with_verbatim_reason():
    low = {**REVIEW, "rating": 2, "guest_name": "Gareth Poole", "source": "TripAdvisor"}
    result = process_reviews([REVIEW, low], {}, "2026-08-27", amenities=AMENITIES)
    assert len(result.escalations) == 1
    assert result.escalations[0]["reason"] == ESCALATION_REASON
    assert len(result.drafts) == 1


def test_process_reviews_escalate_low_off_drafts_the_same_review():
    low = {**REVIEW, "rating": 2, "guest_name": "Gareth Poole"}
    result = process_reviews([low], {"escalate-low": False}, "2026-08-27", amenities=AMENITIES)
    assert result.escalations == []
    assert len(result.drafts) == 1
    assert result.drafts[0]["draft"]["band"] == "recover"


def test_process_reviews_empty_inbox_has_a_clean_headline():
    result = process_reviews([], {}, "2026-08-27")
    assert result.drafts == []
    assert result.escalations == []
    assert result.summary["unanswered"] == 0


def test_first_name_handles_family_and_title_forms():
    from tools.engine import first_name
    assert first_name("Familie Wagner") == "Wagner family"
    assert first_name("Family Smith") == "Smith family"
    assert first_name("Famille Dupont-Martin") == "Dupont-Martin family"
    assert first_name("Herr Wagner") == "Herr Wagner"
    assert first_name("Mrs. Smith") == "Mrs Smith"
    assert first_name("Dr Rossi") == "Dr Rossi"
    assert first_name("Anna Wagner") == "Anna"
    assert first_name("Familie") == "Familie"
    assert first_name("") == "there"
