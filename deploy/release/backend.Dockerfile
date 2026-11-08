FROM public.ecr.aws/docker/library/python:3.14-slim
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH=/app/backend/.venv/bin:$PATH
COPY backend/scripts/install-document-tools.sh /tmp/install-document-tools.sh
RUN sh /tmp/install-document-tools.sh && rm /tmp/install-document-tools.sh && pip install --no-cache-dir uv==0.9.26
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic.ini backend/alembic-mysql.ini ./
COPY editions /app/editions
ARG SOURCE_REVISION=source-archive
ENV SOURCE_REVISION=${SOURCE_REVISION}
RUN PROJECT_NAME=ESOPS FIRST_SUPERUSER=admin@example.com FIRST_SUPERUSER_PASSWORD=build-placeholder DATABASE_TYPE=mysql MYSQL_DB=esops MYSQL_USER=esops MYSQL_PASSWORD=build-placeholder APP_EDITION=esop python -m app.modules.generate_manifest --edition esop --output /app/build/build-manifest.json
ENV BUILD_MANIFEST_PATH=/app/build/build-manifest.json
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
