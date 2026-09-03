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

#: Same pinned uv binary as the builder stage — needed at runtime so `uv
#: run` can launch the app (see entrypoint.sh, below).
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

RUN groupadd --system app && useradd --system --gid app --home-dir /app --create-home app

COPY --from=builder /build/.venv /app/.venv

WORKDIR /app
#: `uv run` (CMD, below) needs these to recognize /app as the project root
#: and to confirm the copied .venv matches the lockfile it was built from
#: — must land in /app, so this comes after WORKDIR, not before.
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY entrypoint.sh ./entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" VIRTUAL_ENV="/app/.venv"

RUN chmod +x entrypoint.sh && chown -R app:app /app
USER app

EXPOSE 8000

#: `.venv/bin/uvicorn`'s shebang is hardcoded to the *builder* stage's path
#: (`/build/.venv/bin/python`) at the point `uv sync` created it — that
#: path doesn't exist here, so directly exec'ing the console-script (plain
#: `uvicorn ...`) fails with "no such file or directory" on the shebang's
#: interpreter, not on uvicorn itself. `uv run --no-sync` invokes the
#: already-frozen venv's Python directly (no lockfile re-resolution, no
#: network call) rather than through that broken shebang, and `python -m
#: uvicorn` sidesteps the console-script file entirely as a second layer
#: of protection against the same class of bug.
#:
#: entrypoint.sh runs `alembic upgrade head` against the real production
#: database before exec'ing uvicorn — this only has a live DB connection
#: once the container is actually running on the target node (CI has no
#: network path to production Postgres, so migrations can't run any
#: earlier in the pipeline). Safe with `replicas: 1` in docker-stack.yml;
#: would need a separate one-shot migration job instead of an entrypoint
#: if replicas are ever scaled beyond 1.
ENTRYPOINT ["./entrypoint.sh"]
