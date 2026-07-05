# Week 4 Day 28 综合实战：高并发简历结构化提取流水线

## 项目概述

本项目是 Week 4 的收官综合实战，将 Day 22~27 六天的技术组件集成拼装为一个可运行在高吞吐量场景下的**结构化简历抽取与转换引擎**。

## 业务场景

HR 系统收到多份非结构化简历文本，需要批量调用大模型进行 JSON 结构化抽取。流水线需要应对：
- API Key QPS 限流 → `asyncio.Semaphore` 并发控制
- 大模型输出脏 JSON → Day 24 容错解析器本地修复
- Pydantic 校验失败 → 自愈纠错引擎自动组装报错 Prompt 重试
- 外部 API 连续崩溃 → `@circuit_breaker` 熔断器降级保护

## 架构设计

```
main.py (无逻辑主入口)
  ├── pipeline.py (并发提取流水线)
  │     ├── circuit_breaker.py (@circuit_breaker 装饰器)
  │     ├── self_correction.py (反思自愈纠错引擎)
  │     │     ├── resume_schema.py (Pydantic 数据契约)
  │     │     └── day24/robust_json_parser (脏 JSON 修复)
  │     ├── day26/PooledLLMClient (HTTPX 连接池)
  │     └── prompt_template.jinja (Jinja2 提示词模板)
  └── sample_resumes.py (模拟简历数据集)
```

## 技术集成清单

| 技术来源 | 组件 | 在本项目中的角色 |
|----------|------|-----------------|
| Day 23 | Pydantic 结构化输出 | 简历数据契约 + JSON Schema 导出 |
| Day 24 | 脏 JSON 容错解析器 | 本地修复大模型输出的格式损坏 |
| Day 25 | Jinja2 模板引擎 | 提示词与代码解耦 |
| Day 26 | HTTPX 连接池客户端 | TCP/TLS 连接复用 + 指数退避重试 |
| Day 27 | 熔断器状态机 | API 崩溃时自动熔断降级 |

## 快速开始

### 运行单元测试

```bash
cd /path/to/freshManStart
python -m pytest weekly/w04_prompt_and_http/project/test_pipeline.py -v
```

### 运行集成测试（需要配置 API Key）

确保 `.env` 文件中配置了以下变量：

```
MINIMAX_API_KEY=your_api_key
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-M3
```

然后执行：

```bash
python weekly/w04_prompt_and_http/project/main.py
```

## 文件说明

| 文件 | 职责 |
|------|------|
| `resume_schema.py` | Pydantic 简历数据模型 + ValidationError 格式化引擎 |
| `self_correction.py` | 反思自愈纠错引擎（脏 JSON 修复 + 校验失败自动重试） |
| `circuit_breaker.py` | `@circuit_breaker` 异步装饰器工厂 |
| `pipeline.py` | 并发提取流水线核心（信号量限流 + 熔断器 + 自愈 + 统计报告） |
| `prompt_template.jinja` | Jinja2 简历提取提示词模板 |
| `sample_resumes.py` | 8 条覆盖不同边界场景的模拟简历数据集 |
| `main.py` | 无逻辑主入口（纯拼装 + 生命周期管理） |
| `test_pipeline.py` | 单元测试套件（23 个用例） |
