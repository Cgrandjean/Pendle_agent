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

# Create data directory
RUN mkdir -p data

# Expose port 7860 (required by HF Spaces)
EXPOSE 7860

# Run the health server + bot
CMD ["python", "scripts/hf_runner.py"]