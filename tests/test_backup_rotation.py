"""Execute the actual Compose backup function against disposable files and a fake dump tool."""

import os
from pathlib import Path
import subprocess
import textwrap
import time


ROOT = Path(__file__).resolve().parents[1]


def run_backup(tmp_path, *, fail=False):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / "mysqldump"
    tool.write_text("#!/bin/sh\nprintf 'SQL dump\\n'\nexit " + ("1" if fail else "0") + "\n")
    tool.chmod(0o700)
    block = (ROOT / "docker-compose.yml").read_text().split("  backup:\n", 1)[1].split("  backup-test-db:\n", 1)[0]
    script = textwrap.dedent(block.split("      - |\n", 1)[1]).split("trap 'backup;", 1)[0]
    script = script.replace("$$", "$").replace("/backups", str(backup_dir)) + "\nbackup\n"
    environment = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DB_NAME": "test_db",
        "DB_USER": "test",
        "DB_PASSWORD": "unused",
        "BACKUP_RETENTION_DAYS": "14",
    }
    return subprocess.run(["/bin/sh", "-c", script], env=environment, capture_output=True, text=True, timeout=5)


def create_file(directory, name, age_seconds, content="SQL"):
    path = directory / name
    path.write_text(content)
    timestamp = time.time() - age_seconds
    os.utime(path, (timestamp, timestamp))
    return path


def test_backup_rotation_keeps_recent_dumps_and_only_cleans_stale_empty_temporary_files(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    recent = create_file(directory, "test_db-recent.sql", 14 * 86400 - 120)
    expired = create_file(directory, "test_db-expired.sql", 14 * 86400 + 120)
    other = create_file(directory, "other_db-expired.sql", 20 * 86400)
    empty_old = create_file(directory, "test_db-old.sql.tmp", 7200, "")
    empty_recent = create_file(directory, "test_db-recent.sql.tmp", 600, "")
    nonempty_old = create_file(directory, "test_db-partial.sql.tmp", 7200)
    result = run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert recent.exists() and other.exists()
    assert not expired.exists() and not empty_old.exists()
    assert empty_recent.exists() and nonempty_old.exists()
    new = [path for path in directory.glob("test_db-*.sql") if path != recent]
    assert len(new) == 1 and new[0].read_text() == "SQL dump\n"


def test_failed_dump_removes_its_temporary_file_and_preserves_previous_backups(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    previous = create_file(directory, "test_db-previous.sql", 20 * 86400)
    result = run_backup(tmp_path, fail=True)
    assert result.returncode != 0
    assert list(directory.iterdir()) == [previous]
