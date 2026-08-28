"""Tests for the loop: adapters, the review-status FSM, and the write guard.

Mirrors reference-agent's own test style: call the pieces the loop is made of
(core.store, core.review, the reviews adapters, tools.engine) directly rather
than importing tools/run.py or tools/review.py as modules - those two are
scripts (they rely on Python auto-adding their own folder to sys.path when
run as `python3 tools/run.py`), so they are covered here by subprocess checks
against `make demo` / `make doctor` instead.

``_settings()`` never reads this repo's own `config/agent.yaml` or
`config/hotel.yaml` - it points `AGENT_CONFIG_DIR` at a tmp copy of the
shipped `.example.yaml` files instead. A hotel following
`workflows/00-setup.md` step 3 replaces `competitors` (and everything else)
in their own `config/agent.yaml`; that must never turn `make test` red
(factory/workflows/build-repo.md §5, "tests never read the live config").
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_settings  # noqa: E402
from core.review import WriteBlocked  # noqa: E402
from core.store import Store  # noqa: E402
from tools.engine import process_reviews  # noqa: E402
from tools.reviews_adapters import ReviewsCsv, ReviewsMock  # noqa: E402

EXPECTED_BANDS = {
    "google-1001": "thank", "tripadvisor-2044": None,   # escalated, no band
    "bookingcom-3087": "acknowledge", "tripadvisor-2045": None,
    "google-1003": "thank",
}


def _settings(monkeypatch, tmp_path, mode: str = "shadow"):
    """Settings built from the shipped example config, isolated from a
    hotel's own edits. See the module docstring."""
    cfg_dir = tmp_path / "example_config"
    cfg_dir.mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "hotel.example.yaml", cfg_dir / "hotel.yaml")
    shutil.copy(REPO_ROOT / "config" / "agent.example.yaml", cfg_dir / "agent.yaml")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("AGENT_MODE", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return load_settings(mode=mode)


def test_reviews_mock_lists_every_fixture_and_skips_already_answered(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    reviews = ReviewsMock(settings).list_reviews()
    assert len(reviews) == 8  # one already responded=true fixture is still returned as-is
    unanswered = [r for r in reviews if not r.get("responded")]
    assert len(unanswered) == 7
    assert all(r.get("id") for r in unanswered)


def test_process_reviews_on_fixtures_matches_expected_bands_and_escalations(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    reviews = ReviewsMock(settings).list_reviews()
    unanswered = [r for r in reviews if not r.get("responded")]
    result = process_reviews(unanswered, dict(settings.agent_get("rules", {})), "2026-08-27",
                             amenities=settings.agent_get("amenities", {}),
                             competitors=settings.agent_get("competitors", []))
    escalated_ids = {e["review"]["id"] for e in result.escalations}
    drafted = {d["review"]["id"]: d["draft"]["band"] for d in result.drafts}
    for review_id, expected in EXPECTED_BANDS.items():
        if expected is None:
            assert review_id in escalated_ids, review_id
        else:
            assert drafted.get(review_id) == expected, review_id
    scrubbed = {d["review"]["id"] for d in result.drafts if d["draft"]["scrubbed"]}
    assert "bookingcom-3087" in scrubbed


def test_dedup_skips_reviews_already_seen_on_a_previous_pass(tmp_path, monkeypatch):
    store = Store(_settings(monkeypatch, tmp_path), path=tmp_path / "loop.db")
    item = store.upsert_item("reviews", "google-1001", kind="review", payload={"id": "google-1001"})
    # run.py always moves a review out of `new` once it is drafted or escalated;
    # a row still in `new` was parked mid-pass and is deliberately NOT "seen".
    assert store.already_processed("reviews", ["google-1001"]) == set()
    store.transition(item.id, "pending_review", actor="agent")
    seen = store.already_processed("reviews", ["google-1001", "google-1002"])
    assert seen == {"google-1001"}
    store.close()


def test_reply_without_an_approved_item_is_blocked_in_shadow_mode(tmp_path, monkeypatch):
    settings = _settings(monkeypatch, tmp_path)
    adapter = ReviewsMock(settings)
    try:
        adapter.reply("google-1001", "a reply nobody approved")
        assert False, "expected WriteBlocked"
    except WriteBlocked as exc:
        assert "shadow" in str(exc)


def test_shadow_blocks_even_an_approved_and_claimed_item(tmp_path, monkeypatch):
    """`mode: shadow` is a true kill switch: an item a human approved, and
    `claim_for_send()` has already moved to `sending`, still cannot post
    while shadow is on - see core/review.py and workflows/90-go-live.md.
    Approving in shadow only records the decision; it never lets a reply
    reach a guest until you switch to `mode: live`.
    """
    settings = _settings(monkeypatch, tmp_path)
    store = Store(settings, path=tmp_path / "post.db")
    item = store.upsert_item("reviews", "google-1001", kind="review",
                             payload={"id": "google-1001"})
    store.set_fields(item.id, draft={"body": "Dear Anneke, thank you."})
    store.transition(item.id, "pending_review", actor="agent")
    store.transition(item.id, "approved", actor="human")
    claimed = store.claim_for_send()
    assert len(claimed) == 1 and claimed[0].review_status == "sending"

    adapter = ReviewsMock(settings)
    try:
        adapter.reply("google-1001", "Dear Anneke, thank you.", item=claimed[0])
        assert False, "expected WriteBlocked - shadow blocks every write, approved or not"
    except WriteBlocked as exc:
        assert "shadow" in str(exc)
    store.close()


def test_live_mode_lets_an_approved_and_claimed_item_post(tmp_path, monkeypatch):
    """The counterpart to the test above: once `mode: live` and a human has
    approved the item, `reviews.reply()` really runs - this is the only path
    that ever posts, for any star rating (`docs/safety.md`).
    """
    settings = _settings(monkeypatch, tmp_path, mode="live")
    store = Store(settings, path=tmp_path / "post.db")
    item = store.upsert_item("reviews", "google-1001", kind="review",
                             payload={"id": "google-1001"})
    store.set_fields(item.id, draft={"body": "Dear Anneke, thank you."})
    store.transition(item.id, "pending_review", actor="agent")
    store.transition(item.id, "approved", actor="human")
    claimed = store.claim_for_send()
    assert len(claimed) == 1 and claimed[0].review_status == "sending"

    adapter = ReviewsMock(settings)
    result = adapter.reply("google-1001", "Dear Anneke, thank you.", item=claimed[0])
    assert result["ok"] is True
    store.mark_sent(item.id, result["message_id"])
    assert store.get_item(item.id).review_status == "sent"

    outbox = json.loads(Path(result["logged_to"]).read_text().splitlines()[-1])
    assert outbox["review_id"] == "google-1001"
    store.close()


def test_csv_adapter_reads_loosely_matched_headers(tmp_path, monkeypatch):
    imports_dir = tmp_path / "imports"
    imports_dir.mkdir()
    (imports_dir / "reviews.csv").write_text(
        "Review Id,Platform,Score,Guest,Review Date,Title,Comment,Theme,Answered\n"
        "csv-1,Google,4,Jamie Lee,2026-08-01,Nice stay,Would come back,rooms,false\n",
        encoding="utf-8")

    class _Config:
        def get(self, key, default=None):
            return str(imports_dir) if key == "imports_dir" else default

    settings = _settings(monkeypatch, tmp_path)
    adapter = ReviewsCsv(settings, _Config())
    reviews = adapter.list_reviews()
    assert len(reviews) == 1
    assert reviews[0]["id"] == "csv-1"
    assert reviews[0]["rating"] == 4.0
    assert reviews[0]["guest_name"] == "Jamie Lee"
    assert reviews[0]["responded"] is False


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=60)


def test_demo_cli_prints_demo_ok():
    proc = _run_cli("tools/demo.py")
    assert proc.returncode == 0, proc.stderr
    assert "DEMO OK" in proc.stdout
    assert "Traceback" not in proc.stderr


def test_doctor_cli_never_tracebacks_even_with_placeholder_config():
    proc = _run_cli("tools/doctor.py")
    assert "Traceback" not in (proc.stdout + proc.stderr)
    assert "doctor" in proc.stdout.lower()


def test_review_cli_shows_sample_marker_for_a_mock_adapter_item(monkeypatch, tmp_path):
    """core/store.py tags an item read through a mock adapter outside `make
    demo` as `_sample` (`Item.is_sample`) - `tools/review.py list` and `show`
    must flag it so a human working the real queue never mistakes a shipped
    sample for a real guest review. Run via subprocess (see module
    docstring) since tools/review.py is a script, not an importable module."""
    settings = _settings(monkeypatch, tmp_path)
    sandbox = tmp_path / "sandbox-repo"
    sandbox.mkdir()
    monkeypatch.setenv("AGENT_REPO_ROOT", str(sandbox))

    store = Store(settings)
    item = store.upsert_item("reviews", "sample-marker-1", kind="review",
                             payload={"title": "Lovely stay", "rating": 5,
                                      "source": "google", "_sample": True})
    store.transition(item.id, "pending_review", "agent")
    store.close()

    proc = _run_cli("tools/review.py", "list")
    assert "[SAMPLE DATA]" in proc.stdout, proc.stdout + proc.stderr

    proc2 = _run_cli("tools/review.py", "show", item.id)
    assert "[SAMPLE DATA]" in proc2.stdout, proc2.stdout + proc2.stderr
