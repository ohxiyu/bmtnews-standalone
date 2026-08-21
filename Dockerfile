# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv for faster dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data
COPY .env.example .env.example

# Install dependencies
RUN uv sync --frozen --no-dev

# Runtime data is mounted here; keep the image and process unprivileged.
RUN useradd --create-home --uid 10001 bmtnews \
    && chown -R bmtnews:bmtnews /app

# Create volume mount points
VOLUME ["/app/data"]

# Set environment variables
ENV PYTHONUNBUFFERED=1
USER bmtnews

# Run the application
ENTRYPOINT ["uv", "run", "bmtnews"]
CMD []
