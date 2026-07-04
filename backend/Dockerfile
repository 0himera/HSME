# Use a fast Python slim base image
FROM python:3.12-slim-bookworm

# Install uv using the official image to benefit from compile caching and performance
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy only the files needed for dependency resolution to leverage cache
COPY pyproject.toml uv.lock ./

# Install dependencies using standard uv sync
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application files
COPY backend/ ./backend/
COPY README.md ./

# Expose backend port
EXPOSE 8000

# Run FastAPI app
CMD ["uv", "run", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
