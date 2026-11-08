FROM public.ecr.aws/docker/library/python:3.14-slim
ARG APP_EDITION=base
COPY backend/scripts/install-document-tools.sh /tmp/install-document-tools.sh
RUN if [ "$APP_EDITION" = "esop" ]; then sh /tmp/install-document-tools.sh; fi && rm /tmp/install-document-tools.sh
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH=/app/backend/.venv/bin:$PATH
RUN pip install --no-cache-dir uv==0.9.26
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic.ini backend/alembic-mysql.ini ./
COPY editions /app/editions
COPY artifacts/${APP_EDITION}/build-manifest.json /app/build/build-manifest.json
ENV BUILD_MANIFEST_PATH=/app/build/build-manifest.json
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
