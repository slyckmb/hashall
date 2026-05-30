"""
qBittorrent Web API integration (read-only).

Connects to qBittorrent to retrieve torrent information for payload mapping.
"""

import json
import os
import requests
import shutil
import time
from requests.exceptions import ConnectionError as RequestsConnectionError
from urllib.parse import parse_qs, urlsplit
from typing import Any, List, Dict, Optional, Iterable
from dataclasses import dataclass, asdict
from pathlib import Path

from hashall.bencode import as_text, bencode_decode


DEFAULT_QB_CACHE_DIR = Path.home() / ".cache" / "silo-qb"
DEFAULT_QB_CACHE_FILE = DEFAULT_QB_CACHE_DIR / "torrents-info.json"
DEFAULT_QB_CACHE_META_FILE = DEFAULT_QB_CACHE_DIR / "torrents-info.meta.json"
LEGACY_QB_CACHE_DIR = Path.home() / ".cache" / "hashall-qb"
LEGACY_QB_CACHE_FILE = LEGACY_QB_CACHE_DIR / "torrents-info.json"
LEGACY_QB_CACHE_META_FILE = LEGACY_QB_CACHE_DIR / "torrents-info.meta.json"
DEFAULT_QB_BT_BACKUP_DIR = Path("/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup")


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _tracker_urls_from_magnet_uri(magnet_uri: str) -> List[str]:
    magnet = str(magnet_uri or "").strip()
    if not magnet:
        return []
    try:
        query = parse_qs(urlsplit(magnet).query, keep_blank_values=False)
    except Exception:
        return []
    return _dedupe_preserve_order(query.get("tr", []))


def _flatten_tracker_values(value: Any) -> List[str]:
    if isinstance(value, bytes):
        text = as_text(value).strip()
        return [text] if text else []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_flatten_tracker_values(item))
        return out
    return []


def _tracker_urls_from_fastresume(path: Path) -> List[str]:
    try:
        doc = bencode_decode(path.read_bytes())
    except Exception:
        return []
    if not isinstance(doc, dict):
        return []
    return _dedupe_preserve_order(_flatten_tracker_values(doc.get(b"trackers")))


def _tracker_domains(urls: Iterable[str]) -> List[str]:
    domains: List[str] = []
    for url in urls:
        try:
            host = (urlsplit(url).hostname or "").strip().lower()
        except Exception:
            host = ""
        if host:
            domains.append(host)
    return _dedupe_preserve_order(domains)


def _http_tracker_urls(urls: Iterable[str]) -> List[str]:
    out: List[str] = []
    for url in urls:
        try:
            scheme = (urlsplit(url).scheme or "").lower()
        except Exception:
            scheme = ""
        if scheme in {"http", "https"}:
            out.append(url)
    return out


def get_torrents_from_cache(
    max_age_s: float = 30.0,
    cache_path: "Path | None" = None,
) -> "list[dict] | None":
    """Read the shared qB cache file if it is fresh enough.

    Returns the parsed list of torrent dicts, or None if the cache is absent
    or older than *max_age_s* seconds.  Never raises; returns None on any error.
    """
    if cache_path is None:
        cache_path = _resolve_default_qb_cache_file(max_age_s=max_age_s)
    try:
        age = time.time() - os.stat(cache_path).st_mtime
        if age > max_age_s:
            return None
        with cache_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _cache_is_fresh(path: Path, *, max_age_s: float) -> bool:
    try:
        return (time.time() - os.stat(path).st_mtime) <= max_age_s
    except OSError:
        return False


def _resolve_default_qb_cache_file(*, max_age_s: float = 30.0) -> Path:
    if _cache_is_fresh(DEFAULT_QB_CACHE_FILE, max_age_s=max_age_s):
        return DEFAULT_QB_CACHE_FILE
    if _cache_is_fresh(LEGACY_QB_CACHE_FILE, max_age_s=max_age_s):
        return LEGACY_QB_CACHE_FILE
    return DEFAULT_QB_CACHE_FILE


def _resolve_default_qb_cache_meta_file() -> Path:
    if DEFAULT_QB_CACHE_META_FILE.exists():
        return DEFAULT_QB_CACHE_META_FILE
    if LEGACY_QB_CACHE_META_FILE.exists():
        return LEGACY_QB_CACHE_META_FILE
    return DEFAULT_QB_CACHE_META_FILE


def _load_json_file(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def get_qb_cache_meta(meta_path: "Path | None" = None) -> "dict | None":
    path = meta_path or _resolve_default_qb_cache_meta_file()
    payload = _load_json_file(path)
    return payload if isinstance(payload, dict) else None


def get_qb_cached_server_profile(meta_path: "Path | None" = None) -> "QBitServerProfile | None":
    meta = get_qb_cache_meta(meta_path)
    if not meta:
        return None
    profile = meta.get("qb_profile")
    if not isinstance(profile, dict):
        return None
    raw_mode = profile.get("state_alias_mode")
    state_alias_mode = str(raw_mode) if raw_mode is not None else "stop_aliases"
    if state_alias_mode == "stop_aliases":
        pause_ep = str(profile.get("pause_fallback_endpoint", "/api/v2/torrents/stop") or "/api/v2/torrents/stop")
        pause_fb = str(profile.get("pause_endpoint", "/api/v2/torrents/pause") or "/api/v2/torrents/pause")
        resume_ep = str(profile.get("resume_fallback_endpoint", "/api/v2/torrents/start") or "/api/v2/torrents/start")
        resume_fb = str(profile.get("resume_endpoint", "/api/v2/torrents/resume") or "/api/v2/torrents/resume")
    else:
        pause_ep = str(profile.get("pause_endpoint", "/api/v2/torrents/pause") or "/api/v2/torrents/pause")
        pause_fb = str(profile.get("pause_fallback_endpoint", "/api/v2/torrents/stop") or "/api/v2/torrents/stop")
        resume_ep = str(profile.get("resume_endpoint", "/api/v2/torrents/resume") or "/api/v2/torrents/resume")
        resume_fb = str(profile.get("resume_fallback_endpoint", "/api/v2/torrents/start") or "/api/v2/torrents/start")
    return QBitServerProfile(
        app_version=str(profile.get("app_version", "") or ""),
        webapi_version=str(profile.get("webapi_version", "") or ""),
        qt_version=str(profile.get("qt_version", "") or ""),
        libtorrent_version=str(profile.get("libtorrent_version", "") or ""),
        state_alias_mode=state_alias_mode,
        pause_endpoint=pause_ep,
        pause_fallback_endpoint=pause_fb,
        resume_endpoint=resume_ep,
        resume_fallback_endpoint=resume_fb,
    )


def _match_payload_filters(
    payload: Dict[str, Any],
    *,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    hashes: Optional[Iterable[str]] = None,
) -> bool:
    if category is not None and str(payload.get("category", "") or "") != str(category):
        return False
    if tag is not None:
        tags = {item.strip() for item in str(payload.get("tags", "") or "").split(",") if item.strip()}
        if str(tag) not in tags:
            return False
    if hashes is not None:
        allowed = {str(h or "").strip().lower() for h in hashes if str(h or "").strip()}
        if str(payload.get("hash", "") or "").strip().lower() not in allowed:
            return False
    return True


@dataclass
class QBitTorrent:
    """Represents a torrent from qBittorrent."""
    hash: str
    name: str
    save_path: str
    content_path: str
    category: str
    tags: str
    state: str
    size: int
    progress: float
    auto_tmm: bool = False
    amount_left: int = 0
    completed: int = 0
    downloaded: int = 0
    completion_on: int = 0
    added_on: int = 0
    state_raw: str = ""


@dataclass
class QBitServerProfile:
    """Compatibility profile for the connected qB server."""

    app_version: str = ""
    webapi_version: str = ""
    qt_version: str = ""
    libtorrent_version: str = ""
    state_alias_mode: str = "stop_aliases"
    pause_endpoint: str = "/api/v2/torrents/pause"
    pause_fallback_endpoint: str = "/api/v2/torrents/stop"
    resume_endpoint: str = "/api/v2/torrents/resume"
    resume_fallback_endpoint: str = "/api/v2/torrents/start"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QBitFile:
    """Represents a file within a torrent."""
    name: str  # Relative path within torrent
    size: int


class QBittorrentClient:
    """
    qBittorrent Web API client (read-only operations).

    Attributes:
        base_url: qBittorrent Web UI URL
        username: Username for authentication
        password: Password for authentication
        session: Requests session with authentication cookie
    """

    def __init__(self, base_url: str = "http://localhost:9003",
                 username: str = "admin", password: str = "adminpass"):
        """
        Initialize qBittorrent client.

        Args:
            base_url: qBittorrent Web UI URL (default: http://localhost:9003)
            username: Username (default: admin)
            password: Password (default: adminpass)
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._authenticated = False
        self.last_error: Optional[str] = None
        self.root_path_files_fallback_calls = 0
        self._auth_cooldown_until = 0.0
        try:
            self.request_timeout = float(os.getenv("HASHALL_QB_HTTP_TIMEOUT", "20"))
        except ValueError:
            self.request_timeout = 20.0
        try:
            self.request_retries = max(1, int(os.getenv("HASHALL_QB_HTTP_RETRIES", "3")))
        except ValueError:
            self.request_retries = 3
        try:
            self.retry_backoff_base = max(
                0.1, float(os.getenv("HASHALL_QB_RETRY_BASE_SECONDS", "0.5"))
            )
        except ValueError:
            self.retry_backoff_base = 0.5
        try:
            self.retry_backoff_cap = max(
                self.retry_backoff_base,
                float(os.getenv("HASHALL_QB_RETRY_MAX_SECONDS", "8")),
            )
        except ValueError:
            self.retry_backoff_cap = 8.0
        try:
            self.auth_cooldown_seconds = max(
                1.0, float(os.getenv("HASHALL_QB_AUTH_COOLDOWN_SECONDS", "30"))
            )
        except ValueError:
            self.auth_cooldown_seconds = 30.0
        self.debug_http = os.getenv("HASHALL_REHOME_QB_DEBUG", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.retryable_http_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        self._server_profile: Optional[QBitServerProfile] = None
        self.cache_file = Path(
            os.getenv("HASHALL_QB_CACHE_FILE", str(DEFAULT_QB_CACHE_FILE))
        ).expanduser()
        self.cache_meta_file = Path(
            os.getenv("HASHALL_QB_CACHE_META_FILE", str(DEFAULT_QB_CACHE_META_FILE))
        ).expanduser()
        self.bt_backup_dir = Path(
            os.getenv("HASHALL_QB_BT_BACKUP_DIR", str(DEFAULT_QB_BT_BACKUP_DIR))
        ).expanduser()

    @staticmethod
    def _is_transport_reset_error(error: BaseException) -> bool:
        text = str(error or "").lower()
        if isinstance(error, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return True
        if isinstance(error, RequestsConnectionError):
            return any(
                token in text
                for token in (
                    "connection reset by peer",
                    "remote end closed connection without response",
                    "remote disconnected",
                    "connection aborted",
                    "connection refused",
                )
            )
        return any(
            token in text
            for token in (
                "connection reset by peer",
                "remote end closed connection without response",
                "remote disconnected",
                "connection aborted",
            )
        )

    def _activate_auth_cooldown(self, reason: str) -> None:
        remaining = max(self.auth_cooldown_seconds, 1.0)
        self._auth_cooldown_until = time.monotonic() + remaining
        self._authenticated = False
        self.last_error = f"transport_cooldown_active:{reason}"

    def _auth_cooldown_remaining(self) -> float:
        return max(0.0, self._auth_cooldown_until - time.monotonic())

    @staticmethod
    def normalize_state_alias(state: str) -> str:
        """Normalize old/new qB pause-state aliases to one canonical form."""
        raw = str(state or "").strip()
        lowered = raw.lower()
        aliases = {
            "pauseddl": "stoppedDL",
            "stoppeddl": "stoppedDL",
            "pausedup": "stoppedUP",
            "stoppedup": "stoppedUP",
        }
        normalized = aliases.get(lowered)
        if normalized:
            return normalized
        return raw

    def _normalize_torrent_payload(self, torrent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return a compatibility-normalized torrent payload dict."""
        payload = dict(torrent_data or {})
        raw_state = str(payload.get("state_raw", payload.get("state", "")) or "").strip()
        payload["state_raw"] = raw_state
        payload["state"] = self.normalize_state_alias(raw_state)
        payload["hash"] = str(payload.get("hash", "") or "")
        payload["name"] = str(payload.get("name", "") or "")
        payload["save_path"] = str(payload.get("save_path", "") or "")
        content_path = str(payload.get("content_path", "") or "")
        if not content_path and payload["save_path"] and payload["name"]:
            content_path = str(Path(payload["save_path"]) / payload["name"])
        payload["content_path"] = content_path
        payload["category"] = str(payload.get("category", "") or "")
        payload["tags"] = str(payload.get("tags", "") or "")
        payload["size"] = int(payload.get("size", 0) or 0)
        payload["progress"] = float(payload.get("progress", 0.0) or 0.0)
        payload["auto_tmm"] = bool(payload.get("auto_tmm", False))
        payload["amount_left"] = int(payload.get("amount_left", 0) or 0)
        payload["completed"] = int(payload.get("completed", 0) or 0)
        payload["downloaded"] = int(payload.get("downloaded", 0) or 0)
        payload["completion_on"] = int(payload.get("completion_on", 0) or 0)
        payload["added_on"] = int(payload.get("added_on", 0) or 0)
        payload["tracker"] = str(payload.get("tracker", "") or "")
        payload["trackers_count"] = int(payload.get("trackers_count", 0) or 0)
        return payload

    def _fastresume_path(self, torrent_hash: str) -> Path:
        return self.bt_backup_dir / f"{str(torrent_hash or '').strip().lower()}.fastresume"

    def enrich_torrent_payload_with_trackers(self, torrent_data: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._normalize_torrent_payload(torrent_data)
        tracker_urls = _tracker_urls_from_magnet_uri(str(payload.get("magnet_uri", "") or ""))
        source = "magnet_uri" if tracker_urls else "none"
        expected_count = int(payload.get("trackers_count", 0) or 0)

        if not tracker_urls or (expected_count > 0 and len(tracker_urls) < expected_count):
            fastresume_urls = _tracker_urls_from_fastresume(self._fastresume_path(payload.get("hash", "")))
            if len(fastresume_urls) > len(tracker_urls):
                tracker_urls = fastresume_urls
                source = "fastresume"

        tracker_field = str(payload.get("tracker", "") or "").strip()
        if tracker_field and tracker_field not in tracker_urls:
            tracker_urls = _dedupe_preserve_order([tracker_field, *tracker_urls])
            if source == "none":
                source = "tracker_field"

        tracker_urls_http = _http_tracker_urls(tracker_urls)
        primary_tracker = tracker_field or (tracker_urls_http[0] if tracker_urls_http else (tracker_urls[0] if tracker_urls else ""))
        payload["tracker_urls"] = tracker_urls
        payload["tracker_urls_http"] = tracker_urls_http
        payload["primary_tracker"] = primary_tracker
        payload["trackers_count"] = expected_count if expected_count > 0 else len(tracker_urls)
        payload["real_trackers_count"] = len(tracker_urls)
        payload["tracker_domains"] = _tracker_domains(tracker_urls)
        payload["tracker_enrichment_source"] = source
        return payload

    def enrich_torrents_payload_with_trackers(
        self,
        torrents_data: Iterable[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        enriched: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        fallback_rows = 0
        for row in torrents_data:
            payload = self.enrich_torrent_payload_with_trackers(row)
            enriched.append(payload)
            source = str(payload.get("tracker_enrichment_source", "none") or "none")
            source_counts[source] = source_counts.get(source, 0) + 1
            if source != "magnet_uri":
                fallback_rows += 1
        summary = {
            "sources": source_counts,
            "fallback_rows": fallback_rows,
            "mode": "magnet_uri_with_fastresume_fallback",
        }
        return enriched, summary

    def _cached_payloads(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        hashes: Optional[Iterable[str]] = None,
        max_age_s: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        age = self.request_timeout if max_age_s is None else max_age_s
        cached = get_torrents_from_cache(max_age_s=age, cache_path=self.cache_file) or []
        out: List[Dict[str, Any]] = []
        for raw in cached:
            if not isinstance(raw, dict):
                continue
            payload = self._normalize_torrent_payload(raw)
            if _match_payload_filters(payload, category=category, tag=tag, hashes=hashes):
                out.append(payload)
        return out

    def _torrent_from_payload(self, torrent_data: Dict[str, Any]) -> QBitTorrent:
        payload = self._normalize_torrent_payload(torrent_data)
        return QBitTorrent(
            hash=payload.get("hash", ""),
            name=payload.get("name", ""),
            save_path=payload.get("save_path", ""),
            content_path=payload.get("content_path", ""),
            category=payload.get("category", ""),
            tags=payload.get("tags", ""),
            state=payload.get("state", ""),
            size=payload.get("size", 0),
            progress=payload.get("progress", 0.0),
            auto_tmm=bool(payload.get("auto_tmm", False)),
            amount_left=payload.get("amount_left", 0),
            completed=payload.get("completed", 0),
            downloaded=payload.get("downloaded", 0),
            completion_on=payload.get("completion_on", 0),
            added_on=payload.get("added_on", 0),
            state_raw=payload.get("state_raw", ""),
        )

    def _retry_delay_seconds(self, attempt: int) -> float:
        """Exponential backoff delay for retry attempts."""
        exp = max(0, attempt - 1)
        return min(self.retry_backoff_cap, self.retry_backoff_base * (2 ** exp))

    def _status_from_error(self, error: requests.HTTPError, response: Optional[requests.Response]) -> Optional[int]:
        if error.response is not None:
            return error.response.status_code
        if response is not None and hasattr(response, "status_code"):
            status = getattr(response, "status_code")
            if isinstance(status, int):
                return status
        return None

    def _response_body_snippet(self, response: Optional[requests.Response], limit: int = 200) -> str:
        if response is None:
            return ""
        try:
            text = (response.text or "").strip()
        except Exception:
            return ""
        if not text:
            return ""
        return text[:limit]

    def login(self) -> bool:
        """
        Authenticate with qBittorrent.

        Returns:
            True if authentication successful, False otherwise
        """
        cooldown_remaining = self._auth_cooldown_remaining()
        if cooldown_remaining > 0:
            self.last_error = (
                "transport_cooldown_active:"
                f"retry_in_s={cooldown_remaining:.1f}"
            )
            return False
        last_exception: Optional[requests.RequestException] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}/api/v2/auth/login",
                    data={"username": self.username, "password": self.password},
                    timeout=self.request_timeout,
                )
                # Success: 200 with "Ok." or empty body (v5+), or 204 No Content
                if response.status_code in (200, 204):
                    if response.status_code == 200 and response.text.strip() not in {"Ok.", ""}:
                        self.last_error = f"login failed: {response.text}"
                        self._authenticated = False
                        return False
                    self._authenticated = True
                    self.last_error = None
                    return True
                self.last_error = f"login failed: {response.status_code} {response.text}"
                self._authenticated = False
                return False
            except requests.RequestException as e:
                last_exception = e
                if self._is_transport_reset_error(e):
                    self.last_error = f"transport_reset:{e}"
                else:
                    self.last_error = str(e)
                self._authenticated = False
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                if self._is_transport_reset_error(e):
                    self._activate_auth_cooldown(str(e))
                    print(f"⚠️ qBittorrent transport reset during login: {e}")
                else:
                    print(f"⚠️ qBittorrent login failed: {e}")
                return False
        if last_exception is not None:
            if self._is_transport_reset_error(last_exception):
                self._activate_auth_cooldown(str(last_exception))
                print(f"⚠️ qBittorrent transport reset during login: {last_exception}")
            else:
                self.last_error = str(last_exception)
                print(f"⚠️ qBittorrent login failed: {last_exception}")
        return False

    def is_reachable(self) -> bool:
        """
        Check whether the qB API is reachable and authenticated.

        Returns:
            True if the API answers successfully, False otherwise.
        """
        response: Optional[requests.Response] = None
        try:
            if not self._authenticated:
                return self.login()
            response = self.session.get(
                f"{self.base_url}/api/v2/app/version",
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            self.last_error = None
            return True
        except requests.HTTPError as e:
            status = self._status_from_error(e, response)
            if status in {401, 403}:
                self._authenticated = False
                return self.login()
            self.last_error = f"HTTP {status}" if status is not None else str(e)
            return False
        except (requests.RequestException, RuntimeError) as e:
            self.last_error = str(e)
            return False

    def _get_optional_json(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Fetch an optional JSON endpoint, returning None on 404/auth-neutral absence."""
        response: Optional[requests.Response] = None
        try:
            self._ensure_authenticated()
            response = self.session.get(
                f"{self.base_url}{endpoint}",
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return None
        except requests.HTTPError as e:
            status = self._status_from_error(e, response)
            if status in {401, 403}:
                self._authenticated = False
                self._ensure_authenticated()
                return self._get_optional_json(endpoint)
            if status == 404:
                return None
            return None
        except requests.RequestException:
            return None

    def _get_optional_text(self, endpoint: str) -> Optional[str]:
        """Fetch an optional text endpoint, returning None on 404/auth-neutral absence."""
        response: Optional[requests.Response] = None
        try:
            self._ensure_authenticated()
            response = self.session.get(
                f"{self.base_url}{endpoint}",
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            text = (response.text or "").strip()
            return text or None
        except requests.HTTPError as e:
            status = self._status_from_error(e, response)
            if status in {401, 403}:
                self._authenticated = False
                self._ensure_authenticated()
                return self._get_optional_text(endpoint)
            if status == 404:
                return None
            return None
        except requests.RequestException:
            return None

    def get_server_profile(self, force_refresh: bool = False) -> QBitServerProfile:
        """Return a cached qB server/API compatibility profile."""
        if self._server_profile is not None and not force_refresh:
            return self._server_profile

        app_version = self._get_optional_text("/api/v2/app/version") or ""
        webapi_version = self._get_optional_text("/api/v2/app/webapiVersion") or ""
        build_info = self._get_optional_json("/api/v2/app/buildInfo") or {}

        # Detect state_alias_mode from app_version: v5+ uses stop aliases
        state_alias_mode = "stop_aliases" if app_version.startswith("v5") else ""

        profile = QBitServerProfile(
            app_version=app_version,
            webapi_version=webapi_version,
            qt_version=str(build_info.get("qt", "") or build_info.get("qt_version", "") or ""),
            libtorrent_version=str(
                build_info.get("libtorrent")
                or build_info.get("libtorrent_version")
                or ""
            ),
            state_alias_mode=state_alias_mode,
            pause_endpoint="/api/v2/torrents/stop" if state_alias_mode == "stop_aliases" else "/api/v2/torrents/pause",
            pause_fallback_endpoint="/api/v2/torrents/pause" if state_alias_mode == "stop_aliases" else "/api/v2/torrents/stop",
            resume_endpoint="/api/v2/torrents/start" if state_alias_mode == "stop_aliases" else "/api/v2/torrents/resume",
            resume_fallback_endpoint="/api/v2/torrents/resume" if state_alias_mode == "stop_aliases" else "/api/v2/torrents/start",
        )
        if not any((
            profile.app_version,
            profile.webapi_version,
            profile.qt_version,
            profile.libtorrent_version,
        )):
            cached_profile = get_qb_cached_server_profile(self.cache_meta_file)
            if cached_profile is not None:
                self._server_profile = cached_profile
                self.last_error = self.last_error or "using_cached_qb_profile"
                return cached_profile
        self._server_profile = profile
        return profile

    def _ensure_authenticated(self):
        """Ensure we're authenticated before making requests."""
        if not self._authenticated:
            if not self.login():
                raise RuntimeError(self.last_error or "Failed to authenticate with qBittorrent")

    def get_torrents_payload(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch normalized raw torrent payloads from qB.

        Proactively uses cache if fresh (< 30s), otherwise hits live API.
        Falls back to stale cache on API failures.
        """
        # Proactively check if cache is fresh enough
        cached_fresh = self._cached_payloads(
            category=category, tag=tag, max_age_s=30.0
        )
        if cached_fresh:
            self.last_error = None
            return cached_fresh

        try:
            self._ensure_authenticated()
        except RuntimeError as e:
            cached = self._cached_payloads(category=category, tag=tag)
            if cached:
                self.last_error = f"cache_fallback_auth:{e}"
                return cached
            raise

        params = {}
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v2/torrents/info",
                    params=params,
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                torrents_data = response.json()
                normalized = [
                    self._normalize_torrent_payload(torrent_data)
                    for torrent_data in torrents_data
                ]
                self.last_error = None
                return normalized
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB torrents/info timeout attempt={attempt}/{self.request_retries} "
                        f"retry_in_s={delay:.1f} timeout_s={self.request_timeout}: {e}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(category=category, tag=tag)
                if cached:
                    self.last_error = f"cache_fallback:{e}"
                    return cached
                print(f"⚠️ Failed to get torrents: {e}")
                return []
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB torrents/info HTTP {status} attempt={attempt}/{self.request_retries} "
                        f"retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(category=category, tag=tag)
                if cached:
                    self.last_error = f"cache_fallback_http:{status}"
                    return cached
                print(f"⚠️ Failed to get torrents: {e}")
                return []
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    if self.debug_http:
                        print(
                            f"⚠️ qB torrents/info retry attempt={attempt}/{self.request_retries} "
                            f"retry_in_s={delay:.1f} error={e}"
                        )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(category=category, tag=tag)
                if cached:
                    self.last_error = f"cache_fallback:{e}"
                    return cached
                print(f"⚠️ Failed to get torrents: {e}")
                return []
        return []

    def get_torrents(self, category: Optional[str] = None,
                    tag: Optional[str] = None) -> List[QBitTorrent]:
        """
        Get list of torrents from qBittorrent.

        Args:
            category: Filter by category (optional)
            tag: Filter by tag (optional)

        Returns:
            List of QBitTorrent objects
        """
        payloads = self.get_torrents_payload(category=category, tag=tag)
        return [self._torrent_from_payload(torrent_data) for torrent_data in payloads]

    def get_torrent_files(self, torrent_hash: str) -> List[QBitFile]:
        """
        Get file list for a specific torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            List of QBitFile objects
        """
        self._ensure_authenticated()

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v2/torrents/files",
                    params={"hash": torrent_hash},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                files_data = response.json()

                files = []
                for f in files_data:
                    files.append(QBitFile(
                        name=f.get('name', ''),
                        size=f.get('size', 0)
                    ))
                self.last_error = None
                return files

            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB files timeout hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} "
                        f"timeout_s={self.request_timeout}: {e}"
                    )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to get files for torrent {torrent_hash}: {e}")
                break
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB files HTTP {status} hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to get files for torrent {torrent_hash}: {e}")
                break
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt == self.request_retries:
                    print(f"⚠️ Failed to get files for torrent {torrent_hash}: {e}")
                    break
                delay = self._retry_delay_seconds(attempt)
                if self.debug_http:
                    print(
                        f"⚠️ qB files retry hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                    )
                time.sleep(delay)
        return []

    def export_torrent_file(self, torrent_hash: str, out_path: Optional[Path] = None) -> Optional[bytes]:
        """
        Export a .torrent file from qBittorrent by hash.

        Args:
            torrent_hash: Torrent infohash.
            out_path: Optional path to write exported bytes.

        Returns:
            Raw torrent bytes on success, otherwise None.
        """
        backup_torrent = self.bt_backup_dir / f"{str(torrent_hash or '').strip().lower()}.torrent"
        try:
            self._ensure_authenticated()
        except RuntimeError:
            if backup_torrent.exists():
                blob = backup_torrent.read_bytes()
                if out_path is not None:
                    target = Path(out_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_torrent, target)
                self.last_error = None
                return blob
            raise

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v2/torrents/export",
                    params={"hash": str(torrent_hash or "").strip()},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                blob = response.content or b""
                if not blob:
                    self.last_error = "empty_export_payload"
                    return None
                if out_path is not None:
                    target = Path(out_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
                self.last_error = None
                return blob
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB export timeout hash={str(torrent_hash)[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                if backup_torrent.exists():
                    blob = backup_torrent.read_bytes()
                    if out_path is not None:
                        target = Path(out_path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_torrent, target)
                    self.last_error = None
                    return blob
                print(f"⚠️ Failed to export torrent {torrent_hash}: {e}")
                return None
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                body = self._response_body_snippet(
                    e.response if e.response is not None else response
                )
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB export retry hash={str(torrent_hash)[:16]} "
                        f"attempt={attempt + 1}/{self.request_retries} "
                        f"status={status} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                msg = (
                    f"⚠️ Failed to export torrent {torrent_hash}: "
                    f"HTTP {status if status is not None else '?'}"
                )
                if body:
                    msg += f" body={body}"
                if backup_torrent.exists():
                    blob = backup_torrent.read_bytes()
                    if out_path is not None:
                        target = Path(out_path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_torrent, target)
                    self.last_error = None
                    return blob
                print(msg)
                return None
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    if self.debug_http:
                        print(
                            f"⚠️ qB export retry hash={str(torrent_hash)[:16]} "
                            f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                        )
                    time.sleep(delay)
                    continue
                if backup_torrent.exists():
                    blob = backup_torrent.read_bytes()
                    if out_path is not None:
                        target = Path(out_path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_torrent, target)
                    self.last_error = None
                    return blob
                print(f"⚠️ Failed to export torrent {torrent_hash}: {e}")
                return None
        return None

    def add_torrent_file(
        self,
        torrent_file: Path,
        *,
        save_path: str,
        category: str = "",
        tags: Optional[Iterable[str]] = None,
        stopped: bool = True,
        skip_checking: bool = False,
    ) -> bool:
        """
        Add a local .torrent file to qBittorrent.

        The caller owns all safety decisions. This helper only performs the Web API
        mutation and keeps the torrent stopped by default for mirror imports.
        """
        torrent_path = Path(torrent_file)
        if not torrent_path.exists():
            self.last_error = f"torrent_file_missing:{torrent_path}"
            return False
        self._ensure_authenticated()

        clean_tags = sorted({str(tag or "").strip() for tag in (tags or []) if str(tag or "").strip()})
        data = {
            "savepath": str(save_path),
            "category": str(category or ""),
            "tags": ",".join(clean_tags),
            "autoTMM": "false",
            "paused": "true" if stopped else "false",
            "stopped": "true" if stopped else "false",
            "skip_checking": "true" if skip_checking else "false",
        }
        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                with torrent_path.open("rb") as handle:
                    response = self.session.post(
                        f"{self.base_url}/api/v2/torrents/add",
                        data=data,
                        files={"torrents": (torrent_path.name, handle, "application/x-bittorrent")},
                        timeout=self.request_timeout,
                    )
                response.raise_for_status()
                body = self._response_body_snippet(response)
                if body and body.lower().startswith("fails"):
                    self.last_error = body
                    return False
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add torrent file {torrent_path}: {e}")
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                body = self._response_body_snippet(
                    e.response if e.response is not None else response
                )
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if body:
                    self.last_error += f":{body}"
                if status in self.retryable_http_statuses and attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add torrent file {torrent_path}: {self.last_error}")
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add torrent file {torrent_path}: {e}")
                return False
        return False

    def get_torrents_by_hashes(self, torrent_hashes: List[str]) -> Dict[str, QBitTorrent]:
        """
        Fetch torrent info for a specific set of hashes in one API request.

        Args:
            torrent_hashes: Iterable of infohash strings

        Returns:
            Mapping of lowercased hash -> QBitTorrent
        """
        self._ensure_authenticated()
        clean_hashes = sorted({str(h or "").strip().lower() for h in torrent_hashes if str(h or "").strip()})
        if not clean_hashes:
            return {}

        response: Optional[requests.Response] = None
        hashes_arg = "|".join(clean_hashes)
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v2/torrents/info",
                    params={"hashes": hashes_arg},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                torrents_data = response.json()
                out: Dict[str, QBitTorrent] = {}
                for t in torrents_data:
                    payload = self._normalize_torrent_payload(t)
                    h = str(payload.get("hash", "") or "").lower().strip()
                    if not h:
                        continue
                    out[h] = self._torrent_from_payload(payload)
                self.last_error = None
                return out
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB info batch timeout hashes={len(clean_hashes)} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} "
                        f"timeout_s={self.request_timeout}: {e}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(hashes=clean_hashes)
                if cached:
                    self.last_error = f"cache_fallback:{e}"
                    return {
                        str(item.get("hash", "")).lower().strip(): self._torrent_from_payload(item)
                        for item in cached
                        if str(item.get("hash", "")).strip()
                    }
                print(f"⚠️ Failed to get batch info for {len(clean_hashes)} torrents: {e}")
                return {}
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB info batch retry hashes={len(clean_hashes)} "
                        f"attempt={attempt + 1}/{self.request_retries} "
                        f"status={status} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(hashes=clean_hashes)
                if cached:
                    self.last_error = f"cache_fallback_http:{status}"
                    return {
                        str(item.get("hash", "")).lower().strip(): self._torrent_from_payload(item)
                        for item in cached
                        if str(item.get("hash", "")).strip()
                    }
                print(f"⚠️ Failed to get batch info for {len(clean_hashes)} torrents: {e}")
                return {}
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    if self.debug_http:
                        print(
                            f"⚠️ qB info batch retry hashes={len(clean_hashes)} "
                            f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                        )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(hashes=clean_hashes)
                if cached:
                    self.last_error = f"cache_fallback:{e}"
                    return {
                        str(item.get("hash", "")).lower().strip(): self._torrent_from_payload(item)
                        for item in cached
                        if str(item.get("hash", "")).strip()
                    }
                print(f"⚠️ Failed to get batch info for {len(clean_hashes)} torrents: {e}")
                return {}
        return {}

    def get_torrent_root_path(self, torrent: QBitTorrent,
                             files: Optional[List[QBitFile]] = None) -> str:
        """
        Determine the on-disk root path for a torrent's payload.

        For single-file torrents: save_path/filename
        For multi-file torrents: save_path/torrent_name/

        Args:
            torrent: QBitTorrent object
            files: Optional list of files (will fetch if not provided)

        Returns:
            Absolute path to payload root
        """
        if torrent.content_path:
            return str(Path(torrent.content_path))

        if files is None:
            self.root_path_files_fallback_calls += 1
            files = self.get_torrent_files(torrent.hash)

        save_path = Path(torrent.save_path)

        # Check if single-file or multi-file torrent
        if len(files) == 1:
            # Single-file torrent: save_path/filename
            return str(save_path / files[0].name)
        else:
            # Multi-file torrent: save_path/torrent_name/
            return str(save_path / torrent.name)

    def _normalize_hashes(self, torrent_hashes: List[str]) -> List[str]:
        """Normalize and deduplicate hashes while preserving order."""
        out: List[str] = []
        seen = set()
        for raw in torrent_hashes:
            h = str(raw or "").strip()
            if not h or h in seen:
                continue
            seen.add(h)
            out.append(h)
        return out

    def _post_hashes_action(
        self,
        endpoint: str,
        torrent_hashes: List[str],
        action_name: str,
        fallback_endpoint: Optional[str] = None,
    ) -> bool:
        """POST a hashes payload to a qB endpoint with retries and optional 404 fallback."""
        hashes = self._normalize_hashes(torrent_hashes)
        if not hashes:
            return True
        self._ensure_authenticated()
        hashes_arg = "|".join(hashes)
        scope = hashes[0][:16] if len(hashes) == 1 else f"{len(hashes)} hashes"

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}{endpoint}",
                    data={"hashes": hashes_arg},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB {action_name} timeout hash={scope} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to {action_name} torrent(s) {scope}: {e}")
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                if status == 404 and fallback_endpoint:
                    try:
                        fallback = self.session.post(
                            f"{self.base_url}{fallback_endpoint}",
                            data={"hashes": hashes_arg},
                            timeout=self.request_timeout,
                        )
                        fallback.raise_for_status()
                        self.last_error = None
                        return True
                    except requests.RequestException as fallback_exc:
                        self.last_error = str(fallback_exc)
                        if attempt < self.request_retries:
                            delay = self._retry_delay_seconds(attempt)
                            print(
                                f"⚠️ qB {action_name} fallback retry hash={scope} "
                                f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f}"
                            )
                            time.sleep(delay)
                            continue
                        print(f"⚠️ Failed to {action_name} torrent(s) {scope}: {fallback_exc}")
                        return False
                body = self._response_body_snippet(
                    e.response if e.response is not None else response
                )
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB {action_name} retry hash={scope} "
                        f"attempt={attempt + 1}/{self.request_retries} "
                        f"status={status} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                msg = (
                    f"⚠️ Failed to {action_name} torrent(s) {scope}: "
                    f"HTTP {status if status is not None else '?'}"
                )
                if body:
                    msg += f" body={body}"
                print(msg)
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    if self.debug_http:
                        print(
                            f"⚠️ qB {action_name} retry hash={scope} "
                            f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                        )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to {action_name} torrent(s) {scope}: {e}")
                return False
        return False

    def pause_torrents(self, torrent_hashes: List[str]) -> bool:
        """
        Pause one or more torrents.

        Uses qBittorrent API: POST /api/v2/torrents/pause
        Falls back to /api/v2/torrents/stop on 404.
        """
        profile = self.get_server_profile()
        return self._post_hashes_action(
            endpoint=profile.pause_endpoint,
            torrent_hashes=torrent_hashes,
            action_name="pause",
            fallback_endpoint=profile.pause_fallback_endpoint,
        )

    def pause_torrent(self, torrent_hash: str) -> bool:
        """Pause a single torrent."""
        return self.pause_torrents([torrent_hash])

    def resume_torrents(self, torrent_hashes: List[str]) -> bool:
        """
        Resume one or more torrents.

        Uses qBittorrent API: POST /api/v2/torrents/resume
        Falls back to /api/v2/torrents/start on 404.
        """
        profile = self.get_server_profile()
        return self._post_hashes_action(
            endpoint=profile.resume_endpoint,
            torrent_hashes=torrent_hashes,
            action_name="resume",
            fallback_endpoint=profile.resume_fallback_endpoint,
        )

    def resume_torrent(self, torrent_hash: str) -> bool:
        """Resume a single torrent."""
        return self.resume_torrents([torrent_hash])


    def set_location(self, torrent_hash: str, new_location: str) -> bool:
        """
        Relocate a torrent to a new save path.

        Args:
            torrent_hash: Torrent infohash
            new_location: New save path (absolute path)

        Returns:
            True if successful, False otherwise

        Note:
            Follows tracker-ctl pattern from qbit_migrate_paths.sh
            Uses qBittorrent API: POST /api/v2/torrents/setLocation
            Pattern: pause → setLocation → resume
        """
        self._ensure_authenticated()

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}/api/v2/torrents/setLocation",
                    data={"hashes": torrent_hash, "location": new_location},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB setLocation timeout hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to set location for torrent {torrent_hash}: {e}")
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                body = self._response_body_snippet(
                    e.response if e.response is not None else response
                )
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB setLocation retry hash={torrent_hash[:16]} "
                        f"attempt={attempt + 1}/{self.request_retries} "
                        f"status={status} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                msg = f"⚠️ Failed to set location for torrent {torrent_hash}: HTTP {status if status is not None else '?'}"
                if body:
                    msg += f" body={body}"
                print(msg)
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    if self.debug_http:
                        print(
                            f"⚠️ qB setLocation retry hash={torrent_hash[:16]} "
                            f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                        )
                    time.sleep(delay)
                    continue
                print(f"⚠️ Failed to set location for torrent {torrent_hash}: {e}")
                return False
        return False

    def recheck_torrents(self, torrent_hashes: List[str]) -> bool:
        """
        Trigger force recheck for one or more torrents.

        Uses qBittorrent API: POST /api/v2/torrents/recheck
        """
        return self._post_hashes_action(
            endpoint="/api/v2/torrents/recheck",
            torrent_hashes=torrent_hashes,
            action_name="recheck",
        )

    def recheck_torrent(self, torrent_hash: str) -> bool:
        """Trigger force recheck for a single torrent."""
        return self.recheck_torrents([torrent_hash])

    def set_auto_management(self, torrent_hash: str, enabled: bool) -> bool:
        """
        Toggle qBittorrent Auto Torrent Management for a torrent.

        Args:
            torrent_hash: Torrent infohash
            enabled: True to enable ATM, False to disable ATM

        Returns:
            True if successful, False otherwise
        """
        self._ensure_authenticated()

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}/api/v2/torrents/setAutoManagement",
                    data={
                        "hashes": torrent_hash,
                        "enable": "true" if enabled else "false",
                    },
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(
                    "⚠️ Failed to set auto management for torrent "
                    f"{torrent_hash} to {enabled}: {e}"
                )
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(
                    "⚠️ Failed to set auto management for torrent "
                    f"{torrent_hash} to {enabled}: {e}"
                )
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(
                    "⚠️ Failed to set auto management for torrent "
                    f"{torrent_hash} to {enabled}: {e}"
                )
                return False
        return False

    def add_tags(self, torrent_hash: str, tags: List[str]) -> bool:
        """Add tags to a torrent."""
        self._ensure_authenticated()

        clean_tags = sorted({t.strip() for t in tags if t and t.strip()})
        if not clean_tags:
            return True

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}/api/v2/torrents/addTags",
                    data={"hashes": torrent_hash, "tags": ",".join(clean_tags)},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add tags for torrent {torrent_hash}: {e}")
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add tags for torrent {torrent_hash}: {e}")
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to add tags for torrent {torrent_hash}: {e}")
                return False
        return False

    def remove_tags(self, torrent_hash: str, tags: List[str]) -> bool:
        """Remove tags from a torrent."""
        self._ensure_authenticated()

        clean_tags = sorted({t.strip() for t in tags if t and t.strip()})
        if not clean_tags:
            return True

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.post(
                    f"{self.base_url}/api/v2/torrents/removeTags",
                    data={"hashes": torrent_hash, "tags": ",".join(clean_tags)},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                self.last_error = None
                return True
            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to remove tags for torrent {torrent_hash}: {e}")
                return False
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to remove tags for torrent {torrent_hash}: {e}")
                return False
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    time.sleep(self._retry_delay_seconds(attempt))
                    continue
                print(f"⚠️ Failed to remove tags for torrent {torrent_hash}: {e}")
                return False
        return False

    def get_torrent_info(self, torrent_hash: str) -> Optional[QBitTorrent]:
        """
        Get detailed info for a specific torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            QBitTorrent object or None if not found
        """
        try:
            self._ensure_authenticated()
        except RuntimeError as e:
            cached = self._cached_payloads(hashes=[torrent_hash])
            if cached:
                self.last_error = f"cache_fallback_auth:{e}"
                return self._torrent_from_payload(cached[0])
            raise

        response: Optional[requests.Response] = None
        for attempt in range(1, self.request_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/api/v2/torrents/info",
                    params={"hashes": torrent_hash},
                    timeout=self.request_timeout,
                )
                response.raise_for_status()
                torrents_data = response.json()

                if not torrents_data:
                    self.last_error = f"not_found:{torrent_hash.lower()}"
                    return None

                t = self._normalize_torrent_payload(torrents_data[0])
                self.last_error = None
                return self._torrent_from_payload(t)

            except requests.Timeout as e:
                self.last_error = str(e)
                if attempt < self.request_retries:
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB info timeout hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} "
                        f"timeout_s={self.request_timeout}: {e}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(hashes=[torrent_hash])
                if cached:
                    self.last_error = f"cache_fallback:{e}"
                    return self._torrent_from_payload(cached[0])
                print(f"⚠️ Failed to get info for torrent {torrent_hash}: {e}")
                break
            except requests.HTTPError as e:
                status = self._status_from_error(e, response)
                self.last_error = f"HTTP {status}" if status is not None else str(e)
                if (
                    status in self.retryable_http_statuses
                    and attempt < self.request_retries
                ):
                    delay = self._retry_delay_seconds(attempt)
                    print(
                        f"⚠️ qB info retry hash={torrent_hash[:16]} "
                        f"attempt={attempt + 1}/{self.request_retries} "
                        f"status={status} retry_in_s={delay:.1f}"
                    )
                    time.sleep(delay)
                    continue
                cached = self._cached_payloads(hashes=[torrent_hash])
                if cached:
                    self.last_error = f"cache_fallback_http:{status}"
                    return self._torrent_from_payload(cached[0])
                print(f"⚠️ Failed to get info for torrent {torrent_hash}: {e}")
                break
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt == self.request_retries:
                    cached = self._cached_payloads(hashes=[torrent_hash])
                    if cached:
                        self.last_error = f"cache_fallback:{e}"
                        return self._torrent_from_payload(cached[0])
                    print(f"⚠️ Failed to get info for torrent {torrent_hash}: {e}")
                    break
                delay = self._retry_delay_seconds(attempt)
                if self.debug_http:
                    print(
                        f"⚠️ qB info retry hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} retry_in_s={delay:.1f} error={e}"
                    )
                time.sleep(delay)
        return None

    def test_connection(self) -> bool:
        """
        Test connection to qBittorrent.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            ok = self.is_reachable()
            if ok:
                self.last_error = None
            return ok
        except (requests.RequestException, RuntimeError) as e:
            self.last_error = str(e)
            return False
def get_qbittorrent_client(base_url: Optional[str] = None,
                          username: Optional[str] = None,
                          password: Optional[str] = None) -> QBittorrentClient:
    """
    Factory function to create qBittorrent client with environment/config defaults.

    Args:
        base_url: qBittorrent URL (default from env or http://localhost:8080)
        username: Username (default from env or 'admin')
        password: Password (default from env or 'adminpass')

    Returns:
        QBittorrentClient instance
    """
    def _parse_env_file(path: Path) -> dict:
        data = {}
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            return {}
        return data

    def _find_credentials_file() -> Optional[Path]:
        env_path = os.getenv("QBITTORRENT_CREDENTIALS_FILE")
        if env_path:
            return Path(env_path)
        candidates = [
            Path("/mnt/config/secrets/qbittorrent/api.env"),
            Path("/home/michael/dev/secrets/qbittorrent/api.env"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _get_env(*names: str) -> Optional[str]:
        for name in names:
            value = os.getenv(name)
            if value:
                return value
        return None

    base_url = base_url or _get_env(
        "QBITTORRENT_API_URL",
        "QBITTORRENT_URL",
        "QBITTORRENT_HOST",
        "QBITTORRENTAPI_HOST",
    ) or "http://localhost:9003"

    if base_url and "://" not in base_url:
        base_url = f"http://{base_url}"

    if not username or not password:
        env_user = _get_env("QBITTORRENTAPI_USERNAME", "QBITTORRENT_USERNAME", "QBITTORRENT_USER")
        env_pass = _get_env("QBITTORRENTAPI_PASSWORD", "QBITTORRENT_PASSWORD", "QBITTORRENT_PASS")
        if env_user and env_pass:
            username = username or env_user
            password = password or env_pass
        else:
            creds_file = _find_credentials_file()
            if creds_file:
                data = _parse_env_file(creds_file)
                username = username or data.get("QBITTORRENTAPI_USERNAME") or data.get("QBITTORRENT_USERNAME")
                password = password or data.get("QBITTORRENTAPI_PASSWORD") or data.get("QBITTORRENT_PASSWORD")

    username = username or "admin"
    password = password or "adminpass"

    return QBittorrentClient(base_url, username, password)
