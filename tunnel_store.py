"""
tunnel_store.py — Persistent storage untuk tunnel ID di server.

Menyimpan daftar tunnel ID yang sudah pernah didaftarkan ke SQLite.
Ini memastikan:
  - ID yang sama selalu milik client yang sama (via token)
  - ID tidak bisa di-claim oleh client lain
  - Riwayat tunnel tersimpan (last_seen, created_at)

DB disimpan di: xflow-server/tunnels.db
"""

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tunnels.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    """Buat tabel jika belum ada."""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS tunnels (
                tunnel_id   TEXT PRIMARY KEY,
                token_hash  TEXT NOT NULL,
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL,
                use_count   INTEGER DEFAULT 1
            )
        """)
        con.commit()


def _hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else "noauth"


def register(tunnel_id: str, token: str) -> bool:
    """
    Daftarkan tunnel ID baru.
    Return True jika berhasil, False jika ID sudah dipakai token lain.
    """
    th = _hash(token)
    now = time.time()
    with _conn() as con:
        row = con.execute("SELECT token_hash FROM tunnels WHERE tunnel_id = ?", (tunnel_id,)).fetchone()
        if row is None:
            # ID baru — daftarkan
            con.execute(
                "INSERT INTO tunnels (tunnel_id, token_hash, created_at, last_seen) VALUES (?,?,?,?)",
                (tunnel_id, th, now, now)
            )
            con.commit()
            return True
        elif row["token_hash"] == th:
            # ID milik token yang sama — update last_seen
            con.execute(
                "UPDATE tunnels SET last_seen = ?, use_count = use_count + 1 WHERE tunnel_id = ?",
                (now, tunnel_id)
            )
            con.commit()
            return True
        else:
            # ID dipakai token lain — tolak
            return False


def is_owner(tunnel_id: str, token: str) -> bool:
    """Cek apakah token ini pemilik tunnel_id."""
    th = _hash(token)
    with _conn() as con:
        row = con.execute(
            "SELECT token_hash FROM tunnels WHERE tunnel_id = ?", (tunnel_id,)
        ).fetchone()
        if row is None:
            return False
        return row["token_hash"] == th


def get_info(tunnel_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM tunnels WHERE tunnel_id = ?", (tunnel_id,)
        ).fetchone()
        return dict(row) if row else None


def list_all() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM tunnels ORDER BY last_seen DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# Init saat module di-import
init_db()