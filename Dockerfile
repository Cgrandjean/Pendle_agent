FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY . .

# Ensure local packages are importable
ENV PYTHONPATH=/app

# Create data directory
RUN mkdir -p data

# Expose port 8080 (Fly.io) — also works for HF Spaces (hf_runner.py starts its own server)
EXPOSE 8080

# Run the bot (hf_runner.py for HF/Fly.io, or run_polling() for local dev)
CMD ["python", "scripts/hf_runner.py"]
