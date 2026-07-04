# Stage 1: Build the frontend Next.js app
FROM oven/bun:alpine AS frontend-builder
WORKDIR /app

# Copy dependency files
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

# Copy frontend source and build static export
COPY frontend/ ./
RUN bun run build

# Stage 2: Build the Python backend and embed the frontend
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files and install
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy backend files
COPY backend/ ./backend/
COPY README.md ./

# Copy built frontend static files so FastAPI can serve them at the root
COPY --from=frontend-builder /app/out ./frontend/out

# Run FastAPI app using the port specified by Railway/env, falling back to 8000
CMD ["sh", "-c", "uv run uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
