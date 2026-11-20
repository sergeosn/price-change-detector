# Guidance for coding agents

## Layout

- `src/config` — Django project: settings, URLs, ASGI entry point. `test_settings.py` is what
  pytest runs under (PostgreSQL from `TEST_DATABASE_URL`, fixed API key, notifications off).
- `src/tracker` — the Django app: models, migrations, admin, management commands, and the
  service layer in `tracker/services` (all business logic lives there).
- `src/api` — FastAPI app: routers, schemas, dependencies (`deps.py`).
- `src/notifications` — the `Notifier` protocol, its implementations and the factory.
- `tests/unit` — one module or service at a time, using fakes.
- `tests/integration` — API, admin, ASGI and management-command tests.
- `tests/helpers.py` — shared fakes and builders; `tests/fixtures/html` — sample pages.

`src` is the import root: import `tracker`, `api`, `config`, `notifications`, never `src.…`.

## Checks

Run all three before calling a change done; CI runs the same commands.

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest --cov` — CI fails below 85% coverage. Needs PostgreSQL: start it with
  `docker compose up -d db`.

After any model change, also run
`DJANGO_SETTINGS_MODULE=config.test_settings uv run python src/manage.py makemigrations --check --dry-run`
— CI rejects a model change that has no migration.

## Rules

**Django owns the models and migrations.**
- Models live only in `src/tracker/models.py`. Generate migrations with `makemigrations`;
  never hand-write one and never edit one that is already committed.
- No second ORM, schema tool or raw DDL anywhere else.

**FastAPI uses the Django ORM through the service layer.**
- Routers call functions in `tracker/services` and map results to schemas. They do not query
  models or hold business logic themselves.
- Route handlers stay plain `def` (the ORM is synchronous). Register new routers in
  `api/main.py` with the `db_connection` dependency so stale connections are dropped.

**Tests never touch the network.**
- Only the tests of a real HTTP client (fetcher, Telegram) may use `respx` to mock the
  transport. Everything else uses fakes.

**External effects sit behind protocols and use fakes in tests.**
- This covers page fetching, notifications, embeddings and LLM calls.
- Callers depend on the protocol (`PageFetcher`, `Notifier`), never on a concrete client, and
  get the implementation from a factory or a FastAPI dependency.
- Fakes live in `tests/helpers.py` and are injected by argument or through
  `app.dependency_overrides` (see `tests/integration/conftest.py`). Do not patch internals.
- A new external integration gets a protocol, a real implementation and a fake in the same
  change.

**No new dependency without a reason.**
- Prefer the standard library and what `pyproject.toml` already lists.
- If one is needed, say why in the change description and add it with `uv add` (`--dev` for
  test-only tools) so `uv.lock` stays in sync — CI installs with `uv sync --frozen`.
