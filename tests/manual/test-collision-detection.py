#!/usr/bin/env python3
"""
Test collision detection and auto-upgrade logic.

Creates synthetic collision scenario:
- Two files with SAME first 1MB (same quick_hash)
- But DIFFERENT full content (different sha1)
- One true duplicate pair (same full SHA1)
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from hashall.scan import scan_path, find_quick_hash_collisions, find_duplicates
from hashall.model import connect_db


def create_test_files(test_dir: Path):
    """Create test files for collision detection."""

    # Create base 1MB chunk (will be shared by collision group)
    base_chunk = os.urandom(1024 * 1024)

    print("📝 Creating test files...")

    # === Collision Group 1: False collision (same quick_hash, different sha1) ===
    file1 = test_dir / "collision_false_1.dat"
    file2 = test_dir / "collision_false_2.dat"

    # Both start with same 1MB, then differ
    with open(file1, "wb") as f:
        f.write(base_chunk)
        f.write(b"DIFFERENT_CONTENT_A" * 1000)

    with open(file2, "wb") as f:
        f.write(base_chunk)
        f.write(b"DIFFERENT_CONTENT_B" * 1000)

    print(f"   ✅ Created false collision pair:")
    print(f"      {file1.name}")
    print(f"      {file2.name}")

    # === True Duplicate Pair (same full content) ===
    file3 = test_dir / "duplicate_original.dat"
    file4 = test_dir / "duplicate_copy.dat"

    # Create identical files
    content = os.urandom(5 * 1024 * 1024)  # 5MB
    with open(file3, "wb") as f:
        f.write(content)
    with open(file4, "wb") as f:
        f.write(content)

    print(f"   ✅ Created true duplicate pair:")
    print(f"      {file3.name}")
    print(f"      {file4.name}")

    # === Unique file (no collision) ===
    file5 = test_dir / "unique.dat"
    with open(file5, "wb") as f:
        f.write(os.urandom(2 * 1024 * 1024))  # 2MB unique

    print(f"   ✅ Created unique file:")
    print(f"      {file5.name}")

    return {
        'false_collision': [file1, file2],
        'true_duplicate': [file3, file4],
        'unique': [file5]
    }


def verify_quick_hashes(db_path: Path, device_id: int):
    """Verify that quick_hash values are set correctly."""
    conn = connect_db(db_path)
    cursor = conn.cursor()
    table_name = f"files_{device_id}"

    cursor.execute(f"""
        SELECT path, quick_hash, sha1
        FROM {table_name}
        WHERE status = 'active'
        ORDER BY path
    """)

    print("\n📊 Database state after fast scan:")
    print(f"{'Path':<30} {'Quick Hash':<20} {'Full SHA1':<20}")
    print("-" * 70)

    for row in cursor.fetchall():
        path = row[0]
        quick = (row[1][:10] + "...") if row[1] else "NULL"
        sha1 = (row[2][:10] + "...") if row[2] else "NULL"
        print(f"{path:<30} {quick:<20} {sha1:<20}")

    conn.close()


def main():
    """Run collision detection test."""

    print("=" * 70)
    print("🧪 COLLISION DETECTION TEST")
    print("=" * 70)

    # Create temporary test directory and database
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "test_data"
        test_dir.mkdir()

        db_path = Path(tmpdir) / "test_catalog.db"

        print(f"\n📁 Test directory: {test_dir}")
        print(f"💾 Test database: {db_path}")

        # Create test files
        test_files = create_test_files(test_dir)

        # Scan with fast hash mode (quick_hash only, sha1=NULL)
        print("\n⚡ Scanning with fast hash mode...")
        scan_path(
            db_path=db_path,
            root_path=test_dir,
            parallel=False,
            hash_mode='fast',
            quiet=True
        )

        # Get device_id
        device_id = os.stat(test_dir).st_dev

        # Verify quick hashes are set, sha1 is NULL
        verify_quick_hashes(db_path, device_id)

        # Find collision groups
        print("\n🔍 Finding collision groups...")
        collisions = find_quick_hash_collisions(device_id, db_path)

        print(f"\n📊 Collision Summary:")
        print(f"   Total collision groups: {len(collisions)}")
        for quick_hash, files in collisions.items():
            print(f"   - {quick_hash[:10]}... : {len(files)} files")
            for f in files:
                print(f"     • {f['path']}")

        # Find duplicates with auto-upgrade
        print("\n⚡ Running duplicate detection with auto-upgrade...")
        duplicates = find_duplicates(device_id, db_path, auto_upgrade=True)

        # Verify results
        print("\n📊 Duplicate Detection Results:")
        print(f"   True duplicate groups: {len(duplicates)}")

        for sha1, files in duplicates.items():
            print(f"\n   SHA1: {sha1[:16]}... ({len(files)} files)")
            for f in files:
                print(f"     • {f['path']} ({f['size']:,} bytes)")

        # Verify database state after upgrade
        print("\n📊 Database state after auto-upgrade:")
        verify_quick_hashes(db_path, device_id)

        # Validation
        print("\n✅ VALIDATION:")

        expected_collision_groups = 2  # 1 false collision + 1 true duplicate
        expected_true_duplicates = 1   # Only the true duplicate pair

        success = True

        if len(collisions) == expected_collision_groups:
            print(f"   ✅ Collision groups: {len(collisions)} (expected {expected_collision_groups})")
        else:
            print(f"   ❌ Collision groups: {len(collisions)} (expected {expected_collision_groups})")
            success = False

        if len(duplicates) == expected_true_duplicates:
            print(f"   ✅ True duplicates: {len(duplicates)} (expected {expected_true_duplicates})")
        else:
            print(f"   ❌ True duplicates: {len(duplicates)} (expected {expected_true_duplicates})")
            success = False

        # Verify all files in collision groups now have full SHA1
        conn = connect_db(db_path)
        cursor = conn.cursor()
        table_name = f"files_{device_id}"

        cursor.execute(f"""
            SELECT COUNT(*) FROM {table_name}
            WHERE status = 'active' AND sha1 IS NULL
        """)
        null_sha1_count = cursor.fetchone()[0]
        conn.close()

        # Should have 1 file with NULL sha1 (the unique file)
        if null_sha1_count == 1:
            print(f"   ✅ Upgraded files: collision groups only (unique file still NULL)")
        else:
            print(f"   ❌ Unexpected NULL sha1 count: {null_sha1_count} (expected 1)")
            success = False

        if success:
            print("\n" + "=" * 70)
            print("✅ ALL TESTS PASSED!")
            print("=" * 70)
            return 0
        else:
            print("\n" + "=" * 70)
            print("❌ TESTS FAILED!")
            print("=" * 70)
            return 1


if __name__ == "__main__":
    sys.exit(main())
