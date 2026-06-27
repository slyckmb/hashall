# Canonicalize Interface Map

> Task j46-t01 — Exact function signatures, types, and instantiation requirements
> for the three functions that will be wired into the unified canonicalize orchestrator.

---

## 1. Function Signatures

### `DemotionPlanner.__init__` — `src/rehome/planner.py:230`

```python
def __init__(
    self,
    catalog_path: Path,
    seeding_roots: List[str],
    library_roots: Optional[List[str]],
    stash_device: int,
    pool_device: int,
    stash_seeding_root: Optional[str] = None,
    pool_seeding_root: Optional[str] = None,
    pool_payload_root: Optional[str] = None,
) -> None:
```

The constructor stores all config as instance attributes then calls no further init.
After construction, `_refresh_identity_cache(conn)` must be called before using any
method that reads device identity — this is done inside `plan_demotion` but the
orchestrator should call it explicitly.

### `DemotionPlanner._refresh_identity_cache` — `src/rehome/planner.py:258`

```python
def _refresh_identity_cache(self, conn: sqlite3.Connection) -> None:
```

Populates `self.stash_fs_uuid` / `self.pool_fs_uuid` from the devices table.
Required before `_payload_exists_on_pool`.

### `DemotionPlanner._detect_external_consumers` — `src/rehome/planner.py:325`

```python
def _detect_external_consumers(
    self,
    conn: sqlite3.Connection,
    root_path: str,
) -> List[ExternalConsumer]:
```

- `conn`: open `sqlite3.Connection` to the hashall catalog (read-only queries)
- `root_path`: absolute payload root path on stash (e.g. from `Payload.root_path`)
- Returns `List[ExternalConsumer]` — empty list if no external hardlinks found

Operates on a **single** root_path (one payload). Uses catalog files tables to find
all hardlinks of each inode under the payload root, then filters for paths outside
`self.seeding_roots`.

### `DemotionPlanner._compute_pool_move_target` — `src/rehome/planner.py:270`

```python
def _compute_pool_move_target(
    self,
    source_root_path: str,
) -> tuple[Optional[str], Optional[str]]:
```

- `source_root_path`: stash-side root path (e.g. from `Payload.root_path`)
- Returns `(target_path, error_reason)` — both `None` if no target possible

Requires `self.stash_seeding_root` and `self.pool_payload_root` (or `self.pool_seeding_root`)
to be set. Preserves seeding-relative structure: computes relpath under
`stash_seeding_root`, then joins under `pool_payload_root`.

### `DemotionPlanner._payload_exists_on_pool` — `src/rehome/planner.py:665`

```python
def _payload_exists_on_pool(
    self,
    conn: sqlite3.Connection,
    payload_hash: str,
) -> Optional[str]:
```

- `conn`: open `sqlite3.Connection` to catalog
- `payload_hash`: the payload hash (string)
- Returns root path string if found on pool device, `None` otherwise

Uses `get_payloads_by_hash` with `device_id=self.pool_device` and `fs_uuid=self.pool_fs_uuid`.
Requires `_refresh_identity_cache` to have been called first.

### `infer_canonical_save_path` — `src/hashall/save_path_inference.py:338`

```python
def infer_canonical_save_path(
    category: str,
    tags: str = "",
    current_save_path: str = "",
    current_content_path: str = "",
    current_rt_directory: str = "",
    *,
    qbm_config_path: str = "/home/michael/dev/sys/docker/qbit_manage/config.yml",
) -> InferredSavePath:
```

Standalone function (no class or shared context needed). Purely derives the canonical
path from qB metadata. The `qbm_config_path` only matters when qbm config is available;
will silently degrade to alphabetical-tag fallback if the file uses `!ENV` YAML tags.

### `_placement_kind` — `src/hashall/client_drift.py:925`

```python
def _placement_kind(
    path: str,
    policy: ClientDriftPolicy,
) -> str:
```

- `path`: a save path string
- `policy`: a `ClientDriftPolicy` instance defining `pool_roots` and `stash_roots`
- Returns `"pool"`, `"stash"`, or `"other"`

---

## 2. Return Types

### `ExternalConsumer` — `src/rehome/planner.py:28`

```python
@dataclass
class ExternalConsumer:
    file_path: str
    external_link_paths: List[str]
```

### `InferredSavePath` — `src/hashall/save_path_inference.py:98`

```python
@dataclass
class InferredSavePath:
    canonical_save_path: str   # absolute path, e.g. "/data/media/torrents/seeding/tv"
    device: Literal["stash", "pool"]
    category: str              # original category name
    subdir: str                # leaf subdir, e.g. "tv", "cross-seed/torrentleech"
    reliability: Literal["reliable", "transient", "ambiguous"]
    notes: list[str] = field(default_factory=list)
```

**`canonical_save_path`** is a **full absolute path** (not relative). It is constructed
as `f"{device_root}/{subdir}"` where `device_root` is either:
- `"/data/media/torrents/seeding"` for stash
- `"/pool/media/torrents/seeding"` for pool

**`device`** is a `Literal["stash", "pool"]` — a plain string, not an int or enum.

### `_placement_kind` return values

Returns one of: `"pool"`, `"stash"`, `"other"` — plain string, checked against
`policy.pool_roots` and `policy.stash_roots` via `_under_any_policy_prefix`.

---

## 3. Shared Context Requirements

| Function | Requires DemotionPlanner instance | Requires Catalog conn | Requires ClientDriftPolicy | Device IDs / Roots |
|---|---|---|---|---|
| `DemotionPlanner.__init__` | — (creates it) | No (stores catalog_path) | No | stash_device, pool_device, seeding_roots, library_roots |
| `DemotionPlanner._detect_external_consumers` | Yes (`self.seeding_roots`) | Yes (`sqlite3.Connection`) | No | Via planner: seeding_roots |
| `DemotionPlanner._compute_pool_move_target` | Yes (`self.stash_seeding_root`, `self.pool_payload_root`) | No | No | Via planner: stash_seeding_root, pool_payload_root |
| `DemotionPlanner._payload_exists_on_pool` | Yes (`self.pool_device`, `self.pool_fs_uuid`) | Yes (`sqlite3.Connection`) | No | Via planner: pool_device, pool_fs_uuid |
| `infer_canonical_save_path` | No | No | No | Self-contained (category/tags/paths in, path out) |
| `_placement_kind` | No | No | Yes (`policy.pool_roots`, `policy.stash_roots`) | Via policy object |

### What the orchestrator must wire:

1. **DemotionPlanner instance** — must be constructed upfront with `catalog_path`,
   `seeding_roots`, `library_roots`, `stash_device`, `pool_device`, and optionally
   `stash_seeding_root`/`pool_seeding_root`/`pool_payload_root` for MOVE support.
2. **Catalog DB connection** — must be opened and passed to planner methods that
   need it (`_detect_external_consumers`, `_payload_exists_on_pool`). Also needed for
   payload resolution (torrent → payload → root_path).
3. **ClientDriftPolicy instance** — for `_placement_kind`. The policy's `pool_roots`
   and `stash_roots` must align with the device IDs used by the planner.
4. **qB metadata** — category, tags, current_save_path, current_content_path for
   `infer_canonical_save_path`. These come from the qB cache, not the catalog.

---

## 4. Staging Filter

Defined in `src/hashall/save_path_inference.py:196`:

```python
_STAGING_DIRS = frozenset({
    "_rehome-unique",
    "_qb-finish",
    "_qb-unique-repair",
    "_qb-repair-v2",
})
```

### How it is applied:

1. In `extract_cross_seed_provider_name` (save_path_inference.py:201): staging
   dirs are skipped when extracting tracker name from a path — if `parts[0] in
   _STAGING_DIRS`, the path is not treated as a tracker directory.
2. In `infer_canonical_save_path` (save_path_inference.py:338): when inferring
   `device` for cross-seed torrents without `~noHL` tag, path hints are checked
   — if the first path component under `/pool/media/torrents/seeding/` is a
   staging dir, the device-from-path hint is rejected to avoid false pool inference.

### Why the orchestrator needs it:

Items in staging directories should not be treated as canonically placed. The
orchestrator must replicate this filter when reading current paths:

- A path under `_rehome-unique/` indicates mid-demotion state
- A path under `_qb-finish/` or `_qb-repair-v2/` indicates a qBittorrent transition state
- Device inference from path hints must skip staging directories

---

## 5. Import Notes

### `rehome/planner.py` imports from `hashall.*`:

```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from hashall.device import get_files_table_name
from hashall.payload import (
    get_torrent_instance, get_payload_by_id,
    get_payloads_by_hash, get_torrent_siblings,
)
from hashall.pathing import canonicalize_path, to_relpath, is_under, remap_to_mount_alias
from rehome.normalize import DEFAULT_UNIQUE_VIEW_SUBDIR
```

### `hashall/client_drift.py` imports from `hashall.*` (same package):

```python
from hashall.fs_utils import get_mount_point
from hashall.pathing import canonicalize_path, remap_to_mount_alias
from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE
from hashall.rt_cache import DEFAULT_RT_SHARED_CACHE_FILE
from hashall.rtorrent import ...
from hashall.save_path_inference import ARR_CATEGORY_FINAL_MAP
```

### `hashall/cli.py` imports from `rehome.*` (cross-package):

```python
from rehome.cli import (...)
```

### Risk analysis:

- **No circular import hazard** between `rehome/` and `hashall/` at the function
  level. The cross-package import `hashall/cli.py → rehome.cli` is in a CLI module
  that is not imported by any other hashall module.
- `rehome/planner.py` uses `sys.path.insert(0, ...)` which is fragile — it assumes
  the parent of `src/rehome/` is on `sys.path`. This works at runtime because
  the rehome CLI entry point sets this up, but importing `DemotionPlanner` from
  a `hashall` context (the orchestrator) means the path manip may not have run.
  **The orchestrator should either use the rehome package's entry mechanism or
  ensure `sys.path` is set up correctly before importing `DemotionPlanner`.**
- The orchestrator in `hashall/` should import `DemotionPlanner` from `rehome.planner`
  after ensuring the parent of `src/rehome/` is on the path. Alternatively,
  `DemotionPlanner.__init__` could be refactored to accept a pre-opened connection
  and remove the `sys.path` dependency — but for now, the path insert is required.

### Module path structure:

```
src/
  hashall/
    save_path_inference.py  ← infer_canonical_save_path, InferredSavePath, _STAGING_DIRS
    client_drift.py          ← _placement_kind, ClientDriftPolicy
    pathing.py               ← canonicalize_path, is_under, remap_to_mount_alias
  rehome/
    planner.py               ← DemotionPlanner (all methods)
    normalize.py              ← DEFAULT_UNIQUE_VIEW_SUBDIR
```

---

## 6. Open Questions

1. **`DemotionPlanner` catalog connection pattern**: Should the orchestrator create
   a single `sqlite3.Connection` and pass it to planner methods, or let the planner
   create its own via `_get_db_connection()`? Currently `plan_demotion` accepts an
   optional `conn` — the orchestrator should likely open once and share.

2. **`sys.path.insert(0, ...)` in planner.py**: The orchestrator will likely live in
   `src/hashall/` and must ensure `src/` is on `sys.path` before importing `rehome.planner`.
   Alternatively, should `DemotionPlanner` be refactored to remove the `sys.path` hack?

3. **`_placement_kind` is a module-level function**, not a method — the orchestrator
   must construct a `ClientDriftPolicy` (or use `default_policy()`) before calling it.
   Should the orchestrator accept a policy path as config, or hardcode the defaults
   that align with the planner's stash/pool device config?

4. **`ClientDriftPolicy` root tuple alignment**: The policy defaults use
   `DEFAULT_STASH_PLACEMENT_ROOTS = ("/data/media/torrents/seeding", "/stash/media/torrents/seeding")`
   and `DEFAULT_POOL_PLACEMENT_ROOTS = ("/pool/media/torrents/seeding",)`.
   These must match the device semantics the planner uses (stash_device/pool_device).
   If they diverge, `_placement_kind` may return wrong values.
