from __future__ import annotations

import sqlite3
from pathlib import Path

from companion.config import DEFAULT_PLANT

SCHEMA = """
CREATE TABLE IF NOT EXISTS serials (
  id TEXT PRIMARY KEY,
  lot_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('wip', 'shipped'))
);
CREATE TABLE IF NOT EXISTS current_revs (
  doc_stem TEXT NOT NULL,
  plant TEXT NOT NULL,
  rev INTEGER NOT NULL,
  PRIMARY KEY (doc_stem, plant)
);
CREATE TABLE IF NOT EXISTS holds (
  lot_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  sop_ids TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  id INTEGER PRIMARY KEY AUTOINCREMENT
);
CREATE TABLE IF NOT EXISTS hold_exceptions (
  lot_id TEXT NOT NULL,
  serial_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  id INTEGER PRIMARY KEY AUTOINCREMENT
);
CREATE TABLE IF NOT EXISTS actions (
  thread_id TEXT NOT NULL,
  lot_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  sop_ids TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  sop_ids TEXT NOT NULL,
  provider TEXT NOT NULL,
  retriever TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
  thread_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  query TEXT,
  snapshot_json TEXT
);
"""

DEFAULT_SERIALS = [
    ("SN-4419", "L-8819", "wip"),
    ("SN-4420", "L-8819", "wip"),
    ("SN-4421", "L-8819", "wip"),
    ("SN-4422", "L-8819", "shipped"),
    # Extra lots so scenario runs prove the graph reads MOM instead of
    # reciting defaults baked into the prompt (see companion/scenarios.py).
    ("SN-5501", "L-8820", "wip"),
    ("SN-5502", "L-8820", "wip"),
    ("SN-5503", "L-8820", "wip"),
    ("SN-5504", "L-8820", "wip"),
    ("SN-5505", "L-8820", "shipped"),
    ("SN-6601", "L-8821", "wip"),
    ("SN-6602", "L-8821", "wip"),
    ("SN-6603", "L-8821", "wip"),
    ("SN-7701", "L-8830", "wip"),
    ("SN-7702", "L-8830", "wip"),
    ("SN-7703", "L-8830", "shipped"),
    ("SN-7704", "L-8830", "shipped"),
]

TORQUE_STEM = "QMS-TORQUE"
DEFAULT_TORQUE_REV = 12
PUBLISHED_TORQUE_REV = 13

DEFAULT_CURRENT_REVS = [
    (TORQUE_STEM, DEFAULT_PLANT, DEFAULT_TORQUE_REV),
    ("WI-TORQUE", DEFAULT_PLANT, 8),
    ("QMS-CONTAINMENT", DEFAULT_PLANT, 5),
    ("QMS-NCR-HANDLING", DEFAULT_PLANT, 3),
    ("QMS-SHIP-HOLD", DEFAULT_PLANT, 2),
    ("QMS-LOT-TRACE", DEFAULT_PLANT, 4),
    ("QMS-CALIBRATION", DEFAULT_PLANT, 9),
    ("WI-INSPECTION", DEFAULT_PLANT, 6),
]


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def seed(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM serials")
    conn.execute("DELETE FROM current_revs")
    conn.execute("DELETE FROM holds")
    conn.execute("DELETE FROM hold_exceptions")
    conn.execute("DELETE FROM actions")
    conn.execute("DELETE FROM decisions")
    conn.executemany(
        "INSERT INTO serials (id, lot_id, status) VALUES (?, ?, ?)",
        DEFAULT_SERIALS,
    )
    conn.executemany(
        "INSERT INTO current_revs (doc_stem, plant, rev) VALUES (?, ?, ?)",
        DEFAULT_CURRENT_REVS,
    )
    conn.commit()


def current_rev_lookup(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    rows = conn.execute("SELECT doc_stem, plant, rev FROM current_revs").fetchall()
    return {(r["doc_stem"], r["plant"]): int(r["rev"]) for r in rows}


def plant_current_revs(
    conn: sqlite3.Connection, plant: str = DEFAULT_PLANT
) -> dict[str, int]:
    return {
        stem: rev
        for (stem, site), rev in current_rev_lookup(conn).items()
        if site == plant
    }


def publish_torque_rev(
    conn: sqlite3.Connection,
    *,
    rev: int = PUBLISHED_TORQUE_REV,
    plant: str = DEFAULT_PLANT,
) -> int:
    """Point QMS-TORQUE at ``rev``. Does not drop older (or future) corpus files."""
    conn.execute(
        "UPDATE current_revs SET rev = ? WHERE doc_stem = ? AND plant = ?",
        (rev, TORQUE_STEM, plant),
    )
    if conn.execute(
        "SELECT 1 FROM current_revs WHERE doc_stem = ? AND plant = ?",
        (TORQUE_STEM, plant),
    ).fetchone() is None:
        conn.execute(
            "INSERT INTO current_revs (doc_stem, plant, rev) VALUES (?, ?, ?)",
            (TORQUE_STEM, plant, rev),
        )
    conn.commit()
    return rev


def siblings_of(conn: sqlite3.Connection, lot_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, lot_id, status FROM serials WHERE lot_id = ? ORDER BY id",
        (lot_id,),
    ).fetchall()
    return [{"id": r["id"], "lot_id": r["lot_id"], "status": r["status"]} for r in rows]


def shipped_in_lot(conn: sqlite3.Connection, lot_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM serials WHERE lot_id = ? AND status = 'shipped' ORDER BY id",
        (lot_id,),
    ).fetchall()
    return [r["id"] for r in rows]
