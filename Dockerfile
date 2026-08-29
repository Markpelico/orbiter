# Multi-stage: uv resolves in the builder, runtime gets only the venv + source.
# Distroless + SBOM + signing arrive in Phase 6 (supply-chain hardening).
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
RUN groupadd -r orbiter && useradd -r -g orbiter orbiter
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH"
USER orbiter
CMD ["python", "-c", "import orbiter; print('specify a command: api, worker, or relay')"]
