FROM docker.io/library/python:3.12-slim

# Install system dependencies: psycopg binary needs libpq, podman not needed in container.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast, reproducible dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the application source.
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 11240

# Run the app via uvicorn under uv.
CMD ["uv", "run", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "11240"]