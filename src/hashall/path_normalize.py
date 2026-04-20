from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
import time

from hashall.pathing import canonicalize_path
from hashall.qbittorrent import QBitTorrent, QBittorrentClient, get_qbittorrent_client
from hashall.rt_cache import load_rt_cache_snapshot
from hashall.rtorrent import (
    DEFAULT_RT_RPC_URL,
    DEFAULT_RT_SESSION_DIR,
    RTTorrentMeta,
    derive_rt_target_directory,
    fetch_rt_status_rows,
    load_rt_torrent_meta,
    normalize_rt_target_directory,
    rt_path_aligned,
    rt_apply_directory_repoint,
)


LEGACY_SEGMENT = "cross-seed-link"
CANONICAL_SEGMENT = "cross-seed"
_STOPPED_QB_STATES = {"stoppedup", "stoppeddl"}
_STOPPED_RT_STATES = {"stoppedup", "stoppeddl"}
_VERIFYING_QB_STATES = {"checkingdl", "checkingup", "checkingresumedata", "moving"}
_VERIFYING_RT_STATES = {"checking", "checkingup", "checkingdl", "checkup", "checkpending"}
_BAD_QB_STATES = {"error", "missingfiles"}
_BAD_RT_STATES = {"error"}


def _normalized_state_text(value: str | None) -> str:
    return str(value or "").strip().lower()


def is_qb_verifying_state(state: str | None) -> bool:
    return _normalized_state_text(state) in _VERIFYING_QB_STATES


def is_rt_verifying_state(state: str | None) -> bool:
    return _normalized_state_text(state) in _VERIFYING_RT_STATES


def is_qb_bad_terminal_state(state: str | None) -> bool:
    return _normalized_state_text(state) in _BAD_QB_STATES


def is_rt_bad_terminal_state(state: str | None) -> bool:
    return _normalized_state_text(state) in _BAD_RT_STATES


def derive_normalization_outcome(*, qb_state: str | None, rt_state: str | None) -> str:
    return derive_normalization_outcome_with_context(
        qb_state=qb_state,
        rt_state=rt_state,
        qb_path_converged=True,
        rt_path_converged=True,
        recovery_performed=False,
        ambiguous=False,
    )


def derive_normalization_outcome_with_context(
    *,
    qb_state: str | None,
    rt_state: str | None,
    qb_path_converged: bool,
    rt_path_converged: bool,
    recovery_performed: bool,
    ambiguous: bool,
) -> str:
    if recovery_performed:
        return "partial_state"
    if not qb_path_converged or not rt_path_converged:
        if ambiguous:
            return "ambiguous_needs_review"
        return "partial_state"
    qb_checking = is_qb_verifying_state(qb_state)
    rt_checking = is_rt_verifying_state(rt_state)
    if qb_checking or rt_checking:
        return "verifying"
    if is_qb_bad_terminal_state(qb_state) or is_rt_bad_terminal_state(rt_state):
        return "ambiguous_needs_review"
    if not _normalized_state_text(qb_state) or not _normalized_state_text(rt_state):
        return "path_converged"
    return "verified"


@dataclass(frozen=True)
class CrossSeedLinkNormalizationPlan:
    torrent_hash: str
    qb_state: str
    qb_should_resume: bool
    qb_old_save_path: str
    qb_new_save_path: str
    qb_old_content_path: str
    qb_new_content_path: str
    rt_state: str
    rt_should_restart: bool
    rt_old_directory: str
    rt_new_directory: str
    rt_old_apply_directory: str
    rt_new_apply_directory: str
    source_exists: bool
    target_exists: bool
    same_filesystem: bool
    source_device: int | None
    target_device: int | None
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["ready"] = self.ready
        return payload


@dataclass(frozen=True)
class CrossSeedLinkNormalizationResult:
    plan: CrossSeedLinkNormalizationPlan
    actions: list[str]
    warnings: list[str]
    outcome: str
    error: str | None
    qb_final_state: str
    qb_final_save_path: str
    qb_final_content_path: str
    rt_final_state: str
    rt_final_directory: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["plan"] = self.plan.to_dict()
        return payload


def _normalize_path_text(path_text: str | None) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    try:
        if path.exists():
            return str(canonicalize_path(path))
    except Exception:
        pass
    return str(path)


def _replace_path_segment(path_text: str, old_segment: str, new_segment: str) -> str:
    path = Path(str(path_text or "").strip())
    parts = list(path.parts)
    if old_segment not in parts:
        raise ValueError(f"missing_segment:{old_segment}")
    replaced = [new_segment if part == old_segment else part for part in parts]
    return str(Path(*replaced))


def _existing_parent(path: Path) -> Path | None:
    current = path if path.exists() else path.parent
    while True:
        if current.exists():
            return current
        if current == current.parent:
            return None
        current = current.parent


def _device_for_path(path_text: str | None) -> tuple[int | None, Path | None]:
    raw = str(path_text or "").strip()
    if not raw:
        return None, None
    existing = _existing_parent(Path(raw))
    if existing is None:
        return None, None
    try:
        return int(existing.stat().st_dev), existing
    except Exception:
        return None, existing


def _should_resume_qb(state: str) -> bool:
    return str(state or "").strip().lower() not in _STOPPED_QB_STATES


def _should_restart_rt(state: str) -> bool:
    return str(state or "").strip().lower() not in _STOPPED_RT_STATES


def _find_rt_row(torrent_hash: str, rows: list[dict] | None = None) -> dict | None:
    torrent_key = str(torrent_hash or "").strip().lower()
    candidate_rows = rows
    if candidate_rows is None:
        snapshot_rows = list(load_rt_cache_snapshot().get("rows") or [])
        candidate_rows = snapshot_rows or fetch_rt_status_rows()
    for row in candidate_rows:
        if str(row.get("hash") or "").strip().lower() == torrent_key:
            return row
    return None


def _derive_expected_rt_runtime_directory(
    *,
    qb_save_path: str,
    qb_content_path: str,
    rt_meta: RTTorrentMeta | None,
) -> str:
    return _normalize_path_text(
        derive_rt_target_directory(
            qb_save_path=_normalize_path_text(qb_save_path or ""),
            qb_content_path=_normalize_path_text(qb_content_path or ""),
            torrent_meta=rt_meta,
        )
    )


def _looks_like_timeout(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "read timed out" in text or "readtimeout" in text or "timed out" in text


def _qb_paths_converged(
    plan: CrossSeedLinkNormalizationPlan,
    qb_torrent: QBitTorrent | None,
) -> bool:
    if qb_torrent is None:
        return False
    actual_save = _normalize_path_text(getattr(qb_torrent, "save_path", ""))
    actual_content = _normalize_path_text(getattr(qb_torrent, "content_path", ""))
    return actual_save == plan.qb_new_save_path and actual_content == plan.qb_new_content_path


def _rt_paths_converged(
    plan: CrossSeedLinkNormalizationPlan,
    rt_row: dict | None,
) -> bool:
    if not rt_row:
        return False
    actual = _normalize_path_text((rt_row or {}).get("directory") or "")
    return actual == plan.rt_new_directory or rt_path_aligned(
        actual,
        qb_save_path=plan.qb_new_save_path,
        qb_content_path=plan.qb_new_content_path,
    )


def _best_effort_qb_info(
    qb_client: QBittorrentClient,
    torrent_hash: str,
) -> QBitTorrent | None:
    try:
        return qb_client.get_torrent_info(torrent_hash)
    except Exception:
        return None


def _best_effort_rt_row(
    torrent_hash: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> dict | None:
    try:
        return _find_rt_row(torrent_hash)
    except Exception:
        try:
            for row in fetch_rt_status_rows(rpc_url=rpc_url):
                if str(row.get("hash") or "").strip().lower() == str(torrent_hash or "").strip().lower():
                    return row
        except Exception:
            return None
    return None


def _build_normalization_result(
    plan: CrossSeedLinkNormalizationPlan,
    *,
    actions: list[str],
    warnings: list[str],
    qb_final: QBitTorrent | None,
    rt_final: dict | None,
    error: str | None = None,
    recovery_performed: bool = False,
    ambiguous: bool = False,
) -> CrossSeedLinkNormalizationResult:
    qb_final_state = str(getattr(qb_final, "state", "") or "")
    qb_final_save_path = _normalize_path_text(getattr(qb_final, "save_path", ""))
    qb_final_content_path = _normalize_path_text(getattr(qb_final, "content_path", ""))
    rt_final_state = str((rt_final or {}).get("state") or "")
    rt_final_directory = _normalize_path_text((rt_final or {}).get("directory") or "")
    outcome = derive_normalization_outcome_with_context(
        qb_state=qb_final_state,
        rt_state=rt_final_state,
        qb_path_converged=_qb_paths_converged(plan, qb_final),
        rt_path_converged=_rt_paths_converged(plan, rt_final),
        recovery_performed=recovery_performed,
        ambiguous=ambiguous,
    )
    return CrossSeedLinkNormalizationResult(
        plan=plan,
        actions=actions,
        warnings=warnings,
        outcome=outcome,
        error=error,
        qb_final_state=qb_final_state,
        qb_final_save_path=qb_final_save_path,
        qb_final_content_path=qb_final_content_path,
        rt_final_state=rt_final_state,
        rt_final_directory=rt_final_directory,
    )


def build_cross_seed_link_normalization_plan(
    torrent_hash: str,
    *,
    qb_torrent: QBitTorrent | None,
    rt_row: dict | None,
    rt_meta: RTTorrentMeta | None = None,
) -> CrossSeedLinkNormalizationPlan:
    torrent_key = str(torrent_hash or "").strip().lower()
    issues: list[str] = []

    qb_state = str(getattr(qb_torrent, "state", "") or "")
    qb_old_save_path = _normalize_path_text(getattr(qb_torrent, "save_path", ""))
    qb_old_content_path = _normalize_path_text(getattr(qb_torrent, "content_path", ""))

    if qb_torrent is None:
        issues.append("qb_torrent_missing")
    if not qb_old_save_path:
        issues.append("qb_save_path_missing")
    if not qb_old_content_path:
        issues.append("qb_content_path_missing")
    if getattr(qb_torrent, "auto_tmm", False):
        issues.append("qb_auto_tmm_enabled")
    if float(getattr(qb_torrent, "progress", 0.0) or 0.0) < 1.0 or int(getattr(qb_torrent, "amount_left", 0) or 0) > 0:
        issues.append("qb_not_complete")

    try:
        qb_new_save_path = _normalize_path_text(
            _replace_path_segment(qb_old_save_path, LEGACY_SEGMENT, CANONICAL_SEGMENT)
        )
    except ValueError:
        qb_new_save_path = qb_old_save_path
        issues.append("qb_save_path_missing_legacy_segment")
    try:
        qb_new_content_path = _normalize_path_text(
            _replace_path_segment(qb_old_content_path, LEGACY_SEGMENT, CANONICAL_SEGMENT)
        )
    except ValueError:
        qb_new_content_path = qb_old_content_path
        issues.append("qb_content_path_missing_legacy_segment")

    rt_state = str((rt_row or {}).get("state") or "")
    rt_old_directory = _normalize_path_text((rt_row or {}).get("directory") or "")
    if rt_row is None:
        issues.append("rt_row_missing")
    try:
        rt_replaced_directory = _normalize_path_text(
            _replace_path_segment(rt_old_directory, LEGACY_SEGMENT, CANONICAL_SEGMENT)
        )
    except ValueError:
        rt_replaced_directory = rt_old_directory
        issues.append("rt_directory_missing_legacy_segment")
    rt_new_directory = _derive_expected_rt_runtime_directory(
        qb_save_path=qb_new_save_path,
        qb_content_path=qb_new_content_path,
        rt_meta=rt_meta,
    ) or rt_replaced_directory
    rt_old_apply_directory = _normalize_path_text(normalize_rt_target_directory(rt_old_directory, rt_meta))
    rt_new_apply_directory = _normalize_path_text(normalize_rt_target_directory(rt_new_directory, rt_meta))
    if not rt_old_apply_directory or not rt_new_apply_directory:
        issues.append("rt_apply_directory_missing")

    source_exists = bool(qb_old_content_path and Path(qb_old_content_path).exists())
    target_exists = bool(qb_new_content_path and Path(qb_new_content_path).exists())
    if not source_exists:
        issues.append("source_content_missing")
    if target_exists:
        issues.append("target_content_already_exists")

    source_device, _ = _device_for_path(qb_old_content_path)
    target_device, _ = _device_for_path(qb_new_content_path)
    same_filesystem = source_device is not None and target_device is not None and source_device == target_device
    if not same_filesystem:
        issues.append("cross_filesystem_move_not_supported")

    return CrossSeedLinkNormalizationPlan(
        torrent_hash=torrent_key,
        qb_state=qb_state,
        qb_should_resume=_should_resume_qb(qb_state),
        qb_old_save_path=qb_old_save_path,
        qb_new_save_path=qb_new_save_path,
        qb_old_content_path=qb_old_content_path,
        qb_new_content_path=qb_new_content_path,
        rt_state=rt_state,
        rt_should_restart=_should_restart_rt(rt_state),
        rt_old_directory=rt_old_directory,
        rt_new_directory=rt_new_directory,
        rt_old_apply_directory=rt_old_apply_directory,
        rt_new_apply_directory=rt_new_apply_directory,
        source_exists=source_exists,
        target_exists=target_exists,
        same_filesystem=same_filesystem,
        source_device=source_device,
        target_device=target_device,
        issues=issues,
    )


def plan_cross_seed_link_normalization(
    torrent_hash: str,
    *,
    qb_client: QBittorrentClient | None = None,
    rt_rows: list[dict] | None = None,
) -> CrossSeedLinkNormalizationPlan:
    client = qb_client or get_qbittorrent_client()
    torrent_key = str(torrent_hash or "").strip().lower()
    qb_issue: str | None = None
    rt_issue: str | None = None
    try:
        info = client.get_torrent_info(torrent_key)
    except RuntimeError as exc:
        info = None
        qb_issue = f"qb_info_unavailable:{exc}"
    try:
        row = _find_rt_row(torrent_key, rows=rt_rows)
    except Exception as exc:
        row = None
        rt_issue = f"rt_status_unavailable:{exc}"
    rt_meta = load_rt_torrent_meta(DEFAULT_RT_SESSION_DIR, torrent_key)
    plan = build_cross_seed_link_normalization_plan(
        torrent_key,
        qb_torrent=info,
        rt_row=row,
        rt_meta=rt_meta,
    )
    issues = [*plan.issues]
    if rt_issue is not None:
        issues.insert(0, rt_issue)
    if qb_issue is not None:
        issues.insert(0, qb_issue)
    if issues != plan.issues:
        return replace(plan, issues=issues)
    return plan


def _wait_for_qb_target(
    qb_client: QBittorrentClient,
    torrent_hash: str,
    *,
    expected_save_path: str,
    expected_content_path: str,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.5,
) -> QBitTorrent | None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    expected_save = _normalize_path_text(expected_save_path)
    expected_content = _normalize_path_text(expected_content_path)

    while True:
        info = qb_client.get_torrent_info(torrent_hash)
        if info:
            actual_save = _normalize_path_text(getattr(info, "save_path", ""))
            actual_content = _normalize_path_text(getattr(info, "content_path", ""))
            if actual_save == expected_save and actual_content == expected_content:
                return info
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval_seconds)


def _set_qb_location_with_retry(
    qb_client: QBittorrentClient,
    torrent_hash: str,
    *,
    target_save_path: str,
    target_content_path: str,
    attempts: int = 5,
    delay_seconds: float = 0.5,
) -> bool:
    current = _wait_for_qb_target(
        qb_client,
        torrent_hash,
        expected_save_path=target_save_path,
        expected_content_path=target_content_path,
        timeout_seconds=0.0,
        interval_seconds=0.0,
    )
    if current is not None:
        return True

    for attempt in range(1, attempts + 1):
        if qb_client.set_location(torrent_hash, target_save_path):
            info = _wait_for_qb_target(
                qb_client,
                torrent_hash,
                expected_save_path=target_save_path,
                expected_content_path=target_content_path,
                timeout_seconds=8.0,
                interval_seconds=0.5,
            )
            if info is not None:
                return True
        else:
            info = _wait_for_qb_target(
                qb_client,
                torrent_hash,
                expected_save_path=target_save_path,
                expected_content_path=target_content_path,
                timeout_seconds=2.0,
                interval_seconds=0.5,
            )
            if info is not None:
                return True
        if attempt < attempts:
            time.sleep(min(delay_seconds * (2 ** (attempt - 1)), 8.0))

    final = _wait_for_qb_target(
        qb_client,
        torrent_hash,
        expected_save_path=target_save_path,
        expected_content_path=target_content_path,
        timeout_seconds=5.0,
        interval_seconds=0.5,
    )
    return final is not None


def _wait_for_rt_target(
    torrent_hash: str,
    *,
    expected_directory: str,
    expected_save_path: str = "",
    expected_content_path: str = "",
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.5,
    reject_bad_state: bool = False,
) -> dict | None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    expected = _normalize_path_text(expected_directory)

    while True:
        for row in fetch_rt_status_rows(rpc_url=rpc_url):
            if str(row.get("hash") or "").strip().lower() != str(torrent_hash or "").strip().lower():
                continue
            actual = _normalize_path_text(row.get("directory") or "")
            if actual == expected or rt_path_aligned(
                actual,
                qb_save_path=expected_save_path,
                qb_content_path=expected_content_path,
            ):
                if reject_bad_state and is_rt_bad_terminal_state(row.get("state")):
                    break
                return row
            break
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval_seconds)


def apply_cross_seed_link_normalization(
    plan: CrossSeedLinkNormalizationPlan,
    *,
    qb_client: QBittorrentClient | None = None,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> CrossSeedLinkNormalizationResult:
    if not plan.ready:
        raise RuntimeError(f"plan_not_ready issues={','.join(plan.issues)}")

    client = qb_client or get_qbittorrent_client()
    actions: list[str] = []
    warnings: list[str] = []
    qb_moved = False
    rt_moved = False
    rt_apply_ambiguous = False
    verified_qb: QBitTorrent | None = None
    verified_rt: dict | None = None

    try:
        if not client.pause_torrent(plan.torrent_hash):
            raise RuntimeError(f"qb_pause_failed error={client.last_error or 'unknown'}")
        actions.append("qb.pause")

        if not _set_qb_location_with_retry(
            client,
            plan.torrent_hash,
            target_save_path=plan.qb_new_save_path,
            target_content_path=plan.qb_new_content_path,
        ):
            raise RuntimeError(f"qb_set_location_failed error={client.last_error or 'unknown'}")
        qb_moved = True
        actions.append("qb.set_location")

        verified_qb = _wait_for_qb_target(
            client,
            plan.torrent_hash,
            expected_save_path=plan.qb_new_save_path,
            expected_content_path=plan.qb_new_content_path,
        )
        if verified_qb is None:
            raise RuntimeError("qb_verify_failed")

        try:
            rt_apply_directory_repoint(
                plan.torrent_hash,
                plan.rt_new_apply_directory,
                rpc_url=rpc_url,
                restart=plan.rt_should_restart,
            )
            rt_moved = True
            actions.append("rt.repoint")
        except Exception as rt_exc:
            if not _looks_like_timeout(rt_exc):
                raise
            rt_apply_ambiguous = True
            warnings.append(f"rt_apply_timeout:{rt_exc}")

        verified_rt = _wait_for_rt_target(
            plan.torrent_hash,
            expected_directory=plan.rt_new_directory,
            expected_save_path=plan.qb_new_save_path,
            expected_content_path=plan.qb_new_content_path,
            rpc_url=rpc_url,
            timeout_seconds=45.0 if rt_apply_ambiguous else 10.0,
            reject_bad_state=True,
        )
        if verified_rt is None:
            raise RuntimeError("rt_verify_failed")
        if rt_apply_ambiguous:
            actions.append("rt.repoint")
            rt_moved = True

        if plan.qb_should_resume:
            if client.resume_torrent(plan.torrent_hash):
                actions.append("qb.resume")
                qb_final = client.get_torrent_info(plan.torrent_hash) or verified_qb
            else:
                warnings.append(f"qb_resume_failed:{client.last_error or 'unknown'}")
                qb_final = client.get_torrent_info(plan.torrent_hash) or verified_qb
        else:
            qb_final = client.get_torrent_info(plan.torrent_hash) or verified_qb

        rt_final = _wait_for_rt_target(
            plan.torrent_hash,
            expected_directory=plan.rt_new_directory,
            expected_save_path=plan.qb_new_save_path,
            expected_content_path=plan.qb_new_content_path,
            rpc_url=rpc_url,
            timeout_seconds=0.0,
            interval_seconds=0.0,
            reject_bad_state=True,
        ) or verified_rt

        return _build_normalization_result(
            plan=plan,
            actions=actions,
            warnings=warnings,
            qb_final=qb_final,
            rt_final=rt_final,
        )
    except Exception as exc:
        rollback_steps: list[str] = []
        rollback_errors: list[str] = []

        if rt_moved:
            try:
                rt_apply_directory_repoint(
                    plan.torrent_hash,
                    plan.rt_old_apply_directory,
                    rpc_url=rpc_url,
                    restart=plan.rt_should_restart,
                )
                rollback_steps.append("rt.rollback")
            except Exception as rollback_exc:
                rollback_errors.append(f"rt.rollback:{rollback_exc}")

        if qb_moved and not rt_apply_ambiguous:
            try:
                if _set_qb_location_with_retry(
                    client,
                    plan.torrent_hash,
                    target_save_path=plan.qb_old_save_path,
                    target_content_path=plan.qb_old_content_path,
                ):
                    rollback_steps.append("qb.rollback")
                else:
                    rollback_errors.append(f"qb.rollback:{client.last_error or 'unknown'}")
            except Exception as rollback_exc:
                rollback_errors.append(f"qb.rollback:{rollback_exc}")

        if plan.qb_should_resume and not rt_apply_ambiguous:
            try:
                if client.resume_torrent(plan.torrent_hash):
                    rollback_steps.append("qb.resume")
                else:
                    rollback_errors.append(f"qb.resume:{client.last_error or 'unknown'}")
            except Exception as rollback_exc:
                rollback_errors.append(f"qb.resume:{rollback_exc}")

        detail = str(exc)
        if rollback_steps:
            detail += f" rollback={','.join(rollback_steps)}"
        if rollback_errors:
            detail += f" rollback_errors={';'.join(rollback_errors)}"
        warnings.extend(rollback_errors)
        final_actions = [*actions, *rollback_steps]
        qb_final = _best_effort_qb_info(client, plan.torrent_hash) or verified_qb
        rt_final = _best_effort_rt_row(plan.torrent_hash, rpc_url=rpc_url) or verified_rt
        recovery_performed = bool(
            rollback_steps
            or rollback_errors
            or ((qb_moved or rt_moved) and qb_moved != rt_moved)
        )
        ambiguous = bool(
            rt_apply_ambiguous
            or (not qb_moved and not rt_moved and not rollback_steps and not rollback_errors)
        )
        return _build_normalization_result(
            plan=plan,
            actions=final_actions,
            warnings=warnings,
            qb_final=qb_final,
            rt_final=rt_final,
            error=detail,
            recovery_performed=recovery_performed,
            ambiguous=ambiguous,
        )
