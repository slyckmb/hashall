# Script: tests/test_rt_qb_mirror_reconcile.py
# Version: 0.8.81
# Last-updated: 2026-09-26T18:12:00-04:00
# v0.8.81: cover fail-closed pre-mutation qB lookup and Phase 4 outcome guidance.
#
# Coverage for the Phase 3 periodic add-only RT->qB reconciler (PR #10, Issue #6),
# specifically the 8 required amendments from PR #8's manager critical review.
# Deliberately a separate file from test_client_drift.py so the existing manual
# sync/process-queue suite is left untouched (Issue #6's "regression tests
# preserving manual behavior").

import json
import time
from pathlib import Path

from click.testing import CliRunner

from hashall.bencode import bencode_dump
from hashall.cli import (
    DEFAULT_RT_QB_RECONCILE_LOCK,
    _apply_reconcile_rows,
    _load_client_drift_report,
    _process_reconcile_candidate,
    _print_rt_qb_event_status,
    _reconcile_cache_freshness,
    _reconcile_summary_classes,
    _select_reconcile_candidates,
    _client_drift_operator_guidance,
    cli,
)
from hashall.rtorrent import rt_live_confirm_mirror_candidate


def _write_rt_session(session_dir: Path, torrent_hash: str, directory: Path, name: str = "Release.One") -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    bencode_dump(
        session_dir / f"{torrent_hash.upper()}.torrent",
        {
            b"info": {
                b"name": name.encode("utf-8"),
                b"files": [{b"length": 123, b"path": [b"file.bin"]}],
            }
        },
    )
    bencode_dump(
        session_dir / f"{torrent_hash.upper()}.torrent.rtorrent",
        {b"directory": str(directory).encode("utf-8")},
    )


def _build_reconcile_candidate_rows(tmp_path: Path, *, torrent_hash: str = "aaa111") -> list[dict]:
    """Build one realistic mirror_rt_to_qb candidate row via the real report pipeline."""
    seed_root = tmp_path / "seeding" / "site"
    content_root = seed_root / "Release.One"
    content_root.mkdir(parents=True)
    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    _write_rt_session(session_dir, torrent_hash, content_root)
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text(
        json.dumps([
            {
                "hash": torrent_hash,
                "name": "Release.One",
                "directory": str(content_root),
                "state": "stalledUP",
                "category": "tv",
                "complete": 1,
            }
        ]),
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps({"mode": "rt-authoritative-mirror", "mirror_roots": [str(tmp_path / "seeding")]}),
        encoding="utf-8",
    )
    report = _load_client_drift_report(
        qb_cache_file=str(qb_cache),
        rt_cache_file=str(rt_cache),
        rt_session_dir=str(session_dir),
        policy_path=str(policy),
        policy_mode="rt-authoritative-mirror",
    )
    return _select_reconcile_candidates(report, hash_filters=(), limit=0)


class _FakeQbit:
    last_error = None

    def __init__(
        self,
        *,
        post_add_state: str = "stoppedUP",
        post_add_states: list[str] | None = None,
        post_add_progress: float = 1.0,
        post_add_amount_left: int = 0,
    ) -> None:
        self.present: dict[str, object] = {}
        self.added: list[dict] = []
        self.paused: list[str] = []
        self.post_add_state = post_add_state
        # Optional per-call state sequence (index clamps to the last entry once
        # exhausted) -- lets a test simulate a torrent that is first observed in a
        # transient state and only later transitions to an active-download state.
        self.post_add_states = list(post_add_states) if post_add_states else None
        self.post_add_progress = post_add_progress
        self.post_add_amount_left = post_add_amount_left
        self._poll_count = 0

    def get_torrent_info(self, torrent_hash: str):
        if torrent_hash in self.present:
            return self.present[torrent_hash]
        if any(event["hash"] == torrent_hash for event in self.added):
            if self.post_add_states:
                index = min(self._poll_count, len(self.post_add_states) - 1)
                state = self.post_add_states[index]
            else:
                state = self.post_add_state
            self._poll_count += 1
            return _Info(
                state=state,
                progress=self.post_add_progress,
                amount_left=self.post_add_amount_left,
            )
        return None

    def add_torrent_file(self, torrent_file, *, save_path, category, tags, stopped, skip_checking) -> bool:
        self.added.append({
            "hash": Path(torrent_file).stem.lower(),
            "save_path": save_path,
            "category": category,
            "tags": list(tags),
            "stopped": stopped,
            "skip_checking": skip_checking,
        })
        return True

    def pause_torrent(self, torrent_hash: str) -> bool:
        self.paused.append(torrent_hash)
        return True


class _Info:
    def __init__(self, *, state: str, progress: float, amount_left: int) -> None:
        self.state = state
        self.progress = progress
        self.amount_left = amount_left
        self.save_path = "/x"
        self.content_path = "/x"


def _confirm_ok(torrent_hash: str, expected_directory, *, rpc_url, timeout):
    return {
        "reachable": True,
        "found": True,
        "complete": True,
        "directory": expected_directory,
        "path_matches": True,
        "ok": True,
        "error": None,
    }


def _confirm_stale(torrent_hash: str, expected_directory, *, rpc_url, timeout):
    return {
        "reachable": True,
        "found": True,
        "complete": False,
        "directory": expected_directory,
        "path_matches": True,
        "ok": False,
        "error": "rt_not_complete",
    }


def _confirm_unreachable(torrent_hash: str, expected_directory, *, rpc_url, timeout):
    return {
        "reachable": False,
        "found": False,
        "complete": None,
        "directory": None,
        "path_matches": False,
        "ok": False,
        "error": "rt_unreachable:ConnectionError",
    }


# --- Amendment 1: live pre-mutation confirmation / stale-cache race rejection ---

def test_reconcile_skips_when_live_rt_confirm_finds_stale_candidate(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    assert rows, "fixture must produce one mirror_rt_to_qb candidate"
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_stale)
    fake = _FakeQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added, "must not add to qB when live RT confirm rejects the candidate"
    assert result["outcome_counts"] == {"skipped_stale": 1}
    assert not result["failed"]


def test_reconcile_fails_closed_when_rt_unreachable(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_unreachable)
    fake = _FakeQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added, "must not add to qB when RT confirmation cannot be trusted"
    assert result["outcome_counts"] == {"rt_unreachable": 1}
    assert len(result["failed"]) == 1


def test_rt_live_confirm_known_hash_not_found_fault_is_a_legitimate_skip(monkeypatch) -> None:
    """The only XML-RPC fault that legitimately means 'stale-cache race, hash is
    gone' is rTorrent's own 'invalid parameters: info-hash not found' fault --
    verified live against DEFAULT_RT_RPC_URL by calling d.directory with an
    unloaded hash (faultCode -500)."""

    def _raise_not_found(method, *args, **kwargs):
        raise RuntimeError("rt_xmlrpc_fault method=d.directory detail=invalid parameters: info-hash not found")

    monkeypatch.setattr("hashall.rtorrent.rt_xmlrpc_call", _raise_not_found)
    result = rt_live_confirm_mirror_candidate("aaa111", "/expected")
    assert result["reachable"] is True
    assert result["found"] is False
    assert result["ok"] is False
    assert "rt_fault_hash_not_found" in str(result["error"])


def test_rt_live_confirm_unrecognized_fault_fails_closed_not_skipped(monkeypatch) -> None:
    """PR #10 review finding (issuecomment-5826147394): rt_xmlrpc_call wraps every
    XML-RPC fault -- method/protocol/permission/server errors, not just the known
    'hash is gone' case -- in the same rt_xmlrpc_fault RuntimeError. An unrecognized
    fault must NOT be normalized into the stale-hash skip path; it must fail closed
    (reachable=False) so the reconciler treats it as rt_unreachable, not
    skipped_stale. Fault text verified live against DEFAULT_RT_RPC_URL by calling
    an unknown method (faultCode -506, distinct from the -500 hash-not-found
    fault)."""

    def _raise_unknown(method, *args, **kwargs):
        raise RuntimeError("rt_xmlrpc_fault method=d.directory detail=method 'd.directory' not defined")

    monkeypatch.setattr("hashall.rtorrent.rt_xmlrpc_call", _raise_unknown)
    result = rt_live_confirm_mirror_candidate("aaa111", "/expected")
    assert result["reachable"] is False
    assert result["found"] is False
    assert result["ok"] is False
    assert "rt_fault_unknown" in str(result["error"])


def test_reconcile_fails_closed_on_unrecognized_rt_fault_not_skipped_stale(tmp_path, monkeypatch) -> None:
    """End-to-end: an unrecognized RT XML-RPC fault during live confirmation must
    surface as rt_unreachable (nonzero exit), never as skipped_stale."""
    rows = _build_reconcile_candidate_rows(tmp_path)

    def _raise_unknown(method, *args, **kwargs):
        raise RuntimeError("rt_xmlrpc_fault method=d.directory detail=method 'd.directory' not defined")

    monkeypatch.setattr("hashall.rtorrent.rt_xmlrpc_call", _raise_unknown)
    fake = _FakeQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added
    assert result["outcome_counts"] == {"rt_unreachable": 1}
    assert len(result["failed"]) == 1


# --- Amendment 2: RT-side custom2 tag is deliberately NOT written by the reconciler ---

def test_reconcile_does_not_write_rt_side_custom2_tag(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)

    class _ExplodingServerProxy:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("reconciler must not talk to RT XML-RPC to write custom2")

    monkeypatch.setattr("xmlrpc.client.ServerProxy", _ExplodingServerProxy)
    fake = _FakeQbit(post_add_state="stoppedUP")
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert result["outcome_counts"] == {"ok": 1}
    assert fake.added and fake.added[0]["hash"] == rows[0]["hash"]


# --- Amendment 3: selection never reads or is vetoed by the journal ---

def test_reconcile_selection_ignores_journal_completion(tmp_path) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    torrent_hash = rows[0]["hash"]
    journal = tmp_path / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"event": "finished", "hash": torrent_hash, "status": "ok", "action": "mirror_rt_to_qb"}) + "\n",
        encoding="utf-8",
    )
    # _select_reconcile_candidates takes no journal_path parameter at all -- prove
    # the candidate is still selected regardless of what the journal says.
    selected = _select_reconcile_candidates({"rows": rows})
    assert len(selected) == 1
    assert selected[0]["hash"] == torrent_hash


# --- Amendment 4: fail loudly on semantic problems ---

def test_reconcile_verify_timeout_is_not_silently_swallowed(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    # "checkingUP" never satisfies _verify_qb_import_complete's progress/amount_left
    # condition within the tiny timeout below.
    fake = _FakeQbit(post_add_state="checkingUP", post_add_progress=0.5, post_add_amount_left=100)
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=0.2,
        verify_interval=0.1,
        qbit=fake,
    )
    assert result["outcome_counts"] == {"verify_timeout": 1}
    assert len(result["failed"]) == 1


def test_reconcile_cli_exits_nonzero_on_failure(tmp_path, monkeypatch) -> None:
    # Side effect: writes the qb.json / rt.json / session / policy.json fixture files
    # this CLI invocation reads back below.
    _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit(post_add_state="checkingUP", post_add_progress=0.5, post_add_amount_left=100)
    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", lambda: fake)

    session_dir = tmp_path / "session"
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    policy = tmp_path / "policy.json"
    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror", "reconcile",
            "--qb-cache-file", str(qb_cache),
            "--rt-cache-file", str(rt_cache),
            "--rt-session-dir", str(session_dir),
            "--policy", str(policy),
            "--cache-max-age", "999999",
            "--verify-timeout", "0.2",
            "--verify-interval", "0.1",
            "--journal", str(tmp_path / "journal.jsonl"),
            "--lock-file", str(tmp_path / "reconcile.lock"),
            "--apply",
        ],
    )
    assert result.exit_code != 0
    assert "verify_timeout" in result.output


# --- Amendment 4: active-download safety brake ---

def test_reconcile_safety_brake_pauses_active_download_and_stops_run(tmp_path, monkeypatch) -> None:
    first = _build_reconcile_candidate_rows(tmp_path)[0]
    # A second, distinctly-hashed candidate to prove the brake also stops later rows.
    second = dict(first)
    second["hash"] = "bbb222"
    rows = [first, second]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit(post_add_state="downloading")
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert fake.paused == [rows[0]["hash"]]
    assert result["outcome_counts"].get("safety_brake") == 1
    assert result["brake_tripped"] is True
    assert result["deferred"] == [rows[1]["hash"]]
    assert len(result["failed"]) == 1


def test_reconcile_stopped_download_state_is_not_a_brake_but_still_fails(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit(post_add_state="stoppedDL")
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert fake.paused == [], "stoppedDL is already stopped -- nothing to pause"
    assert result["outcome_counts"] == {"unverified_added": 1}
    assert len(result["failed"]) == 1


def test_reconcile_safety_brake_trips_on_active_download_discovered_during_verification(
    tmp_path, monkeypatch
) -> None:
    """PR #10 review finding (issuecomment-5826095123): the brake must not only
    fire on the immediate post-add check -- a torrent observed first as a
    transient/non-download state (e.g. checkingDL) can still transition to an
    active-download state on a later verification poll, and must be paused and
    fail the run at that point too."""
    first = _build_reconcile_candidate_rows(tmp_path)[0]
    second = dict(first)
    second["hash"] = "bbb222"
    rows = [first, second]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    # Immediate post-add check observes "checkingDL" (transient, not a brake state
    # and not stopped -- falls through into _verify_qb_import_complete), then the
    # first verification poll observes "downloading".
    fake = _FakeQbit(post_add_states=["checkingDL", "downloading"])
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=5.0,
        verify_interval=0.1,
        qbit=fake,
    )
    assert fake.paused == [rows[0]["hash"]]
    assert result["outcome_counts"].get("safety_brake") == 1
    assert result["brake_tripped"] is True
    assert result["deferred"] == [rows[1]["hash"]]
    assert len(result["failed"]) == 1


def test_reconcile_safety_brake_fires_on_already_present_active_download(tmp_path, monkeypatch) -> None:
    """A candidate this run never added can still be observed live in an
    active-download state (a pre-existing qB mirror qB itself resumed, or one
    added by other automation). Amendment 4's brake is unconditional ("if qB is
    ever observed in an active downloading state") -- it must not be
    short-circuited by the already_present early return, and must not exit
    green as an ordinary already_present outcome."""
    rows = _build_reconcile_candidate_rows(tmp_path)
    torrent_hash = rows[0]["hash"]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit()
    fake.present[torrent_hash] = _Info(state="downloading", progress=0.5, amount_left=100)
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added, "must not add -- already present in qB"
    assert fake.paused == [torrent_hash]
    assert result["outcome_counts"] == {"safety_brake": 1}
    assert result["brake_tripped"] is True
    assert len(result["failed"]) == 1


def test_reconcile_already_present_stopped_download_is_not_silently_healthy(tmp_path, monkeypatch) -> None:
    """Umbrella-manager blocking finding (issuecomment-5849848962): a stale RT-only
    discovery cache can classify a row as a candidate, then the mandatory live qB
    check in _process_reconcile_candidate finds it already present. No mutation
    happens this run, so the active-download safety brake never fires -- but an
    already-present stoppedDL/pausedDL mirror is exactly the already-stopped,
    non-brake case amendment 4 requires "leave it stopped, fail/alert, do not
    auto-recheck" for. It must not be silently reported as a healthy
    already_present success. A second, distinctly-hashed candidate proves this is
    genuinely non-brake (unlike an active-download already_present hit, it must not
    trip brake_tripped or defer the rest of the run). _FakeQbit also has no
    recheck_torrent(s) method at all, so any attempt to auto-recheck would crash
    this test outright -- "not rechecked" is structurally enforced, not just
    asserted via fake.paused."""
    first = _build_reconcile_candidate_rows(tmp_path)[0]
    # A second, distinctly-hashed candidate this run never observes as already
    # present in qB (only ``first["hash"]`` is pre-seeded into fake.present) --
    # its own outcome is irrelevant here; it exists solely to prove the first
    # candidate's already_present_unhealthy finding does NOT trip the brake or
    # defer the rest of the run the way an active-download already_present hit
    # would (test_reconcile_safety_brake_fires_on_already_present_active_download).
    second = dict(first)
    second["hash"] = "bbb222"
    rows = [first, second]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit()
    fake.present[first["hash"]] = _Info(state="stoppedDL", progress=0.5, amount_left=100)
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    first_event = result["events"][0]
    assert first_event["hash"] == first["hash"]
    assert first_event["status"] == "already_present_unhealthy"
    assert first_event["state"] == "stoppedDL"
    assert fake.paused == [], "stoppedDL is already stopped -- nothing to pause, and no recheck"
    assert result["outcome_counts"].get("already_present_unhealthy") == 1
    assert result["brake_tripped"] is False, "unhealthy already_present is not a brake condition"
    assert result["deferred"] == [], "unhealthy already_present must not defer the rest of the run"
    assert len(result["events"]) == 2, "second candidate must still be processed, not deferred"


def test_reconcile_pre_mutation_cache_fallback_fails_closed_without_mutation(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    torrent_hash = rows[0]["hash"]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)

    class _CacheBackedExistingQbit(_FakeQbit):
        def get_torrent_info(self, torrent_hash: str):
            self.last_error = "cache_fallback:live qB timeout"
            return _Info(state="stoppedUP", progress=1.0, amount_left=0)

    fake = _CacheBackedExistingQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added
    assert fake.paused == []
    assert result["outcome_counts"] == {"qb_live_lookup_failed": 1}
    assert len(result["failed"]) == 1
    assert "cache_fallback" in result["events"][0]["error"]


def test_reconcile_pre_mutation_live_lookup_error_without_cache_fails_closed(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)

    class _FailedLiveLookupQbit(_FakeQbit):
        def get_torrent_info(self, torrent_hash: str):
            self.last_error = "live qB connection refused"
            return None

    fake = _FailedLiveLookupQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added
    assert result["outcome_counts"] == {"qb_live_lookup_failed": 1}
    assert len(result["failed"]) == 1


def test_phase4_event_guidance_is_reconcile_only(capsys) -> None:
    _print_rt_qb_event_status({"event": "reconcile", "status": "already_present"})
    reconcile_output = capsys.readouterr().out
    assert "guidance:" in reconcile_output
    assert "healthy:" in reconcile_output

    _print_rt_qb_event_status({"event": "finished", "status": "already_present"})
    manual_output = capsys.readouterr().out
    assert "guidance:" not in manual_output


def test_reconcile_phase4_summary_classes_distinguish_operator_actions() -> None:
    classes = _reconcile_summary_classes(
        {
            "ok": 1,
            "already_present": 2,
            "would_add": 3,
            "already_present_unhealthy": 1,
            "qb_live_lookup_failed": 1,
            "skipped_stale": 4,
        },
        deferred_count=2,
    )
    assert classes == {
        "healthy": 3,
        "actionable": 3,
        "manual_review": 2,
        "no_action": 4,
        "deferred": 2,
    }


def test_phase4_client_drift_guidance_keeps_mutation_boundaries_explicit() -> None:
    assert "do not auto-recheck" in _client_drift_operator_guidance(
        "qb_unverified_mirror", "inspect_qb_unverified_mirror"
    )
    assert "never deletes" in _client_drift_operator_guidance("qb_only", "remove_from_qb")
    assert "live RT confirmation" in _client_drift_operator_guidance("rt_only", "mirror_rt_to_qb")
    assert "explicit classified action" in _client_drift_operator_guidance("path_drift", "repoint_qb_to_rt_path")


def test_reconcile_already_present_healthy_mirror_stays_green(tmp_path, monkeypatch) -> None:
    """Counterpart to the unhealthy case above: a pre-existing qB mirror observed
    live in the base-design healthy state (stoppedUP, fully complete) must remain
    an ordinary successful already_present outcome, not be swept into
    already_present_unhealthy by an overly broad state check."""
    rows = _build_reconcile_candidate_rows(tmp_path)
    torrent_hash = rows[0]["hash"]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit()
    fake.present[torrent_hash] = _Info(state="stoppedUP", progress=1.0, amount_left=0)
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert not fake.added, "must not add -- already present in qB"
    assert fake.paused == []
    assert result["outcome_counts"] == {"already_present": 1}
    assert result["failed"] == []


# --- Amendment 5: post-mutation validation must be against live qB, not cache ---

def test_reconcile_rejects_verify_backed_by_cache_fallback(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)

    class _CacheFallbackQbit(_FakeQbit):
        def get_torrent_info(self, torrent_hash: str):
            info = super().get_torrent_info(torrent_hash)
            if info is not None and any(event["hash"] == torrent_hash for event in self.added):
                self.last_error = "cache_fallback:qb unreachable"
            return info

    fake = _CacheFallbackQbit(post_add_state="stoppedUP")
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
    )
    assert result["outcome_counts"] == {"verify_timeout": 1}
    assert "cache_fallback" in result["events"][0]["error"]


# --- Amendment 6: orphan (qB-only) cleanup is untouched by the reconciler ---

def test_reconcile_never_selects_qb_only_orphan_rows(tmp_path) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    report = {
        "rows": rows + [
            {
                "hash": "bbb222",
                "side": "qb_only",
                "action": "remove_from_qb",
                "qb": {"save_path": "/somewhere", "state": "stoppedUP"},
            }
        ]
    }
    selected = _select_reconcile_candidates(report)
    assert [row["hash"] for row in selected] == [rows[0]["hash"]]


# --- Amendment 8: bounded execution timeout ---

def test_reconcile_defers_candidates_once_deadline_has_passed(tmp_path, monkeypatch) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    second = dict(rows[0])
    second["hash"] = "bbb222"
    rows = [rows[0], second]
    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", _confirm_ok)
    fake = _FakeQbit()
    result = _apply_reconcile_rows(
        rows,
        do_apply=True,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
        qbit=fake,
        deadline=time.time() - 1.0,
    )
    assert result["events"] == []
    assert set(result["deferred"]) == {"aaa111", "bbb222"}
    assert not result["failed"], "a deferred-only run (no attempted failures) must not be treated as a failure"


# --- Cache freshness gate (amendment 1's discovery-time threshold) ---

def test_reconcile_cache_freshness_rejects_stale_files(tmp_path) -> None:
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text("[]", encoding="utf-8")
    old = time.time() - 10_000
    import os

    os.utime(qb_cache, (old, old))
    os.utime(rt_cache, (old, old))
    ok, problems = _reconcile_cache_freshness(
        qb_cache_file=str(qb_cache), rt_cache_file=str(rt_cache), max_age_s=300.0
    )
    assert ok is False
    assert problems


def test_reconcile_cli_fails_closed_on_stale_cache(tmp_path) -> None:
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    qb_cache.write_text("[]", encoding="utf-8")
    rt_cache.write_text("[]", encoding="utf-8")
    import os

    old = time.time() - 10_000
    os.utime(qb_cache, (old, old))
    os.utime(rt_cache, (old, old))
    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror", "reconcile",
            "--qb-cache-file", str(qb_cache),
            "--rt-cache-file", str(rt_cache),
            "--rt-session-dir", str(tmp_path),
            "--cache-max-age", "300",
            "--journal", str(tmp_path / "journal.jsonl"),
        ],
    )
    assert result.exit_code != 0
    assert "cache freshness gate failed" in result.output or "stale" in result.output


def test_reconcile_help_makes_live_poll_vs_recheck_boundary_explicit() -> None:
    result = CliRunner().invoke(cli, ["rt-qb-mirror", "reconcile", "--help"])
    assert result.exit_code == 0
    normalized = " ".join(result.output.split())
    assert "observation only" in normalized
    assert "rechecks qB; must be > 0" in normalized
    assert "never issues a qB force-recheck" in normalized


def test_reconcile_rejects_zero_verify_timeout(tmp_path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "rt-qb-mirror", "reconcile",
            "--verify-timeout", "0",
            "--journal", str(tmp_path / "journal.jsonl"),
        ],
    )
    assert result.exit_code != 0
    assert "must be > 0" in result.output


def test_reconcile_dry_run_still_runs_live_rt_confirm_and_does_not_construct_qb_client(
    tmp_path, monkeypatch
) -> None:
    rows = _build_reconcile_candidate_rows(tmp_path)
    calls: list[str] = []

    def tracking_confirm(torrent_hash, expected_directory, *, rpc_url, timeout):
        calls.append(torrent_hash)
        return _confirm_ok(torrent_hash, expected_directory, rpc_url=rpc_url, timeout=timeout)

    monkeypatch.setattr("hashall.rtorrent.rt_live_confirm_mirror_candidate", tracking_confirm)

    def fail_client():
        raise AssertionError("dry-run must not construct a qB client")

    monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", fail_client)
    result = _apply_reconcile_rows(
        rows,
        do_apply=False,
        journal=tmp_path / "journal.jsonl",
        verify_timeout=1.0,
    )
    assert calls == [rows[0]["hash"]]
    assert result["outcome_counts"] == {"would_add": 1}


def test_reconcile_apply_skips_when_lock_held(tmp_path, monkeypatch) -> None:
    import fcntl

    # Side effect: writes a valid non-empty qb.json / rt.json / session / policy.json
    # fixture (an empty rt.json reads back as freshness="missing", not "fresh").
    _build_reconcile_candidate_rows(tmp_path)
    qb_cache = tmp_path / "qb.json"
    rt_cache = tmp_path / "rt.json"
    session_dir = tmp_path / "session"
    policy = tmp_path / "policy.json"

    lock_path = tmp_path / "reconcile.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        def fail_client():
            raise AssertionError("must not construct a qB client when the lock is held")

        monkeypatch.setattr("hashall.qbittorrent.get_qbittorrent_client", fail_client)
        result = CliRunner().invoke(
            cli,
            [
                "rt-qb-mirror", "reconcile",
                "--qb-cache-file", str(qb_cache),
                "--rt-cache-file", str(rt_cache),
                "--rt-session-dir", str(session_dir),
                "--policy", str(policy),
                "--cache-max-age", "999999",
                "--lock-file", str(lock_path),
                "--journal", str(tmp_path / "journal.jsonl"),
                "--apply",
            ],
        )
        assert result.exit_code == 0
        assert "skipped" in result.output
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()


def test_reconcile_default_lock_path_is_dedicated_to_reconcile() -> None:
    # Guards against accidentally sharing a lock path with sync/process-queue, which
    # would change their concurrency semantics as a side effect of this PR.
    assert "reconcile" in str(DEFAULT_RT_QB_RECONCILE_LOCK)
