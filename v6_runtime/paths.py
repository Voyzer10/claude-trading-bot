"""The V6 data root and a path guard. Every persistent V6 file goes through DataRoot.path(), which refuses anything
outside the root, anything under /opt/trader (the deploy rsync --delete target) and anything that looks like V4 data.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

DEFAULT_ROOT = "/var/lib/trader-v6"
ENV_ROOT = "V6_DATA_ROOT"

# Never inside these trees (V4 code checkout and V4 data / secrets).
FORBIDDEN_PREFIXES = ("/opt/trader", "/etc/trader")
# Never these V4 data path fragments, wherever they appear.
FORBIDDEN_FRAGMENTS = ("trader/paper", "trader/live", "trader.env")


class PathGuardError(ValueError):
    """A V6 path outside the V6 root or pointing at V4 territory."""


def _norm(p: str) -> str:
    return os.path.realpath(os.path.abspath(p))


def check_root(root: str) -> str:
    r = _norm(root)
    r_fwd = r.replace(os.sep, "/")
    _, tail = os.path.splitdrive(r_fwd)
    cmp_tail = tail.lower() if os.name == "nt" else tail
    for pre in FORBIDDEN_PREFIXES:
        if cmp_tail == pre or cmp_tail.startswith(pre + "/"):
            raise PathGuardError("V6 data root %s is inside %s (forbidden: deploy rsync --delete / V4 data)" % (r, pre))
    for frag in FORBIDDEN_FRAGMENTS:
        if frag in cmp_tail:
            raise PathGuardError("V6 data root %s looks like V4 data (%s)" % (r, frag))
    return r


class DataRoot:
    """The one directory V6 may write. Default /var/lib/trader-v6; V6_DATA_ROOT overrides it (tests, staging)."""

    def __init__(self, root: str | None = None):
        self.root = check_root(root if root is not None else os.environ.get(ENV_ROOT, DEFAULT_ROOT))

    def exists(self) -> bool:
        return os.path.isdir(self.root)

    def path(self, *parts: str) -> str:
        p = _norm(os.path.join(self.root, *parts))
        if p != self.root and not p.startswith(self.root + os.sep):
            raise PathGuardError("%s escapes the V6 data root %s" % (p, self.root))
        for frag in FORBIDDEN_FRAGMENTS:
            if frag in p.replace(os.sep, "/"):
                raise PathGuardError("%s looks like V4 data (%s)" % (p, frag))
        return p

    def read_json(self, *parts: str, default: Any = None) -> Any:
        p = self.path(*parts)
        if not os.path.exists(p):
            return default
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def write_json_atomic(self, obj: Any, *parts: str) -> str:
        """Write-to-temp, fsync, rename: a reader sees the old or the new file, never a partial one."""
        p = self.path(*parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(p))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, indent=1, sort_keys=True, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return p

    def append_jsonl(self, obj: Any, *parts: str) -> str:
        p = self.path(*parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return p

    def read_jsonl(self, *parts: str) -> list:
        p = self.path(*parts)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
