from hashall.hash_progress import HashProgressReporter


def test_hash_progress_reporter_minimal_mode():
    lines = []
    reporter = HashProgressReporter(
        label="payload",
        mode="minimal",
        emit=lines.append,
    )

    reporter.start(total_groups=3, total_bytes=300)
    reporter.update(
        event="progress",
        done_groups=1,
        total_groups=3,
        batch_bytes_done=100,
        batch_bytes_total=300,
    )
    reporter.finish(
        done_groups=3,
        total_groups=3,
        batch_bytes_done=300,
        batch_bytes_total=300,
    )

    assert "Hashing inode groups: 0/3" in lines[0]
    assert "Hashing inode groups: 1/3" in lines[1]
    assert "Hashing complete: 3/3 inode groups" in lines[2]


def test_hash_progress_reporter_full_mode_includes_bytes():
    lines = []
    reporter = HashProgressReporter(
        label="payload",
        mode="full",
        emit=lines.append,
    )
    reporter.start(total_groups=1, total_bytes=1024)
    reporter.update(
        event="chunk",
        done_groups=0,
        total_groups=1,
        path="/pool/data/seeds/movies/movie.mkv",
        file_bytes_done=512,
        file_bytes_total=1024,
        batch_bytes_done=512,
        batch_bytes_total=1024,
        force=True,
    )

    assert any("Hashing:" in line for line in lines)
    assert any("file=512 B/1.0 KiB" in line for line in lines)
    assert any("total=512 B/1.0 KiB" in line for line in lines)
