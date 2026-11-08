#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo '请先安装 Docker 与 Compose 插件。' >&2; exit 1; }
docker compose version >/dev/null
command -v openssl >/dev/null || { echo '请安装 openssl。' >&2; exit 1; }
command -v python3 >/dev/null || { echo '请安装 Python 3。' >&2; exit 1; }
if [[ ! -f .env ]]; then
  umask 077
  echo '首次部署：将生成独立的数据库和管理员凭据，保存在 .env。'
  read -r -p '管理员邮箱: ' admin_email
  [[ "$admin_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo '邮箱格式无效。' >&2; exit 1; }
  cat > .env <<CONFIG
PROJECT_NAME=ESOPS
ENVIRONMENT=production
APP_EDITION=esop
DATABASE_TYPE=mysql
MYSQL_SERVER=db
MYSQL_PORT=3306
MYSQL_DB=esops
MYSQL_USER=esops_app
MYSQL_APP_PASSWORD=$(openssl rand -hex 24)
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
ESOP_ACTIVATION_CIPHER_KEY=$(openssl rand -base64 32 | tr '/+' '_-')
FIRST_SUPERUSER=$admin_email
FIRST_SUPERUSER_PASSWORD=$(openssl rand -hex 12)
REDIS_URL=redis://redis:6379/0
REDIS_KEY_PREFIX=esops-open
FRONTEND_HOST=http://localhost:18096
BACKEND_CORS_ORIGINS=[]
STORAGE_PROVIDER=local
ESOPS_BIND=127.0.0.1
ESOPS_PORT=18096
CONFIG
fi
umask 077
grep -vE '^(MYSQL_ROOT_PASSWORD|MYSQL_APP_PASSWORD)=' .env > .env.runtime
revision=$(git rev-parse HEAD 2>/dev/null || printf source-archive)
docker build -f deploy/release/backend.Dockerfile --build-arg "SOURCE_REVISION=$revision" -t esops-open-backend:local .
container=$(docker create esops-open-backend:local)
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
mkdir -p artifacts/esop
docker cp "$container:/app/build/build-manifest.json" artifacts/esop/build-manifest.json
docker rm "$container" >/dev/null
trap - EXIT
python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path('artifacts/esop/build-manifest.json').read_text())
Path('artifacts/esop/build-manifest.ts').write_text('export const buildManifest = ' + json.dumps(manifest, indent=2, ensure_ascii=False) + ' as const;\n')
PY
docker compose -f compose.release.yml up -d --build
echo '部署已启动。管理员邮箱和初始密码保存在权限为 600 的 .env 文件中。'
echo '请检查 docker compose -f compose.release.yml ps 和日志。'
