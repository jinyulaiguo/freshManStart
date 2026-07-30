#!/usr/bin/env bash
# 启动 Week 16 本地可观测性集群（Phoenix + Prometheus + Grafana）
# 用法：在本目录执行 ./start.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
COMPOSE_FILE="$(cd "$(dirname "$0")" && pwd)/docker-compose.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[w16] 未找到 ${ENV_FILE}"
  echo "[w16] 请先：cp .env.example .env ，并按注释填写 [必填] 项"
  exit 1
fi

echo "[w16] 使用环境文件: ${ENV_FILE}"
echo "[w16] 启动 compose: ${COMPOSE_FILE}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

echo
echo "[w16] 已启动。访问地址（请用 0.0.0.0 或 127.0.0.1，勿用 localhost）："
echo "  Phoenix UI     http://0.0.0.0:6006"
echo "  Prometheus UI  http://0.0.0.0:9090"
echo "  Grafana UI     http://0.0.0.0:3000  (账号见 .env 中 GF_SECURITY_*)"
echo
echo "[w16] 课前总纲: weekly/w16_observability/overview.html"
echo "[w16] OTLP: OTEL_EXPORTER_OTLP_ENDPOINT=http://0.0.0.0:6006/v1/traces"
echo
echo "[w16] 查看日志: docker compose -f ${COMPOSE_FILE} logs -f"
echo "[w16] 停止集群: docker compose -f ${COMPOSE_FILE} down"
