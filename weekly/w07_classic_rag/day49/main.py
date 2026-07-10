"""
Day 49 综合实战项目统一启动主入口 (main.py)

设计方案：
==========
1. 设计意图：
   本模块是整个 RAG 问答系统的“拼装积木墙”和主控制器总线。
   它本身不承担任何具体算法（如切片或打分），只负责接收生命周期参数、解析 CLI 命令
   并调度对应的可视化 Web App 服务器或交互式 CLI 命令行终端。

2. 启动模式支持：
   - Web 模式 (默认 / --web) : 自动调用 uvicorn 启动挂载了 index.html 网页的 API 服务器。
   - CLI 模式 (--cli)       : 启动终端 REPL 问答循环（高亮显示引用来源与溯源表）。
   - 冒烟测试模式 (--test)   : 非交互自动执行两条预设合规问题，用于 CI/CD 和部署自动验证。
"""

import sys
import argparse
import asyncio
import uvicorn

# 导入底层 Ingestion 和 RAG 服务
from weekly.w07_classic_rag.day48.solution import MultiFormatDocIngestor
from weekly.w07_classic_rag.day49.solution import ChunkIndexer, CitationRAGBot, run_interactive_repl


async def run_cli_mode(test_dir: str):
    """启动终端 CLI REPL 交互模式"""
    print("📁 [CLI 模式] 正在扫描测试文档并构建向量索引...")
    ingestor = MultiFormatDocIngestor(test_dir)
    pages = ingestor.scan_and_ingest()
    
    indexer = ChunkIndexer(collection_name="company_policy", dimension=1536)
    await indexer.ingest_and_index(pages, recreate=True)
    
    bot = CitationRAGBot(indexer, similarity_threshold=0.4)
    # 启动 solution 中定义的命令行循环
    await run_interactive_repl(bot)


async def run_smoke_test_mode(test_dir: str):
    """自动运行非交互冒烟测试并输出脚注解析"""
    print("📁 [冒烟测试模式] 正在构建向量索引并进行非交互问答验证...")
    ingestor = MultiFormatDocIngestor(test_dir)
    pages = ingestor.scan_and_ingest()
    
    indexer = ChunkIndexer(collection_name="company_policy", dimension=1536)
    await indexer.ingest_and_index(pages, recreate=True)
    
    bot = CitationRAGBot(indexer, similarity_threshold=0.4)
    
    test_queries = [
        "请问公司年假有几天？当年没休完会怎么样？",
        "正式员工出差住宿费一天可以报销多少钱？"
    ]
    
    for query in test_queries:
        print(f"\n🙋 自动提问: '{query}'")
        async for packet in bot.answer_stream(query):
            ptype = packet["type"]
            if ptype == "status":
                sys.stdout.write(f"\033[90m[{packet['content']}]\033[0m\n")
                sys.stdout.flush()
            elif ptype == "delta":
                sys.stdout.write(packet["content"])
                sys.stdout.flush()
            elif ptype == "final":
                print("\n")
                citations = packet["citations"]
                if citations:
                    print("\033[33m" + "="*25 + " 📄 原始文献溯源审计表 " + "="*25 + "\033[0m")
                    for idx, cite in enumerate(citations, start=1):
                        print(f" \033[1m[{idx}] [{cite['doc_id']}:{cite['page']}]\033[0m")
                        print(f"   - 来源文献: \033[4m{cite['source_file']}\033[0m")
                        print(f"   - 原始段落: \033[32m{cite['content']}\033[0m")
                        print("-" * 72)
                    print("\033[33m" + "="*72 + "\033[0m")
                else:
                    print("\033[90m[本次生成未包含有效引用来源]\033[0m")


def main():
    parser = argparse.ArgumentParser(description="AI 研究助手 - 经典 Policy RAG 系统启动入口")
    
    # 启动模式选择参数
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--web", action="store_true", help="启动可视化 Web 界面服务 (默认模式)")
    group.add_argument("--cli", action="store_true", help="启动终端交互式 CLI 命令行模式")
    group.add_argument("--test", action="store_true", help="运行非交互端到端冒烟测试")
    
    parser.add_argument(
        "--test-dir", 
        type=str, 
        default="./weekly/w07_classic_rag/day49/test_docs",
        help="CLI / 测试模式下的规章文档扫描目录"
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web 服务的绑定 IP 地址")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务的监听端口")
    
    args = parser.parse_args()

    # Step 1: 判定路由并执行对应启动流
    if args.cli:
        asyncio.run(run_cli_mode(args.test_dir))
    elif args.test:
        asyncio.run(run_smoke_test_mode(args.test_dir))
    else:
        # 默认或明确指定 --web 模式：启动 uvicorn
        print("\n" + "="*60)
        print("    🚀 正在启动 Policy RAG 可视化网页应用服务器...")
        print(f"    🌍 服务地址: http://{args.host}:{args.port}")
        print("    💡 温馨提示: 您可以在浏览器中打开以上网址进行文档上传和流式问答")
        print("="*60 + "\n")
        
        # 启动 Web App (关闭 reload 以保障终端日志输出的整洁度)
        uvicorn.run(
            "weekly.w07_classic_rag.day49.app:app",
            host=args.host,
            port=args.port,
            reload=False
        )


if __name__ == "__main__":
    main()
