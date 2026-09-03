# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

#: Pinned to match the local uv version that generated `uv.lock` (0.11.28)
#: — keeps the resolver behavior that produced the lockfile reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /build

COPY pyproject.toml uv.lock README.md ./
COPY app ./app

#: `--frozen` refuses to re-resolve or touch the lockfile — the image's
#: dependency versions are exactly what `uv.lock` pins, not "whatever
#: resolves today". `--no-dev` excludes pytest/ruff/mypy from the runtime
#: image. `--no-editable` installs this project as a real package instead
#: of a symlink into /build, which won't exist in the runtime stage.
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --home-dir /app --create-home app

COPY --from=builder /build/.venv /app/.venv

WORKDIR /app
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
