"""
Day 98 场景三: 代码库模拟器 (codebase_simulator.py)

模拟 120 个 Python 文件的微服务网关代码库，按 4 个子模块组织。
特定文件中埋入 OWASP 漏洞模式用于安全审计。
"""

import os
import sys
import time
import random
from typing import List, Dict, Any, Iterator, Optional
from dataclasses import dataclass, field

VULNERABILITY_TEMPLATES = {
    "sql_injection": {
        "severity": "CRITICAL",
        "cve": "CVE-2024-38816",
        "pattern": 'query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL Injection',
        "description": "直接字符串拼接构造 SQL 查询，存在 SQL 注入风险"
    },
    "hardcoded_credential": {
        "severity": "HIGH",
        "cve": "CVE-2024-45678",
        "pattern": 'DB_PASSWORD = "admin123!@#"  # Hardcoded credential',
        "description": "硬编码数据库密码，违反安全最佳实践"
    },
    "insecure_deserialization": {
        "severity": "CRITICAL",
        "cve": "CVE-2024-29847",
        "pattern": 'data = pickle.loads(request.body)  # Unsafe deserialization',
        "description": "不安全的反序列化操作，可能导致远程代码执行"
    },
    "path_traversal": {
        "severity": "HIGH",
        "cve": "CVE-2024-32002",
        "pattern": 'filepath = os.path.join("/data", user_input)  # Path traversal',
        "description": "用户输入直接拼接文件路径，存在目录遍历风险"
    },
    "missing_auth_check": {
        "severity": "HIGH",
        "cve": "CVE-2024-41990",
        "pattern": '# TODO: Add authentication check before processing',
        "description": "缺少认证检查的 API 端点，任意用户可访问"
    },
    "weak_crypto": {
        "severity": "MEDIUM",
        "cve": "CVE-2024-38063",
        "pattern": 'hashlib.md5(password.encode()).hexdigest()  # Weak hash',
        "description": "使用 MD5 哈希存储密码，算法强度不足"
    },
    "ssrf": {
        "severity": "HIGH",
        "cve": "CVE-2024-39573",
        "pattern": 'requests.get(user_provided_url)  # SSRF vulnerability',
        "description": "未校验的服务端请求伪造 (SSRF)"
    },
    "xss": {
        "severity": "MEDIUM",
        "cve": "CVE-2024-40725",
        "pattern": 'return f"<div>{user_input}</div>"  # Reflected XSS',
        "description": "用户输入未转义直接输出到 HTML，存在反射型 XSS"
    },
}

# 4 个子模块定义
MODULE_SPECS = {
    "gateway-core": {
        "file_count": 35,
        "vuln_files": {5: "sql_injection", 12: "hardcoded_credential", 25: "insecure_deserialization"},
        "description": "网关核心路由与请求分发模块"
    },
    "auth-plugin": {
        "file_count": 30,
        "vuln_files": {8: "missing_auth_check", 15: "weak_crypto", 22: "hardcoded_credential"},
        "description": "认证授权插件模块"
    },
    "rate-limiter": {
        "file_count": 25,
        "vuln_files": {6: "path_traversal", 18: "ssrf"},
        "description": "流量限速与防刷模块"
    },
    "circuit-breaker": {
        "file_count": 30,
        "vuln_files": {10: "xss", 20: "sql_injection", 28: "insecure_deserialization"},
        "description": "熔断器与降级保护模块"
    },
}


@dataclass
class FileInfo:
    """文件信息数据模型"""
    filename: str
    module: str
    content: str
    file_index: int  # 在模块中的序号
    global_index: int  # 全局序号
    has_vulnerability: bool = False
    vulnerability_type: Optional[str] = None
    vulnerability_detail: Optional[Dict[str, str]] = None
    estimated_tokens: int = 0


def _generate_file_content(module: str, index: int, vuln_type: Optional[str] = None) -> str:
    """生成模拟的 Python 文件内容"""
    base_content = f'''"""
Module: {module} | File #{index}
Auto-generated gateway component for security audit testing.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("{module}.component_{index}")

CONFIG_NAMESPACE = "{module.upper().replace('-', '_')}"
COMPONENT_VERSION = "2.1.{index}"

class Component{index}Handler:
    """组件 {index} 核心处理器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.metrics = {{"processed": 0, "errors": 0}}
        logger.info(f"Component {index} initialized with config: {{config}}")

    async def process_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理入站请求"""
        self.metrics["processed"] += 1
        try:
            validated = self._validate_input(request_data)
            result = await self._execute_logic(validated)
            return {{"status": "ok", "data": result}}
        except Exception as e:
            self.metrics["errors"] += 1
            logger.error(f"Processing error: {{e}}")
            return {{"status": "error", "message": str(e)}}

    def _validate_input(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """输入校验"""
        required_fields = ["action", "payload"]
        for f in required_fields:
            if f not in data:
                raise ValueError(f"Missing required field: {{f}}")
        return data

    async def _execute_logic(self, data: Dict[str, Any]) -> Any:
        """业务逻辑执行"""
        action = data["action"]
        payload = data["payload"]
        return {{"action": action, "result": "processed"}}

    def get_health_status(self) -> Dict[str, Any]:
        """健康检查"""
        return {{
            "component": f"component_{index}",
            "module": "{module}",
            "status": "healthy",
            "metrics": self.metrics
        }}
'''

    # 如果有漏洞，注入漏洞代码
    if vuln_type and vuln_type in VULNERABILITY_TEMPLATES:
        vuln = VULNERABILITY_TEMPLATES[vuln_type]
        vuln_code = f'''
    # ⚠️ VULNERABILITY: {vuln["description"]}
    # Severity: {vuln["severity"]} | {vuln["cve"]}
    def _unsafe_operation(self, user_input):
        {vuln["pattern"]}
        return user_input
'''
        base_content += vuln_code

    return base_content


def iter_module(module_name: str, global_offset: int = 0) -> Iterator[FileInfo]:
    """
    迭代遍历模块中的所有文件

    Args:
        module_name: 子模块名
        global_offset: 全局文件序号偏移

    Yields:
        FileInfo: 文件信息
    """
    spec = MODULE_SPECS.get(module_name)
    if not spec:
        raise ValueError(f"未知模块: {module_name}")

    for i in range(1, spec["file_count"] + 1):
        vuln_type = spec["vuln_files"].get(i)
        content = _generate_file_content(module_name, i, vuln_type)

        vuln_detail = None
        if vuln_type:
            vuln_detail = VULNERABILITY_TEMPLATES[vuln_type].copy()

        yield FileInfo(
            filename=f"{module_name}/component_{i}.py",
            module=module_name,
            content=content,
            file_index=i,
            global_index=global_offset + i,
            has_vulnerability=vuln_type is not None,
            vulnerability_type=vuln_type,
            vulnerability_detail=vuln_detail,
            estimated_tokens=len(content) // 4 + len(content.split())
        )


def get_total_file_count() -> int:
    """获取总文件数"""
    return sum(spec["file_count"] for spec in MODULE_SPECS.values())


def get_module_names() -> List[str]:
    """获取所有模块名"""
    return list(MODULE_SPECS.keys())


def get_total_vulnerability_count() -> Dict[str, int]:
    """获取漏洞统计"""
    stats = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
    for spec in MODULE_SPECS.values():
        for vuln_type in spec["vuln_files"].values():
            if vuln_type in VULNERABILITY_TEMPLATES:
                severity = VULNERABILITY_TEMPLATES[vuln_type]["severity"]
                stats[severity] = stats.get(severity, 0) + 1
    return stats


if __name__ == "__main__":
    print("=" * 70)
    print("🏗️ Day 98 场景三: 代码库模拟器验证")
    print("=" * 70)

    total = get_total_file_count()
    print(f"\n📊 总文件数: {total}")

    vuln_stats = get_total_vulnerability_count()
    print(f"   漏洞统计: CRITICAL={vuln_stats['CRITICAL']} HIGH={vuln_stats['HIGH']} MEDIUM={vuln_stats['MEDIUM']}")

    offset = 0
    for module in get_module_names():
        spec = MODULE_SPECS[module]
        vuln_count = len(spec["vuln_files"])
        print(f"\n   📁 {module}: {spec['file_count']} files, {vuln_count} vulns")
        for f in iter_module(module, offset):
            if f.has_vulnerability:
                print(f"      ⚠️ [{f.filename}] {f.vulnerability_type} ({f.vulnerability_detail['severity']})")
        offset += spec["file_count"]
