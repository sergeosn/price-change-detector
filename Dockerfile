FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# uv.lock pins torch to the CPU-only wheel index (see [tool.uv.sources] in pyproject.toml),
# so no CUDA libraries end up in the image.
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
# /models holds the downloaded embedding model. It is created here so that a volume
# mounted over it starts out owned by the app user.
RUN useradd --create-home --uid 1000 app && install -d -o app -g app /models
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    HF_HOME=/models
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src /app/src
WORKDIR /app/src
# collectstatic only needs the settings to import; it never connects to the database.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgres://build-only@localhost/build-only \
    python manage.py collectstatic --noinput
USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec uvicorn config.asgi:app --host 0.0.0.0 --port 8000"]
