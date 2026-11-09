# Local setup without Docker

For Windows machines with no Docker, PostgreSQL or Redis. It uses two lightweight stand-ins, both for development only:

- **PGlite:** real PostgreSQL with pgvector compiled to WebAssembly, run through Node. It handles one transaction at a time.
- **fakeredis:** a Redis-protocol server in Python, held in memory.

Commands are for PowerShell, starting from the repository root.

## Before you start

- Python 3.12 or newer. Python 3.14 was used for development.
- Node 22 or newer.
- **Microsoft Visual C++ Redistributable 2015-2022 (x64).** ONNX Runtime and LightGBM need it, and neither loads without it. Install it from Microsoft.
- About 1 GB free for packages and the embedding model. The virtual environment can live on another drive.

## 1. Configure

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

In `.env`, paste that value into `JWT_SECRET`, set `DEMO_PASSWORD`, then add:

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5433/postgres?sslmode=disable
REDIS_URL=redis://127.0.0.1:6380/0
DB_DISABLE_PREPARED_STATEMENTS=true
```

Optional, to keep large files off a full drive:

```
ARTIFACTS_DIR=D:/incident-dev/artifacts
EMBEDDING_CACHE_DIR=D:/incident-dev/embeddings
```

## 2. Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
npm.cmd --prefix dev\pglite install
npm.cmd --prefix frontend install
```

## 3. Start the database and Redis

Leave each running in its own terminal.

```powershell
npm.cmd --prefix dev\pglite start
```

```powershell
.\.venv\Scripts\python.exe dev\fake_redis.py
```

## 4. Prepare the data

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.ml.train
..\.venv\Scripts\python.exe -m scripts.seed_demo
```

The first seed downloads the embedding model, about 90 MB. Run the seed again after adding articles to `backend/data/knowledge`: it indexes only what changed and keeps your tickets.

## 5. Start the application

Run each in its own terminal, from `backend`, except the last.

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

```powershell
..\.venv\Scripts\python.exe -m celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo
```

```powershell
..\.venv\Scripts\python.exe -m celery -A app.workers.celery_app beat --loglevel=INFO
```

```powershell
npm.cmd --prefix frontend run dev
```

Open <http://localhost:5173>. API docs are at <http://localhost:8000/docs>.

To confirm the whole stack works, including the worker:

```powershell
..\.venv\Scripts\python.exe -m scripts.smoke_test
```

## Running tests

Start a disposable database, which is wiped by each run:

```powershell
npm.cmd --prefix dev\pglite run start:test
```

Then, from `backend`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5434/postgres?sslmode=disable"
$env:DB_DISABLE_PREPARED_STATEMENTS = "true"
..\.venv\Scripts\python.exe -m pytest --cov=app --timeout=120
```

Never point `TEST_DATABASE_URL` at a database you care about, because the suite drops its schema.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `DLL load failed while importing onnxruntime_pybind11_state` or `Could not find module lib_lightgbm.dll` | The Visual C++ Redistributable is missing. Install it. |
| `An Application Control policy has blocked this file` | Windows Smart App Control refused a compiled library file. During development this happened a few times, and each time the same file loaded on the next try. Retry once. If SQLAlchemy's `_cy` files keep being refused, move the `*_cy*.pyd` files out of `site-packages/sqlalchemy`, and SQLAlchemy uses its own Python versions of them. Do not turn Smart App Control off for this project: it cannot be turned back on without resetting Windows. If it persists, use Docker or WSL. |
| `npm.ps1 cannot be loaded because running scripts is disabled` | PowerShell blocks `npm`, which is a script. Use `npm.cmd` as shown in this guide. |
| `prepared statement "_pg3_0" already exists` | Add `DB_DISABLE_PREPARED_STATEMENTS=true`, which PGlite and PgBouncer both need. |
| Tests hang | A session is holding a transaction open across an API call, which blocks on PGlite. Run with `--timeout=120` to see which test. |
| Celery exits with `unknown command 'evalsha'` | `lupa` was missing when the fake Redis started. Install `requirements-dev.txt` and restart `dev\fake_redis.py`. |
| Celery worker hangs or errors on Windows | Use `--pool=solo`. The default pool does not work on Windows. |
| Sign-in fails with "Too many requests" | Login allows 10 attempts a minute. Wait a minute, or restart the API in development. |
| `No trained category model` in the logs | Run `python -m app.ml.train`. Incidents still work without it. |
| The assistant says it lacks evidence for everything | Run the seed. If you changed the embedding model, re-tune `RAG_MIN_SIMILARITY` with `python -m app.rag.evaluate`. |
| `No space left on device` during install | Set `TEMP`, `TMP`, `PIP_CACHE_DIR` and `npm_config_cache` to another drive, and put the virtual environment there. |
