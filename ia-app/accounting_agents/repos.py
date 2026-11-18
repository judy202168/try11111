"""Synchronize the fixed, reviewed GitHub sources used by accounting workflows."""
from pathlib import Path
import subprocess
import threading
import time


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
CACHE_SECONDS = 15 * 60


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
        warning = ""
        if not (target / ".git").exists():
            try:
                _run(["git", "clone", "--depth", "1", source["url"], str(target)], timeout=75)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("The repository connection timed out before the source was cached. Retry once; if it continues, check Railway outbound access.") from exc
        else:
            remote = _run(["git", "-C", str(target), "remote", "get-url", "origin"])
            if remote.rstrip("/").removesuffix(".git") != source["url"].rstrip("/").removesuffix(".git"):
                raise RuntimeError("Cached repository remote does not match the allowlisted source.")
            # Do not contact GitHub on every user request. A healthy cached clone
            # keeps the workflow available during transient plugin/network issues.
            if time.time() - (target / ".git" / "FETCH_HEAD").stat().st_mtime > CACHE_SECONDS if (target / ".git" / "FETCH_HEAD").exists() else True:
                try:
                    _run(["git", "-C", str(target), "pull", "--ff-only"], timeout=45)
                except (subprocess.TimeoutExpired, RuntimeError):
                    warning = "GitHub refresh was unavailable; the last verified cached commit was used."
        commit = _run(["git", "-C", str(target), "rev-parse", "HEAD"])
        committed_at = _run(["git", "-C", str(target), "show", "-s", "--format=%cI", "HEAD"])
    return {**source, "commit": commit, "committed_at": committed_at, "path": str(target), "sync_warning": warning}
