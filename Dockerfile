FROM node:22-bookworm-slim AS web
WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@10.6.5 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.10.4 AS uv
FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN uv sync --locked --no-dev --no-editable && \
    groupadd --gid 10001 stacks && useradd --uid 10001 --gid stacks --no-create-home stacks && \
    mkdir /data && chown stacks:stacks /data
COPY --from=web /app/frontend/build frontend/build
ENV PATH="/app/.venv/bin:$PATH" STACKS_DATA_DIR=/data PYTHONUNBUFFERED=1
USER stacks
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"
CMD ["uvicorn", "stacks.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
