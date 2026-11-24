# Stage 1: build. Installs pcache and only the API's runtime dependencies (no pytest, no matplotlib).
# psycopg[binary] bundles libpq, so no system packages are needed.
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: final image: Python packages, the API and the web page. Nothing else.
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY api ./api
COPY web ./web
RUN useradd --create-home app
USER app
EXPOSE 8000
# Database credentials are never baked in; pass them at run time:
#   docker run --env-file .env -p 8000:8000 <image>
# Without PGHOST it reads the CSV at PCACHE_CSV (default data/requests_hourly.csv; mount ./data).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
