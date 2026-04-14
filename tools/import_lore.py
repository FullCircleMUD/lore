#!/usr/bin/env python3
"""
FullCircleMUD lore importer — standalone, runs anywhere.

Walks the lore YAML files in this repo, embeds each entry via the
OpenAI embeddings API, and upserts into the game's ai_memory_lorememory
table. Talks to the database directly via psycopg (Postgres) or
sqlite3 (local dev) — no Django, no Evennia dependency.

Designed to run as a one-shot Railway service in the same project as
the game so it shares DATABASE_URL via service references. Re-runs on
every push to the lore repo via Railway's auto-deploy.

Usage:
    python import_lore.py             # import all entries
    python import_lore.py --dry-run   # show what would change, no DB writes
    python import_lore.py --prune     # delete DB entries no longer in YAML

Required env vars:
    DATABASE_URL    — postgres://... or sqlite:///path/to/file.db3
    OPENAI_API_KEY  — for the embeddings API call

------------------------------------------------------------------------
SCHEMA WARNING — keep in sync with FCM/src/game/ai_memory/models.py
------------------------------------------------------------------------
This script writes directly to the ai_memory_lorememory table. The
columns it knows about must match the LoreMemory Django model. If you
add or rename a column on the game side, update this script too.

Columns written:
    title           VARCHAR(200)
    content         TEXT
    scope_level     VARCHAR(20)
    scope_tags      JSONB / TEXT (json)
    embedding       BYTEA / BLOB        (sqlite path only)
    embedding_vector vector(1536)       (postgres path only)
    source          VARCHAR(200)
    created_at      TIMESTAMP
    updated_at      TIMESTAMP

Unique constraint: (source, title) — added in migration
ai_memory/0005_lorememory_unique_source_title.py.
------------------------------------------------------------------------
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536
LORE_DIR = Path(__file__).resolve().parent.parent  # repo root


# ── Backend detection ────────────────────────────────────────────────


def detect_backend(database_url: str) -> str:
    if database_url.startswith(("postgres://", "postgresql://")):
        return "postgres"
    if database_url.startswith("sqlite://"):
        return "sqlite"
    raise ValueError(
        f"Unsupported DATABASE_URL scheme: {database_url[:30]}... "
        "Expected postgres:// or sqlite://"
    )


def connect(database_url: str, backend: str):
    if backend == "postgres":
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(database_url, autocommit=False)
        register_vector(conn)
        return conn
    if backend == "sqlite":
        import sqlite3

        path = database_url.replace("sqlite:///", "", 1)
        if path.startswith("/"):
            # sqlite:////absolute/path → /absolute/path
            pass
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    raise ValueError(backend)


# ── Embedding ────────────────────────────────────────────────────────


_openai_client = None


def get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def embed(text: str) -> list[float]:
    client = get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return resp.data[0].embedding


# ── Database ops ─────────────────────────────────────────────────────


def get_existing(conn, backend: str, source: str, title: str) -> dict | None:
    sql = (
        "SELECT content, scope_level, scope_tags FROM ai_memory_lorememory "
        "WHERE source = %s AND title = %s"
    )
    if backend == "sqlite":
        sql = sql.replace("%s", "?")
    cur = conn.cursor()
    try:
        cur.execute(sql, (source, title))
        row = cur.fetchone()
    finally:
        cur.close()
    if not row:
        return None
    if backend == "postgres":
        content, scope_level, scope_tags = row
    else:
        content = row["content"]
        scope_level = row["scope_level"]
        scope_tags = json.loads(row["scope_tags"]) if row["scope_tags"] else []
    return {
        "content": content,
        "scope_level": scope_level,
        "scope_tags": scope_tags or [],
    }


def upsert_postgres(conn, source: str, entry: dict, vec: list[float]) -> str:
    """INSERT ... ON CONFLICT for Postgres. Returns 'created' or 'updated'."""
    import numpy as np

    vec_np = np.asarray(vec, dtype=np.float32)
    now = datetime.now(timezone.utc)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ai_memory_lorememory
                (title, content, scope_level, scope_tags,
                 embedding, embedding_vector, source, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s)
            ON CONFLICT (source, title) DO UPDATE SET
                content = EXCLUDED.content,
                scope_level = EXCLUDED.scope_level,
                scope_tags = EXCLUDED.scope_tags,
                embedding_vector = EXCLUDED.embedding_vector,
                updated_at = EXCLUDED.updated_at
            RETURNING (xmax = 0) AS inserted
            """,
            (
                entry["title"],
                entry["content"],
                entry["scope_level"],
                json.dumps(entry["scope_tags"]),
                vec_np,
                source,
                now,
                now,
            ),
        )
        inserted = cur.fetchone()[0]
    finally:
        cur.close()
    return "created" if inserted else "updated"


def upsert_sqlite(conn, source: str, entry: dict, vec: list[float]) -> str:
    """Two-step upsert for SQLite: select-then-insert/update."""
    import numpy as np

    blob = np.asarray(vec, dtype=np.float32).tobytes()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM ai_memory_lorememory WHERE source = ? AND title = ?",
        (source, entry["title"]),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            """
            UPDATE ai_memory_lorememory SET
                content = ?,
                scope_level = ?,
                scope_tags = ?,
                embedding = ?,
                embedding_vector = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                entry["content"],
                entry["scope_level"],
                json.dumps(entry["scope_tags"]),
                blob,
                now,
                row["id"],
            ),
        )
        return "updated"
    cur.execute(
        """
        INSERT INTO ai_memory_lorememory
            (title, content, scope_level, scope_tags,
             embedding, embedding_vector, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        (
            entry["title"],
            entry["content"],
            entry["scope_level"],
            json.dumps(entry["scope_tags"]),
            blob,
            source,
            now,
            now,
        ),
    )
    return "created"


def upsert(conn, backend: str, source: str, entry: dict, vec: list[float]) -> str:
    if backend == "postgres":
        return upsert_postgres(conn, source, entry, vec)
    return upsert_sqlite(conn, source, entry, vec)


def prune_orphans(conn, backend: str, source: str, valid_titles: set[str]) -> int:
    """Delete entries for *source* whose title isn't in *valid_titles*."""
    if not valid_titles:
        return 0
    placeholders = ",".join(["%s" if backend == "postgres" else "?"] * len(valid_titles))
    sql = (
        f"DELETE FROM ai_memory_lorememory "
        f"WHERE source = {'%s' if backend == 'postgres' else '?'} "
        f"AND title NOT IN ({placeholders})"
    )
    cur = conn.cursor()
    try:
        cur.execute(sql, (source, *sorted(valid_titles)))
        return cur.rowcount
    finally:
        cur.close()


# ── YAML walking ─────────────────────────────────────────────────────


def collect_yaml_files(lore_dir: Path) -> list[Path]:
    paths = []
    for p in sorted(lore_dir.rglob("*.yaml")):
        if "tools" in p.parts or ".git" in p.parts:
            continue
        paths.append(p)
    for p in sorted(lore_dir.rglob("*.yml")):
        if "tools" in p.parts or ".git" in p.parts:
            continue
        paths.append(p)
    return paths


def parse_entry(entry: dict, source: str) -> dict | None:
    title = entry.get("title")
    content = (entry.get("content") or "").strip()
    if not title or not content:
        return None
    return {
        "title": title,
        "content": content,
        "scope_level": entry.get("scope_level", "continental"),
        "scope_tags": list(entry.get("scope_tags") or []),
    }


# ── Main ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Import lore YAML into ai_memory.LoreMemory")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes, no embeddings")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete DB entries no longer present in YAML (per source file).",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2
    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    backend = detect_backend(database_url)
    print(f"Backend: {backend}")
    print(f"Lore dir: {LORE_DIR}")
    if args.dry_run:
        print("DRY RUN — no DB writes")

    conn = connect(database_url, backend) if not args.dry_run else None

    counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0, "pruned": 0}
    yaml_files = collect_yaml_files(LORE_DIR)
    print(f"Found {len(yaml_files)} YAML file(s)\n")

    for yaml_path in yaml_files:
        rel = yaml_path.relative_to(LORE_DIR).as_posix()
        print(f"  Processing: {rel}")
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"    YAML parse error: {e}", file=sys.stderr)
            counts["failed"] += 1
            continue

        if not data or "entries" not in data:
            print("    no 'entries' key — skipping")
            continue

        source = data.get("source", rel)
        seen_titles: set[str] = set()

        for raw_entry in data["entries"]:
            entry = parse_entry(raw_entry, source)
            if entry is None:
                print("    skipped entry with missing title or content")
                counts["failed"] += 1
                continue
            seen_titles.add(entry["title"])

            if args.dry_run:
                print(f"    [DRY] {entry['title']}")
                counts["created"] += 1
                continue

            existing = get_existing(conn, backend, source, entry["title"])
            if (
                existing
                and existing["content"] == entry["content"]
                and existing["scope_level"] == entry["scope_level"]
                and existing["scope_tags"] == entry["scope_tags"]
            ):
                counts["unchanged"] += 1
                print(f"    UNCHANGED: {entry['title']}")
                continue

            try:
                vec = embed(entry["content"])
            except Exception as e:
                print(f"    EMBED FAILED: {entry['title']} — {e}", file=sys.stderr)
                counts["failed"] += 1
                continue

            try:
                status = upsert(conn, backend, source, entry, vec)
                conn.commit()
                counts[status] += 1
                print(f"    {status.upper()}: {entry['title']}")
            except Exception as e:
                conn.rollback()
                print(f"    UPSERT FAILED: {entry['title']} — {e}", file=sys.stderr)
                counts["failed"] += 1

        if args.prune and not args.dry_run and seen_titles:
            try:
                deleted = prune_orphans(conn, backend, source, seen_titles)
                if deleted:
                    conn.commit()
                    counts["pruned"] += deleted
                    print(f"    PRUNED {deleted} orphan(s) from {source}")
            except Exception as e:
                conn.rollback()
                print(f"    PRUNE FAILED for {source} — {e}", file=sys.stderr)

    if conn is not None:
        conn.close()

    print()
    print(
        f"Done. Created: {counts['created']}, Updated: {counts['updated']}, "
        f"Unchanged: {counts['unchanged']}, Pruned: {counts['pruned']}, "
        f"Failed: {counts['failed']}"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
