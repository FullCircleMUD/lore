# Lore Importer

Standalone Python tool that walks the `*.yaml` files in this repo,
generates embeddings via OpenAI, and upserts them into the game's
`ai_memory_lorememory` table. No Django, no Evennia — just psycopg /
sqlite3 + the OpenAI SDK.

This is the **single source of truth** for lore ingestion. Both local
dev and the Railway production deploy run this exact script.

## Local usage

```bash
cd FCM/lore/tools
python -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# edit .env, set OPENAI_API_KEY (DATABASE_URL default points at local SQLite)
set -a; source .env; set +a
python import_lore.py
```

First run reports `Created: N`. Subsequent runs against unchanged YAML
report `Unchanged: N`. Edit a YAML entry's content and rerun — should
report `Updated: 1`.

### Flags

- `--dry-run` — walk YAML, print what would change, no DB writes, no
  OpenAI calls.
- `--prune` — delete database entries whose `(source, title)` is no
  longer present in YAML. **Off by default** — accidental file
  deletion would otherwise wipe live lore.

## Railway deployment

Deployed as a separate Railway service in the same project as the
game so it can share `DATABASE_URL` and `OPENAI_API_KEY` via service
references.

1. In the Railway dashboard, **+ New Service → GitHub Repo →
   FullCircleMUD/lore**.
2. **Settings → Service:**
   - Root directory: `tools/`
   - Start command: `python import_lore.py`
3. **Settings → Variables:** add `DATABASE_URL` and `OPENAI_API_KEY`,
   each as a reference to the game service's variable of the same name.
4. **Settings → Deploy:** auto-deploy on push to `main`.
5. Trigger the first deploy. Watch logs — should report `Created: N`,
   exit code 0.
6. Each subsequent push to the lore repo will trigger a fresh deploy
   that re-imports (skipping unchanged entries).

The service exits cleanly after every run. Railway will mark the
deployment as "Removed" — that's expected for a one-shot job.

### Schema dependency

This script writes directly to columns defined by the game-side
`LoreMemory` Django model
(`FCM/src/game/ai_memory/models.py`). If the schema changes, update
the column list in `import_lore.py` to match. Loud comment at the
top of the file calls this out.

The unique constraint `(source, title)` is required for the Postgres
`INSERT ... ON CONFLICT` path. It's added by migration
`ai_memory/0005_lorememory_unique_source_title.py` on the game side.
**Apply that migration before running this tool against a Postgres
database.**

## Troubleshooting

- **`relation "ai_memory_lorememory" does not exist`** — the game's
  `ai_memory` migrations haven't been applied yet. Run
  `evennia migrate --database ai_memory` (locally) or wait for the
  game service's `deploy_migrate.py` to finish (Railway).
- **`type "vector" does not exist`** — pgvector extension isn't
  installed in your Postgres. The game's `deploy_migrate.py` runs
  `CREATE EXTENSION IF NOT EXISTS vector` on Railway. Locally,
  install pgvector or just use SQLite.
- **`OPENAI_API_KEY not set`** — exactly what it says. Use the same
  key the game uses (`LLM_EMBEDDING_API_KEY` in the game's settings).
