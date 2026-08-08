"""
SQLite persistence layer for the pantry app.

Tables (per the spec's data-model sketch, trimmed to what V1 actually needs
since V1 is local-storage-only / single-user, no accounts yet):

  staples            - user-editable staples whitelist (spec 2.2.4)
  spices             - curated spice list + which ones the user owns (spec 2.3)
  favorites          - saved/favorited recipes (spec section 3)
  exclusions         - "never show me X" ingredient list (spec 11.2), stored as
                       names and resolved to recipe-DB ingredient IDs at search
                       time so it survives recipe-DB rebuilds
  nutrition_cache    - kept for Phase 4 Tier-2 computed nutrition (spec 11.4)
"""

import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "pantry.db"

DEFAULT_STAPLES = [
    "salt", "pepper", "black pepper", "oil", "olive oil",
    "vegetable oil", "water", "sugar",
]

# Curated spice list — no data source exposes a reliable "spice" category
# flag, so we maintain this ourselves (spec 2.3).
CURATED_SPICES = [
    "salt", "black pepper", "cayenne pepper", "paprika", "smoked paprika",
    "cumin", "coriander", "turmeric", "chili powder", "garlic powder",
    "onion powder", "oregano", "basil", "thyme", "rosemary", "bay leaves",
    "cinnamon", "nutmeg", "cloves", "allspice", "ginger", "cardamom",
    "fennel seeds", "mustard seeds", "curry powder", "garam masala",
    "red pepper flakes", "italian seasoning", "dried parsley", "sage",
    "five spice powder", "saffron", "vanilla extract", "chili flakes",
    "za'atar", "sumac", "old bay seasoning",
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS staples (
                name TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spices (
                name TEXT PRIMARY KEY,
                owned INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                recipe_id INTEGER PRIMARY KEY,
                title TEXT,
                image TEXT,
                saved_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exclusions (
                name TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nutrition_cache (
                recipe_id INTEGER NOT NULL,
                servings INTEGER NOT NULL,
                payload TEXT NOT NULL,
                computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (recipe_id, servings)
            )
        """)

        # Seed staples on first run
        existing = conn.execute("SELECT COUNT(*) c FROM staples").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO staples (name) VALUES (?)",
                [(s,) for s in DEFAULT_STAPLES],
            )

        # Seed curated spice list on first run (owned=0 by default)
        existing = conn.execute("SELECT COUNT(*) c FROM spices").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO spices (name, owned) VALUES (?, 0)",
                [(s,) for s in CURATED_SPICES],
            )


# ---------- Staples ----------

def list_staples():
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM staples ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def add_staple(name):
    name = name.strip().lower()
    if not name:
        return
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO staples (name) VALUES (?)", (name,))


def remove_staple(name):
    with get_conn() as conn:
        conn.execute("DELETE FROM staples WHERE name = ?", (name.strip().lower(),))


# ---------- Spices ----------

def list_spices():
    with get_conn() as conn:
        rows = conn.execute("SELECT name, owned FROM spices ORDER BY name").fetchall()
        return [{"name": r["name"], "owned": bool(r["owned"])} for r in rows]


def owned_spices():
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM spices WHERE owned = 1 ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def set_spice_owned(name, owned):
    with get_conn() as conn:
        # allow adding a custom spice not in the curated list
        conn.execute(
            "INSERT INTO spices (name, owned) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET owned = excluded.owned",
            (name.strip().lower(), 1 if owned else 0),
        )


# ---------- "Never show me X" exclusions (spec 11.2) ----------

def list_exclusions():
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM exclusions ORDER BY name").fetchall()
        return [r["name"] for r in rows]


def add_exclusion(name):
    name = name.strip().lower()
    if not name:
        return
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO exclusions (name) VALUES (?)", (name,))


def remove_exclusion(name):
    with get_conn() as conn:
        conn.execute("DELETE FROM exclusions WHERE name = ?", (name.strip().lower(),))


# ---------- Favorites ----------

def list_favorites():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_id, title, image, saved_at FROM favorites ORDER BY saved_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_favorite(recipe_id, title, image):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO favorites (recipe_id, title, image) VALUES (?, ?, ?)",
            (recipe_id, title, image),
        )


def remove_favorite(recipe_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM favorites WHERE recipe_id = ?", (recipe_id,))


def is_favorite(recipe_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE recipe_id = ?", (recipe_id,)
        ).fetchone()
        return row is not None


# ---------- Nutrition cache ----------

def get_cached_nutrition(recipe_id, servings):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT payload FROM nutrition_cache WHERE recipe_id = ? AND servings = ?",
            (recipe_id, servings),
        ).fetchone()
        return json.loads(row["payload"]) if row else None


def cache_nutrition(recipe_id, servings, payload):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO nutrition_cache (recipe_id, servings, payload) VALUES (?, ?, ?)",
            (recipe_id, servings, json.dumps(payload)),
        )
