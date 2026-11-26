import json
from pathlib import Path
import sqlite3
import time


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(exist_ok=True, parents=True)
        self.db = sqlite3.connect(directory / "memwatch.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, profile TEXT NOT NULL,
                pid INTEGER, name TEXT, kind TEXT NOT NULL, level TEXT NOT NULL,
                message TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_filter ON events(profile,id);
        """
        )

    def profile(self, name):
        row = self.db.execute("SELECT payload FROM profiles WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def _insert(self, profile, pid, kind, level, message, detail, target_name):
        self.db.execute(
            "INSERT INTO events(ts,profile,pid,name,kind,level,message,detail) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                time.time(),
                profile,
                pid,
                target_name,
                kind,
                level,
                message,
                json.dumps(detail, ensure_ascii=False),
            ),
        )

    def log(self, profile, pid, kind, level, message, *, target_name, **detail):
        with self.db:
            self._insert(profile, pid, kind, level, message, detail, target_name)

    def save_profile(self, name, pid, data, target_name):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO profiles VALUES(?,?)",
                (name, json.dumps(data, ensure_ascii=False)),
            )
            self._insert(
                name,
                pid,
                "baseline",
                "info",
                "정상 기준값 저장",
                {
                    "approved": True,
                    "samples": data["samples"],
                    "runs": data["runs"],
                    "bounds": data["bounds"],
                    "created": data["created"],
                },
                target_name,
            )

    def events(self, profile, query="", level="", before=0, limit=50):
        sql = "SELECT * FROM events WHERE profile=? AND (?=0 OR id<?)"
        args = [profile, before, before]
        if level:
            sql += " AND level=?"
            args.append(level)
        if query:
            sql += (
                " AND (instr(message,?) OR instr(kind,?) OR instr(detail,?) OR CAST(pid AS TEXT)=?)"
            )
            args.extend([query] * 4)
        args.append(limit)
        rows = self.db.execute(sql + " ORDER BY id DESC LIMIT ?", args)
        return [dict(row, detail=json.loads(row["detail"])) for row in rows]
