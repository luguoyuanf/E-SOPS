#!/bin/sh
set -eu
python -m app.backend_pre_start
python -m app.modules.migrate --edition esop
MYSQL_USER=esops_app MYSQL_PASSWORD="$MYSQL_APP_PASSWORD" python -m app.initial_data
