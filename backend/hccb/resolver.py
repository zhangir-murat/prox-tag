"""SQLite-backed ID -> destination resolver (local replacement for Microsoft's Tag servers)."""
from __future__ import annotations

import random
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from . import codec

SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    prefix INTEGER NOT NULL,
    code INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    url TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(mode, prefix, code)
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    prefix INTEGER NOT NULL,
    code INTEGER NOT NULL,
    tag_row INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    outcome TEXT NOT NULL,          -- resolved | disabled | unassigned
    source TEXT NOT NULL DEFAULT '', -- upload | camera | experiment | ...
    corrected INTEGER NOT NULL DEFAULT 0,
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS scans_tag ON scans(tag_row);
"""


class ResolverError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def validate_url(url: str | None) -> str | None:
    if url is None or url == "":
        return None
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ResolverError("destination must be an absolute http(s) URL")
    return url.strip()


class Resolver:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ------------------------------------------------------------- tags
    def _row(self, r: sqlite3.Row | None) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        d["tag_id"] = codec.format_tag_id(d["mode"], d["prefix"], d["code"])
        return d

    def _limits(self, mode: str):
        if mode == "mstag":
            return 0xFFFF, 0xFFFFFFFF
        if mode == "exp1":
            return 0xFF, 0xFFFFFFFF
        raise ResolverError(f"unknown mode {mode!r}")

    def create(self, mode: str, url: str | None = None, prefix: int = 1, code: int | None = None,
               label: str = "") -> dict:
        pmax, cmax = self._limits(mode)
        if not 0 <= prefix <= pmax:
            raise ResolverError(f"prefix out of range 0..{pmax}")
        url = validate_url(url)
        with self._lock:
            if code is None:
                rng = random.SystemRandom()
                for _ in range(100):
                    code = rng.randrange(1, cmax + 1)
                    if not self.get(mode, prefix, code):
                        break
            elif not 0 <= code <= cmax:
                raise ResolverError(f"code out of range 0..{cmax}")
            now = time.time()
            try:
                cur = self.db.execute(
                    "INSERT INTO tags(mode,prefix,code,label,url,enabled,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?)",
                    (mode, prefix, code, label, url, now, now))
                self.db.commit()
            except sqlite3.IntegrityError:
                raise ResolverError(f"tag {codec.format_tag_id(mode, prefix, code)} already exists", 409)
            return self.by_row(cur.lastrowid)

    def by_row(self, row_id: int) -> dict | None:
        return self._row(self.db.execute("SELECT * FROM tags WHERE id=?", (row_id,)).fetchone())

    def get(self, mode: str, prefix: int, code: int) -> dict | None:
        return self._row(self.db.execute("SELECT * FROM tags WHERE mode=? AND prefix=? AND code=?",
                                         (mode, prefix, code)).fetchone())

    def update(self, row_id: int, **fields) -> dict:
        cur = self.by_row(row_id)
        if not cur:
            raise ResolverError("tag not found", 404)
        sets, vals = [], []
        if "url" in fields:
            sets.append("url=?")
            vals.append(validate_url(fields["url"]))
        if "label" in fields and fields["label"] is not None:
            sets.append("label=?")
            vals.append(str(fields["label"])[:200])
        if "enabled" in fields and fields["enabled"] is not None:
            sets.append("enabled=?")
            vals.append(1 if fields["enabled"] else 0)
        if not sets:
            return cur
        sets.append("updated_at=?")
        vals.append(time.time())
        with self._lock:
            self.db.execute(f"UPDATE tags SET {', '.join(sets)} WHERE id=?", (*vals, row_id))
            self.db.commit()
        return self.by_row(row_id)

    def delete(self, row_id: int) -> None:
        with self._lock:
            cur = self.db.execute("DELETE FROM tags WHERE id=?", (row_id,))
            self.db.commit()
        if cur.rowcount == 0:
            raise ResolverError("tag not found", 404)

    def list(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT t.*, COUNT(s.id) AS scan_count, MAX(s.ts) AS last_scan
            FROM tags t LEFT JOIN scans s ON s.tag_row = t.id
            GROUP BY t.id ORDER BY t.created_at DESC""").fetchall()
        return [self._row(r) for r in rows]

    # ------------------------------------------------------------ resolve
    def resolve(self, mode: str, prefix: int, code: int, source: str = "", corrected: int = 0,
                user_agent: str = "", record: bool = True) -> dict:
        tag = self.get(mode, prefix, code)
        if tag is None:
            outcome = "unassigned"
        elif not tag["enabled"]:
            outcome = "disabled"
        elif not tag["url"]:
            outcome = "unassigned"
        else:
            outcome = "resolved"
        if record:
            with self._lock:
                self.db.execute(
                    "INSERT INTO scans(ts,mode,prefix,code,tag_row,outcome,source,corrected,user_agent) VALUES (?,?,?,?,?,?,?,?,?)",
                    (time.time(), mode, prefix, code, tag["id"] if tag else None, outcome, source, corrected, user_agent[:300]))
                self.db.commit()
        return {
            "outcome": outcome,
            "url": tag["url"] if outcome == "resolved" else None,
            "tag": tag,
            "tag_id": codec.format_tag_id(mode, prefix, code),
        }

    def scans(self, row_id: int | None = None, limit: int = 200) -> list[dict]:
        if row_id is None:
            rows = self.db.execute("SELECT * FROM scans ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM scans WHERE tag_row=? ORDER BY ts DESC LIMIT ?", (row_id, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tag_id"] = codec.format_tag_id(d["mode"], d["prefix"], d["code"])
            out.append(d)
        return out

    def stats(self) -> dict:
        q = self.db.execute
        total = q("SELECT COUNT(*) FROM scans").fetchone()[0]
        by_outcome = {r[0]: r[1] for r in q("SELECT outcome, COUNT(*) FROM scans GROUP BY outcome")}
        by_source = {r[0] or "unknown": r[1] for r in q("SELECT source, COUNT(*) FROM scans GROUP BY source")}
        per_day = [dict(r) for r in q("""SELECT date(ts,'unixepoch','localtime') AS day, COUNT(*) AS n
                                         FROM scans GROUP BY day ORDER BY day DESC LIMIT 30""")]
        tags = q("SELECT COUNT(*), SUM(enabled) FROM tags").fetchone()
        return {"total_scans": total, "by_outcome": by_outcome, "by_source": by_source,
                "per_day": per_day, "tags": tags[0], "enabled_tags": tags[1] or 0}
