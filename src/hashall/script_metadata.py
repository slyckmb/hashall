from __future__ import annotations

import atexit
import sys
from datetime import datetime, timezone

_EXIT_CODE = 0
_EMITTED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def emit_start(script_name: str, semver: str, last_updated: str, *, argv: str = "") -> None:
    parts = [
        "event=start",
        f"script={script_name}",
        f"semver={semver}",
        f"last_updated={last_updated}",
        f"timestamp={_now_iso()}",
    ]
    if argv:
        parts.append(f"argv={argv}")
    print(" ".join(parts), flush=True)


def emit_end(script_name: str, semver: str, last_updated: str, *, exit_code: int) -> None:
    global _EMITTED
    if _EMITTED:
        return
    _EMITTED = True
    status = "ok" if int(exit_code) == 0 else "failed"
    print(
        " ".join(
            [
                "event=end",
                f"script={script_name}",
                f"semver={semver}",
                f"last_updated={last_updated}",
                f"timestamp={_now_iso()}",
                f"exit_code={int(exit_code)}",
                f"status={status}",
            ]
        ),
        flush=True,
    )


def register(script_name: str, semver: str, last_updated: str, *, argv: str = "") -> None:
    global _EXIT_CODE
    emit_start(script_name, semver, last_updated, argv=argv)

    def _emit_end() -> None:
        emit_end(script_name, semver, last_updated, exit_code=_EXIT_CODE)

    previous_hook = sys.excepthook

    def _hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        global _EXIT_CODE
        _EXIT_CODE = 1
        emit_end(script_name, semver, last_updated, exit_code=_EXIT_CODE)
        previous_hook(exc_type, exc, tb)

    sys.excepthook = _hook
    atexit.register(_emit_end)
