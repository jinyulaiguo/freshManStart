"""
Day 84 综合实战: 本地离线研报数据库工具组件

【设计说明】
当 API 异常或需要高可靠离线数据时，提供本地离线数据库检索能力。
"""

import asyncio
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class DatabaseHit(BaseModel):
    category: str
    stat_name: str
    stat_value: str
    year: int


class DatabaseResult(BaseModel):
    records: List[DatabaseHit]


LOCAL_DB = [
    {"category": "整体市场", "stat_name": "全球医疗AI市场规模", "stat_value": "450亿美元", "year": 2026},
    {"category": "核心厂商", "stat_name": "行业领军者", "stat_value": "联影智能、推想医疗、DeepMind Health", "year": 2026},
    {"category": "渗透率", "stat_name": "中国三甲医院渗透明细", "stat_value": "72%", "year": 2026},
    {"category": "政策风向", "stat_name": "核心风险与合规", "stat_value": "FDA/NMPA三类医疗器械审批周期", "year": 2026},
]


class LocalDatabaseTool:
    """本地离线数据库工具"""

    async def execute(self, query: str) -> Dict[str, Any]:
        await asyncio.sleep(0.1)
        hits = [DatabaseHit(**item) for item in LOCAL_DB]
        return DatabaseResult(records=hits).model_dump()
