"""
Week 4 Day 28 综合实战 — 模拟简历数据集 (Sample Resumes)

设计方案：
1. 设计意图：
   提供 8 条覆盖不同边界场景的非结构化简历文本，用于测试流水线在以下维度的表现：
   - 正常提取（信息完整的标准简历）
   - 模糊推断（技能描述含糊，需要模型推断数值）
   - 字段缺失（缺少邮箱等必填字段，触发 Pydantic 校验失败 → 自愈纠错）
   - 多语言处理（英文简历）
   - 复杂嵌套（多段工作经历 + 多技能）

2. 数据结构：
   SAMPLE_RESUMES 是一个列表，每个元素为字典，包含:
   - id: 简历编号
   - scenario: 场景描述（用于日志标记）
   - text: 非结构化简历原文
"""


SAMPLE_RESUMES: list[dict] = [
    {
        "id": 1,
        "scenario": "标准完整简历（信息齐全）",
        "text": (
            "本人周易，工作邮箱 zhouyi@techcorp.com，手机 13800138001。"
            "目前在智能科技有限公司担任高级 Python 工程师，已工作 3 年。"
            "之前在创想数据公司做后端开发 2.5 年。"
            "技术栈方面，Python 熟练度自评 92 分，已使用 5.5 年；"
            "Go 语言熟练度 75 分，使用 2 年；Docker 容器化 60 分，使用 1.5 年。"
        )
    },
    {
        "id": 2,
        "scenario": "模糊技能描述（需要模型推断数值）",
        "text": (
            "我叫李明，邮箱 liming@gmail.com。"
            "我对 Java 非常精通，用了很多年了。"
            "JavaScript 略懂一些，主要做过几个小项目。"
            "在阿里巴巴做了 4 年 Java 后端开发。"
        )
    },
    {
        "id": 3,
        "scenario": "缺失邮箱字段（预期触发校验失败 → 自愈）",
        "text": (
            "王芳，手机号 15900001234。"
            "精通数据分析，Python 使用 3 年，熟练度 85 分。"
            "SQL 数据库查询能力较强，用了 4 年，熟练度 90 分。"
            "在字节跳动数据团队工作 2 年，之前在美团做数据分析师 1.5 年。"
        )
    },
    {
        "id": 4,
        "scenario": "英文简历（多语言处理）",
        "text": (
            "John Smith, email: john.smith@outlook.com, phone: +1-555-0123. "
            "Senior Machine Learning Engineer at Google for 5 years. "
            "Previously worked at Facebook as ML Research Scientist for 3 years. "
            "Expert in Python (95/100, 8 years), TensorFlow (88/100, 5 years), "
            "and Kubernetes (70/100, 3 years)."
        )
    },
    {
        "id": 5,
        "scenario": "复杂多段经历（多工作 + 多技能嵌套）",
        "text": (
            "张伟，联系邮箱 zhangwei@devops.cn。"
            "第一份工作：华为技术，云计算工程师，5 年。"
            "第二份工作：腾讯科技，SRE 运维专家，3 年。"
            "第三份工作：当前在蚂蚁集团做架构师，已工作 2 年。"
            "技能树："
            "Linux 系统运维 95 分 8 年、Kubernetes 90 分 5 年、"
            "Python 脚本 80 分 6 年、Terraform 基础设施即代码 75 分 3 年、"
            "Prometheus 监控 70 分 4 年。"
        )
    },
    {
        "id": 6,
        "scenario": "极简简历（信息极度缺乏）",
        "text": (
            "赵六，会用 Excel 和 PPT。之前在某公司做了一年行政。"
        )
    },
    {
        "id": 7,
        "scenario": "带有格式噪音的简历文本",
        "text": (
            "***个人简历***\n"
            "==============\n"
            "姓名：陈小华\n"
            "邮箱：chenxiaohua@mail.com\n"
            "技能：\n"
            "  - Rust 语言 (精通, 88分, 4年)\n"
            "  - C++ (熟练, 82分, 6年)\n"
            "  - WebAssembly (了解, 45分, 1年)\n"
            "工作经历：\n"
            "  1. Mozilla Foundation, 系统工程师, 3年\n"
            "  2. 华为终端, 嵌入式开发, 2.5年\n"
        )
    },
    {
        "id": 8,
        "scenario": "包含特殊字符和不规则排版",
        "text": (
            "我叫刘洋～～～ 📧 email: liuyang2024@qq.com\n"
            "☎️ 手机: 18612345678\n"
            "💼 工作经历:\n"
            "  ✅ 小米科技 | 前端开发工程师 | 2年\n"
            "  ✅ 网易 | 全栈开发 | 3年\n"
            "🛠 技能: React(85分/4年) Vue(78分/3年) Node.js(72分/3年) TypeScript(68分/2年)"
        )
    }
]


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Day 28 模拟简历数据集预览")
    print("=" * 80)
    for resume in SAMPLE_RESUMES:
        print(f"\n[#{resume['id']}] 场景: {resume['scenario']}")
        print(f"  文本预览: {resume['text'][:80]}...")
    print(f"\n总计 {len(SAMPLE_RESUMES)} 条模拟简历")
    print("=" * 80)
