#!/usr/bin/env bash
# 停止 Week 16 本地可观测性集群
set -euo pipefail

COMPOSE_FILE="$(cd "$(dirname "$0")" && pwd)/docker-compose.yml"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down
else
  docker compose -f "${COMPOSE_FILE}" down
fi

echo "[w16] 可观测性集群已停止"
