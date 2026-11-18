"""Synchronize the fixed, reviewed GitHub sources used by accounting workflows."""
from pathlib import Path
import subprocess
import threading


SOURCES = {
    "revenue": {
        "url": "https://github.com/ChipmunkRPA/erev-cloud.git",
        "name": "ChipmunkRPA/erev-cloud",
        "license": "Apache-2.0",
    },
    "sec": {
        "url": "https://github.com/sec-gov/python-for-dera-mutual-fund-risk-return-datasets.git",
        "name": "sec-gov/python-for-dera-mutual-fund-risk-return-datasets",
        "license": "CC0-1.0",
    },
}
LOCK = threading.Lock()


def _run(args, timeout=90):
    completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode:
        message = (completed.stderr or completed.stdout or "Git command failed.").strip()
        raise RuntimeError(message[-500:])
    return completed.stdout.strip()


def sync_source(key, root):
    """Clone or fast-forward one allowlisted public repository and return provenance."""
    if key not in SOURCES:
        raise ValueError("Unknown repository source.")
    source = SOURCES[key]
    root = Path(root)
    target = root / key
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK:
        if not (target / ".git").exists():
            _run(["git", "clone", "--depth", "1", source["url"], str(target)], timeout=120)
        else:
            remote = _run(["git", "-C", str(target), "remote", "get-url", "origin"])
            if remote.rstrip("/").removesuffix(".git") != source["url"].rstrip("/").removesuffix(".git"):
                raise RuntimeError("Cached repository remote does not match the allowlisted source.")
            _run(["git", "-C", str(target), "pull", "--ff-only"], timeout=120)
        commit = _run(["git", "-C", str(target), "rev-parse", "HEAD"])
        committed_at = _run(["git", "-C", str(target), "show", "-s", "--format=%cI", "HEAD"])
    return {**source, "commit": commit, "committed_at": committed_at, "path": str(target)}
