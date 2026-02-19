"""Sanity checks for payload orphan timer assets."""

from pathlib import Path


def test_systemd_user_units_exist_and_reference_repo_targets():
    repo_root = Path(__file__).parent.parent
    service = repo_root / "ops" / "systemd" / "user" / "hashall-payload-orphan-snapshot.service"
    timer = repo_root / "ops" / "systemd" / "user" / "hashall-payload-orphan-snapshot.timer"

    assert service.exists()
    assert timer.exists()

    service_text = service.read_text()
    timer_text = timer.read_text()

    assert "WorkingDirectory=%h/dev/work/hashall" in service_text
    assert "Environment=HASHALL_REPO_DIR=%h/dev/work/hashall" in service_text
    assert "Environment=HASHALL_PYTHON=%h/.venvs/hashall/bin/python" in service_text
    assert "make -C \"${HASHALL_REPO_DIR}\" PYTHON=\"$py\" payload-orphan-snapshot" in service_text
    assert "EnvironmentFile=-%h/.config/hashall/payload-orphan-snapshot.env" in service_text
    assert "Environment=PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL=1" in service_text
    assert "Environment=PAYLOAD_ORPHAN_AUDIT_NOTIFY_TO=michael" in service_text
    assert "OnCalendar=*-*-* 00,06,12,18:15:00" in timer_text
    assert "Unit=hashall-payload-orphan-snapshot.service" in timer_text


def test_install_script_links_expected_units():
    repo_root = Path(__file__).parent.parent
    install_script = repo_root / "scripts" / "install_payload_orphan_snapshot_user_timer.sh"

    assert install_script.exists()
    text = install_script.read_text()

    assert "hashall-payload-orphan-snapshot.service" in text
    assert "hashall-payload-orphan-snapshot.timer" in text
    assert "HASHALL_REPO_DIR" in text
    assert "HASHALL_PYTHON" in text
    assert "systemctl --user daemon-reload" in text
    assert "systemctl --user enable --now hashall-payload-orphan-snapshot.timer" in text
