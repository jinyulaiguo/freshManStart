"""
Day 106 · 核心业务 Agent（零追踪依赖）

约束：本模块禁止 import langsmith / opentelemetry。
追踪完全由进程环境变量 + LangChain 运行时回调完成。
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# 模拟库存：SKU -> (品名, 单价 USD, 库存件数)
_INVENTORY: dict[str, tuple[str, float, int]] = {
    "SKU-1001": ("边缘推理加速卡", 1299.0, 12),
    "SKU-2002": ("向量检索一体机", 4599.0, 3),
    "SKU-3003": ("标注工作站", 899.0, 25),
}


@tool
def lookup_stock(sku: str) -> str:
    """根据 SKU 查询商品名称、单价（USD）与库存数量。"""
    key = sku.strip().upper()
    item = _INVENTORY.get(key)
    if item is None:
        return f"未找到 SKU={key}。可选：{', '.join(_INVENTORY)}"
    name, price, qty = item
    return f"sku={key}; name={name}; unit_price_usd={price}; stock_qty={qty}"


@tool
def calc_quote(unit_price_usd: float, quantity: int) -> str:
    """根据单价与采购数量计算报价小计（USD）。"""
    if quantity <= 0:
        return "quantity 必须为正整数"
    if unit_price_usd < 0:
        return "unit_price_usd 不能为负"
    subtotal = round(unit_price_usd * quantity, 2)
    return f"quantity={quantity}; unit_price_usd={unit_price_usd}; subtotal_usd={subtotal}"


def build_llm() -> ChatOpenAI:
    """使用根 .env 中的 MiniMax OpenAI 兼容配置。"""
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("缺少 MINIMAX_API_KEY，请检查仓库根目录 .env")
    return ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "MiniMax-M3"),
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0,
        timeout=60.0,
    )


def build_react_agent() -> Any:
    """构造 ReAct Agent：业务入口，不含任何追踪 SDK。"""
    tools = [lookup_stock, calc_quote]
    return create_react_agent(
        model=build_llm(),
        tools=tools,
        prompt=(
            "你是采购助手。必须先调用 lookup_stock 查清单价与库存，"
            "再调用 calc_quote 计算小计，最后用中文给出简洁结论。"
            "不要编造库存或价格。"
        ),
    )


def run_agent(query: str) -> str:
    """同步运行一次 Agent，返回最终助手文本。"""
    agent = build_react_agent()
    result = agent.invoke({"messages": [("user", query)]})
    messages = result.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", None)
    return content if isinstance(content, str) else str(last)
