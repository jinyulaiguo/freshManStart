# Week 16 · 可观测性配置与本地集群

本目录先落地 **配置契约 + Docker 脚本**；每日练习代码后续再补。

## 你需要自行提供的配置

复制根目录模版并编辑真实值：

```bash
cp .env.example .env
```

| 变量 | 是否必填 | 说明 |
|------|----------|------|
| `MINIMAX_API_KEY` | 必填（跑 Agent） | 已有则沿用 |
| `LANGSMITH_API_KEY` | 必填（Day 106） | [LangSmith](https://smith.langchain.com/) → API Keys |
| `LANGSMITH_TRACING` | 建议 `true` | 托管追踪开关 |
| `LANGSMITH_PROJECT` | 可选 | 后台项目名 |
| `GF_SECURITY_ADMIN_PASSWORD` | 建议改掉 | Grafana 登录密码 |
| `PHOENIX_*` / `OTEL_*` | 本地默认即可 | 对接本目录 compose，一般不用改 |
| `AGENT_METRICS_PORT` | 本地默认 `9108` | 宿主机 `/metrics` 端口，供 Prometheus 刮取 |
| `PHOENIX_SECRET` | 仅开鉴权时 | 本地学习保持 `PHOENIX_ENABLE_AUTH=false` 即可 |

完整注释见仓库根目录 [`.env.example`](../../.env.example)。

## Python 依赖

根目录已把可观测性包写入 `pyproject.toml`，在仓库根执行：

```bash
uv sync
```

## 启动 Docker 集群（自行运行）

```bash
cd weekly/w16_observability/infra
chmod +x start.sh stop.sh
./start.sh
```

或：

```bash
docker compose --env-file ../../../.env -f docker-compose.yml up -d
```

| 服务 | URL |
|------|-----|
| Phoenix | http://localhost:6006 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

停止：

```bash
./stop.sh
```
