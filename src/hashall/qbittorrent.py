"""
qBittorrent Web API integration (read-only).

Connects to qBittorrent to retrieve torrent information for payload mapping.
"""

import os
import requests
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path


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
        try:
            self.request_timeout = float(os.getenv("HASHALL_QB_HTTP_TIMEOUT", "20"))
        except ValueError:
            self.request_timeout = 20.0
        try:
            self.request_retries = max(1, int(os.getenv("HASHALL_QB_HTTP_RETRIES", "3")))
        except ValueError:
            self.request_retries = 3
        self.debug_http = os.getenv("HASHALL_REHOME_QB_DEBUG", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }

    def login(self) -> bool:
        """
        Authenticate with qBittorrent.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=self.request_timeout,
            )
            if response.text == "Ok.":
                self._authenticated = True
                self.last_error = None
                return True
            self.last_error = f"login failed: {response.text}"
            return False
        except requests.RequestException as e:
            self.last_error = str(e)
            print(f"⚠️ qBittorrent login failed: {e}")
            return False

    def _ensure_authenticated(self):
        """Ensure we're authenticated before making requests."""
        if not self._authenticated:
            if not self.login():
                raise RuntimeError("Failed to authenticate with qBittorrent")

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
        self._ensure_authenticated()

        params = {}
        if category:
            params['category'] = category
        if tag:
            params['tag'] = tag

        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/info",
                params=params,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            torrents_data = response.json()

            torrents = []
            for t in torrents_data:
                torrents.append(QBitTorrent(
                    hash=t.get('hash', ''),
                    name=t.get('name', ''),
                    save_path=t.get('save_path', ''),
                    content_path=t.get('content_path', ''),
                    category=t.get('category', ''),
                    tags=t.get('tags', ''),
                    state=t.get('state', ''),
                    size=t.get('size', 0),
                    progress=t.get('progress', 0.0),
                    auto_tmm=bool(t.get('auto_tmm', False)),
                ))

            return torrents

        except requests.RequestException as e:
            print(f"⚠️ Failed to get torrents: {e}")
            return []

    def get_torrent_files(self, torrent_hash: str) -> List[QBitFile]:
        """
        Get file list for a specific torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            List of QBitFile objects
        """
        self._ensure_authenticated()

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
                return files

            except requests.Timeout as e:
                print(
                    f"⚠️ qB files timeout hash={torrent_hash[:16]} "
                    f"attempt={attempt}/{self.request_retries} timeout_s={self.request_timeout}: {e}"
                )
            except requests.RequestException as e:
                if attempt == self.request_retries:
                    print(f"⚠️ Failed to get files for torrent {torrent_hash}: {e}")
                    break
                if self.debug_http:
                    print(
                        f"⚠️ qB files retry hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} error={e}"
                    )
            if attempt < self.request_retries:
                time.sleep(min(0.5 * attempt, 2.0))
        return []

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

    def pause_torrent(self, torrent_hash: str) -> bool:
        """
        Pause a torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            True if successful, False otherwise

        Note:
            Follows tracker-ctl pattern from qbit_migrate_paths.sh
            Uses qBittorrent API: POST /api/v2/torrents/pause
        """
        self._ensure_authenticated()

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/pause",
                data={"hashes": torrent_hash},
                timeout=self.request_timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError:
                if response.status_code != 404:
                    raise
                # Some qB builds expose stop/start instead of pause/resume.
                fallback = self.session.post(
                    f"{self.base_url}/api/v2/torrents/stop",
                    data={"hashes": torrent_hash},
                    timeout=self.request_timeout,
                )
                fallback.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"⚠️ Failed to pause torrent {torrent_hash}: {e}")
            return False

    def resume_torrent(self, torrent_hash: str) -> bool:
        """
        Resume a paused torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            True if successful, False otherwise

        Note:
            Follows tracker-ctl pattern from qbit_migrate_paths.sh
            Uses qBittorrent API: POST /api/v2/torrents/resume
        """
        self._ensure_authenticated()

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/resume",
                data={"hashes": torrent_hash},
                timeout=self.request_timeout,
            )
            try:
                response.raise_for_status()
            except requests.HTTPError:
                if response.status_code != 404:
                    raise
                # Some qB builds expose stop/start instead of pause/resume.
                fallback = self.session.post(
                    f"{self.base_url}/api/v2/torrents/start",
                    data={"hashes": torrent_hash},
                    timeout=self.request_timeout,
                )
                fallback.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"⚠️ Failed to resume torrent {torrent_hash}: {e}")
            return False


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

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/setLocation",
                data={"hashes": torrent_hash, "location": new_location},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            return True
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            body = ""
            if e.response is not None:
                try:
                    body = e.response.text.strip()
                except Exception:
                    body = ""
            body = body[:200] if body else ""
            msg = f"⚠️ Failed to set location for torrent {torrent_hash}: HTTP {status}"
            if body:
                msg += f" body={body}"
            print(msg)
            return False
        except requests.RequestException as e:
            print(f"⚠️ Failed to set location for torrent {torrent_hash}: {e}")
            return False

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
            return True
        except requests.RequestException as e:
            print(
                "⚠️ Failed to set auto management for torrent "
                f"{torrent_hash} to {enabled}: {e}"
            )
            return False

    def add_tags(self, torrent_hash: str, tags: List[str]) -> bool:
        """Add tags to a torrent."""
        self._ensure_authenticated()

        clean_tags = sorted({t.strip() for t in tags if t and t.strip()})
        if not clean_tags:
            return True

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/addTags",
                data={"hashes": torrent_hash, "tags": ",".join(clean_tags)},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"⚠️ Failed to add tags for torrent {torrent_hash}: {e}")
            return False

    def remove_tags(self, torrent_hash: str, tags: List[str]) -> bool:
        """Remove tags from a torrent."""
        self._ensure_authenticated()

        clean_tags = sorted({t.strip() for t in tags if t and t.strip()})
        if not clean_tags:
            return True

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/removeTags",
                data={"hashes": torrent_hash, "tags": ",".join(clean_tags)},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"⚠️ Failed to remove tags for torrent {torrent_hash}: {e}")
            return False

    def get_torrent_info(self, torrent_hash: str) -> Optional[QBitTorrent]:
        """
        Get detailed info for a specific torrent.

        Args:
            torrent_hash: Torrent infohash

        Returns:
            QBitTorrent object or None if not found
        """
        self._ensure_authenticated()

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

                t = torrents_data[0]
                self.last_error = None
                return QBitTorrent(
                    hash=t.get('hash', ''),
                    name=t.get('name', ''),
                    save_path=t.get('save_path', ''),
                    content_path=t.get('content_path', ''),
                    category=t.get('category', ''),
                    tags=t.get('tags', ''),
                    state=t.get('state', ''),
                    size=t.get('size', 0),
                    progress=t.get('progress', 0.0),
                    auto_tmm=bool(t.get('auto_tmm', False)),
                )

            except requests.Timeout as e:
                self.last_error = str(e)
                print(
                    f"⚠️ qB info timeout hash={torrent_hash[:16]} "
                    f"attempt={attempt}/{self.request_retries} timeout_s={self.request_timeout}: {e}"
                )
            except requests.RequestException as e:
                self.last_error = str(e)
                if attempt == self.request_retries:
                    print(f"⚠️ Failed to get info for torrent {torrent_hash}: {e}")
                    break
                if self.debug_http:
                    print(
                        f"⚠️ qB info retry hash={torrent_hash[:16]} "
                        f"attempt={attempt}/{self.request_retries} error={e}"
                    )
            if attempt < self.request_retries:
                time.sleep(min(0.5 * attempt, 2.0))
        return None

    def test_connection(self) -> bool:
        """
        Test connection to qBittorrent.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/app/version",
                timeout=5
            )
            response.raise_for_status()
            self.last_error = None
            return True
        except requests.RequestException as e:
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
