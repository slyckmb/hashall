import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "bin" / "rehome-stage0.sh"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")


def _write_fake_curl(fake_bin: Path) -> None:
    script = textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import json
        import os
        import sys
        from urllib.parse import parse_qs, urlparse


        def load_state(path):
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)


        def save_state(path, state):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)


        def append_call(state, op, **kwargs):
            call = {"op": op}
            call.update(kwargs)
            state.setdefault("calls", []).append(call)


        def find_torrent(state, torrent_hash):
            for item in state.get("torrents", []):
                if item.get("hash") == torrent_hash:
                    return item
            return None


        def parse_request(argv):
            method = "GET"
            payload = {}
            url = None
            fail_http = False
            output_path = None
            write_out = None
            i = 0
            while i < len(argv):
                token = argv[i]
                if token == "-X" and i + 1 < len(argv):
                    method = argv[i + 1].upper()
                    i += 2
                    continue
                if token in ("-f", "--fail"):
                    fail_http = True
                    i += 1
                    continue
                if token in ("--data-urlencode", "--data", "-d") and i + 1 < len(argv):
                    pair = argv[i + 1]
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        payload[key] = value
                    i += 2
                    continue
                if token in ("-b", "-c", "-o", "-w") and i + 1 < len(argv):
                    if token == "-o":
                        output_path = argv[i + 1]
                    if token == "-w":
                        write_out = argv[i + 1]
                    i += 2
                    continue
                if token.startswith("-"):
                    i += 1
                    continue
                url = token
                i += 1
            return method, payload, url, fail_http, output_path, write_out


        def emit_response(status_code, body, fail_http, output_path, write_out):
            if fail_http and status_code >= 400:
                print(f"curl: ({status_code}) HTTP error", file=sys.stderr)
                return status_code

            stdout = ""
            if output_path:
                if output_path != "/dev/null":
                    with open(output_path, "w", encoding="utf-8") as handle:
                        handle.write(body)
            else:
                stdout += body

            if write_out:
                stdout += write_out.replace("%{http_code}", str(status_code))

            if stdout:
                sys.stdout.write(stdout)

            return 0


        def main():
            state_path = os.environ["FAKE_QBIT_STATE"]
            state = load_state(state_path)
            method, payload, url, fail_http, output_path, write_out = parse_request(sys.argv[1:])

            if url is None:
                print("missing URL", file=sys.stderr)
                return 2

            parsed = urlparse(url)
            path = parsed.path
            status_code = 200
            body = ""

            if path == "/api/v2/auth/login":
                append_call(state, "login")
                save_state(state_path, state)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/info":
                requested_hash = parse_qs(parsed.query).get("hashes", [None])[0]
                if requested_hash is None:
                    append_call(state, "info_all")
                    payload_out = state.get("torrents", [])
                else:
                    append_call(state, "info", hash=requested_hash)
                    torrent = find_torrent(state, requested_hash)
                    payload_out = [torrent] if torrent else []
                save_state(state_path, state)
                body = json.dumps(payload_out)
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if method != "POST":
                append_call(state, "unexpected_method", method=method, path=path)
                save_state(state_path, state)
                status_code = 405
                body = "unexpected method"
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/pause":
                torrent_hash = payload.get("hashes", "")
                append_call(state, "pause", hash=torrent_hash)
                save_state(state_path, state)
                if torrent_hash in set(state.get("fail_pause_hashes", [])):
                    status_code = 500
                    body = "pause failed"
                    return emit_response(status_code, body, fail_http, output_path, write_out)
                if torrent_hash in set(state.get("pause_404_hashes", [])):
                    status_code = 404
                    body = "missing endpoint"
                    return emit_response(status_code, body, fail_http, output_path, write_out)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/stop":
                torrent_hash = payload.get("hashes", "")
                append_call(state, "stop", hash=torrent_hash)
                save_state(state_path, state)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/setLocation":
                torrent_hash = payload.get("hashes", "")
                location = payload.get("location", "")
                append_call(state, "setLocation", hash=torrent_hash, location=location)
                torrent = find_torrent(state, torrent_hash)
                if torrent is None:
                    save_state(state_path, state)
                    status_code = 404
                    body = "missing torrent"
                    return emit_response(status_code, body, fail_http, output_path, write_out)
                torrent["save_path"] = location
                save_state(state_path, state)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/resume":
                torrent_hash = payload.get("hashes", "")
                append_call(state, "resume", hash=torrent_hash)
                save_state(state_path, state)
                if torrent_hash in set(state.get("resume_404_hashes", [])):
                    status_code = 404
                    body = "missing endpoint"
                    return emit_response(status_code, body, fail_http, output_path, write_out)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            if path == "/api/v2/torrents/start":
                torrent_hash = payload.get("hashes", "")
                append_call(state, "start", hash=torrent_hash)
                save_state(state_path, state)
                body = "Ok."
                return emit_response(status_code, body, fail_http, output_path, write_out)

            append_call(state, "unknown_path", path=path)
            save_state(state_path, state)
            status_code = 404
            body = "unknown path"
            return emit_response(status_code, body, fail_http, output_path, write_out)


        if __name__ == "__main__":
            raise SystemExit(main())
        """
    )
    curl_path = fake_bin / "curl"
    curl_path.write_text(script, encoding="utf-8")
    curl_path.chmod(curl_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_stage0(mode: str, tmp_path: Path, state: dict, extra_env: dict | None = None):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_curl(fake_bin)

    state_path = tmp_path / "fake-qbit-state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_QBIT_STATE"] = str(state_path)
    env["QBIT_URL"] = "http://fake-qbit"
    env["QBIT_USER"] = "admin"
    env["QBIT_PASS"] = "adminpass"
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), mode],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    final_state = json.loads(state_path.read_text(encoding="utf-8"))
    return result, final_state


def _find_call_index(calls, op, torrent_hash):
    for idx, call in enumerate(calls):
        if call.get("op") == op and call.get("hash") == torrent_hash:
            return idx
    raise AssertionError(f"Missing call: op={op} hash={torrent_hash}")


def test_stage0_dryrun_filters_candidates_and_maps_target_path(tmp_path):
    state = {
        "torrents": [
            {"hash": "h1", "save_path": "/pool/data/cross-seed/siteA", "progress": 1.0},
            {"hash": "h2", "save_path": "/pool/data/seeds/existing", "progress": 1.0},
            {"hash": "h3", "save_path": "/pool/data/incomplete", "progress": 0.4},
            {"hash": "h4", "save_path": "/stash/media/other", "progress": 1.0},
        ],
        "fail_pause_hashes": [],
        "pause_404_hashes": [],
        "resume_404_hashes": [],
        "calls": [],
    }
    result, final_state = _run_stage0("--dryrun", tmp_path, state)

    assert result.returncode == 0, result.stderr
    assert "candidate_total=1" in result.stdout
    assert "1/1 h1 /pool/data/cross-seed/siteA->/pool/data/seeds/cross-seed/siteA 0s/dryrun" in result.stdout

    calls = final_state["calls"]
    assert calls[0]["op"] == "login"
    assert any(call.get("op") == "info_all" for call in calls)


def test_stage0_apply_continues_after_item_error(tmp_path):
    state = {
        "torrents": [
            {"hash": "bad", "save_path": "/pool/data/a", "progress": 1.0},
            {"hash": "good", "save_path": "/pool/data/b", "progress": 1.0},
        ],
        "fail_pause_hashes": ["bad"],
        "pause_404_hashes": [],
        "resume_404_hashes": [],
        "calls": [],
    }
    result, final_state = _run_stage0("--apply", tmp_path, state)

    assert result.returncode == 1
    assert "1/2 bad /pool/data/a->/pool/data/seeds/a 0s/error" in result.stdout
    assert "2/2 good /pool/data/b->/pool/data/seeds/b " in result.stdout

    calls = final_state["calls"]
    bad_pause_index = _find_call_index(calls, "pause", "bad")
    good_pause_index = _find_call_index(calls, "pause", "good")
    good_set_index = next(
        idx
        for idx, call in enumerate(calls)
        if call.get("op") == "setLocation"
        and call.get("hash") == "good"
        and call.get("location") == "/pool/data/seeds/b"
    )
    assert bad_pause_index < good_pause_index < good_set_index
    assert not any(call.get("op") == "resume" and call.get("hash") == "good" for call in calls)


def test_stage0_apply_falls_back_to_stop_start_on_404(tmp_path):
    state = {
        "torrents": [
            {"hash": "good", "save_path": "/pool/data/c", "progress": 1.0},
        ],
        "fail_pause_hashes": [],
        "pause_404_hashes": ["good"],
        "resume_404_hashes": ["good"],
        "calls": [],
    }
    result, final_state = _run_stage0(
        "--apply",
        tmp_path,
        state,
        extra_env={"HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE": "1"},
    )

    assert result.returncode == 0, result.stdout
    assert "1/1 good /pool/data/c->/pool/data/seeds/c " in result.stdout
    assert "summary mode=apply total=1 ok=1 errors=0 stuck=0" in result.stdout

    calls = final_state["calls"]
    pause_index = _find_call_index(calls, "pause", "good")
    stop_index = _find_call_index(calls, "stop", "good")
    set_index = next(
        idx
        for idx, call in enumerate(calls)
        if call.get("op") == "setLocation"
        and call.get("hash") == "good"
        and call.get("location") == "/pool/data/seeds/c"
    )
    resume_index = _find_call_index(calls, "resume", "good")
    start_index = _find_call_index(calls, "start", "good")
    assert pause_index < stop_index < set_index < resume_index < start_index
