"""
File: server.py
Description: HTTP & SSE 服务端。服务于可视化看板 dashboard.html，并提供流式接口展示推理步骤。

设计方案：
1. 设计意图：
   通过 Python 内置的 http.server 构建轻量级 Web 服务器，避免引入第三方框架（如 FastAPI/Flask），从而保持环境纯净。
   利用 Server-Sent Events (SSE) 技术实现实时的单向步骤数据推送，实现动态的前端状态点亮。

2. 核心结构：
   - `ReasoningHTTPRequestHandler`: 继承自 http.server.BaseHTTPRequestHandler。
     - `do_GET()`: 拦截主页请求返回 dashboard.html，拦截 `/api/run` 触发 SSE 流。
     - `stream_reasoning_steps(query: str)`: 驱动 ReasoningEngine 异步生成器，将结果以 `data: {...}\n\n` 格式写入 wfile。

3. 关键数据流向：
   前端 (EventSource) ──► GET /api/run?query=... ──► 启动 asyncio.run(推理流)
   数据管道：ReasoningEngine ──► yield 字典 ──► 序列化为 JSON ──► 写入 wfile (flush) ──► 前端实时渲染
"""

import asyncio
import urllib.parse
import json
import http.server
import socketserver
import os
import sys

# 保证当前 weekly 目录在 python path 中，能够正常 import weekly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from weekly.w08_advanced_retrieval_and_graph.day56.reasoning_engine import ReasoningEngine

PORT = 8000
HTML_FILE_PATH = os.path.join(os.path.dirname(__file__), "dashboard.html")

# 创建全局引擎单例
engine = ReasoningEngine()

class ReasoningHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """自定义 HTTP 请求处理器，提供静态 HTML 服务与 SSE 异步流通道"""

    def do_GET(self):
        """处理 HTTP GET 请求，路由静态页面与 API 接口"""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        # 1. 静态 HTML 页面路由
        if path in ["/", "/index.html", "/dashboard.html"]:
            self.serve_dashboard()
        # 2. SSE 流式推理接口路由
        elif path == "/api/run":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            query = query_params.get("query", [""])[0]
            if not query:
                self.send_error_response(400, "Query parameter 'query' is required.")
                return
            self.serve_sse_stream(query)
        # 3. 默认 404 拦截
        else:
            self.send_error_response(404, "Not Found")

    def serve_dashboard(self):
        """读取并返回前端可视化看板静态文件"""
        try:
            if not os.path.exists(HTML_FILE_PATH):
                self.send_error_response(404, f"dashboard.html not found at {HTML_FILE_PATH}")
                return
                
            with open(HTML_FILE_PATH, "r", encoding="utf-8") as f:
                html_content = f.read()
                
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_content.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
        except Exception as e:
            self.send_error_response(500, f"Internal Server Error: {str(e)}")

    def serve_sse_stream(self, query: str):
        """流式推送推理步骤结果 (Server-Sent Events)"""
        # 1. 写入 SSE 标准响应头
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        
        # 2. 在同步 handler 中调度异步引擎执行
        async def run_and_stream():
            try:
                # 确保向量数据库已被加载
                # 内存数据库每次运行需要重构以注入最新分片
                await engine.initialize_database()
                
                async for step_result in engine.execute_reasoning(query):
                    # 序列化为 SSE data 帧
                    json_data = json.dumps(step_result, ensure_ascii=False)
                    sse_message = f"data: {json_data}\n\n"
                    
                    # 写入 socket 并即刻 flush 推送
                    self.wfile.write(sse_message.encode("utf-8"))
                    self.wfile.flush()
                    
                    # 适当呼吸，模拟步骤处理感觉，并让步给事件循环
                    await asyncio.sleep(0.5)
            except Exception as stream_err:
                err_data = {
                    "step": -1,
                    "status": "error",
                    "error": f"Stream failed: {str(stream_err)}"
                }
                sse_message = f"data: {json.dumps(err_data, ensure_ascii=False)}\n\n"
                self.wfile.write(sse_message.encode("utf-8"))
                self.wfile.flush()

        # 启动事件循环完成流推送
        asyncio.run(run_and_stream())

    def send_error_response(self, code: int, message: str):
        """封装标准 JSON 错误返回"""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        err_body = json.dumps({"error": message}, ensure_ascii=False)
        self.wfile.write(err_body.encode("utf-8"))

def run_server():
    """启动本地 HTTP 监听服务"""
    # 允许端口即时重用
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), ReasoningHTTPRequestHandler) as httpd:
        print(f"\n=======================================================")
        print(f"🎉 Day 56 可视化推理看板服务已成功启动！")
        print(f"👉 请在浏览器中打开: http://localhost:{PORT}/")
        print(f"=======================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n-> 正在关闭 Web 服务...")
            httpd.shutdown()
            print("-> 服务关闭完成。")

if __name__ == "__main__":
    run_server()
