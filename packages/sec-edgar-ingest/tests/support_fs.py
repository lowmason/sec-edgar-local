"""Filesystem assertions shared without importing command or context fixtures."""
import hashlib
from pathlib import Path


def tree_snapshot(root: Path) -> dict[str, str]:
    """Every directory and file under root, files by content hash. SQLite's transient WAL files are
    excluded: a reader creates and removes them without changing stored state."""
    entries = {}
    for path in sorted(Path(root).rglob('*')):
        if path.name.endswith(('-wal', '-shm')):
            continue
        entries[str(path.relative_to(root))] = 'dir' if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return entries
