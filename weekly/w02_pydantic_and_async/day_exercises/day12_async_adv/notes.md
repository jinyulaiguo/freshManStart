# Day 12：异步进阶与网络 API 调用

在 Day 11 中，我们 learning 了事件循环、协程函数以及 `asyncio.gather` 的非阻塞并发调度。但在生产级 Agent 的开发中，仅仅掌握任务并发是不够的。当 Agent 需要通过 HTTP 协议调用 LLM（大语言模型）API，或者处理海量流式输出（Streaming Tokens）时，我们必须解决以下两个核心工程问题：
1. **连接资源的管理**：高并发下如何避免网络套接字（Socket）泄露与文件描述符耗尽？
2. **内存溢出风险**：当 API 返回几百兆数据或无限的事件流时，如何避免一次性拉取整个 HTTP 报文主体导致内存崩溃？

今天，我们将学习通过**异步上下文管理器（`async with`）**与**异步迭代器/生成器（`async for`/`async yield`）**配合 `httpx`，构建高并发、低内存占用的流式网络客户端。

---

## 🧭 核心教学六步法

### 第零步：定位并引导痛点场景

#### 【问】如果没有本节课的技术，代码会在哪里卡住？它解决了什么核心痛点？
在大模型（LLM）对话场景中，如果采用传统的同步 HTTP 库（如 `requests`）以及一次性响应接收模式，系统会遭遇以下致命痛点：
1. **阻塞整个系统**：大模型生成响应通常需要数秒甚至数十秒，`requests.post()` 会阻塞当前执行线程。如果该线程属于 Web 服务的主循环，服务将直接假死，无法响应其他用户的并发请求。
2. **极差的用户体验（流式首字延迟高）**：如果不使用流式传输，用户必须等到 LLM 将 2048 个 Token 全部生成完毕并完成一次性 HTTP 响应构建后，才能看到第一个字。首字呈现延迟（TTFT, Time to First Token）从 100ms 飙升至 10s 以上。
3. **内存水位暴涨**：如果我们要从后端拉取一个 1GB 的 Agent 执行痕迹日志文件，常规的 `response.content` 会一次性将 1GB 字节读入内存，直接导致进程触发 OOM（Out Of Memory）被操作系统内核杀掉。

---

### 第一步：建立直观类比与核心定义

#### 【类比说明】
*   **同步网络调用 vs 异步网络调用**：同步网络调用就像你去前台排队买咖啡，付完钱后你必须站在前台一直等咖啡做好，期间你什么也干不了（阻塞）；异步网络调用就像你付完钱拿着呼叫器找个座位坐下，你可以继续玩手机（执行其他协程任务），当呼叫器响了（I/O 可读信号到达），你再去取咖啡。
*   **一次性接收 vs 流式接收（`async for`）**：一次性接收就像你在水龙头下放一个大水桶，必须等水桶接满水才把它搬走使用（高延迟，高内存占用）；流式接收就像你插了一根麦管在出水口，来一滴水你就喝一滴，水桶里永远不需要积攒大量的水（低延迟，接近零内存积压）。

#### 【核心定义】
1. **异步上下文管理器 (`async with`)**：实现了 `__aenter__` 和 `__aexit__` 异步协议的方法。它保证在进入作用域时异步建立连接/获取资源，在退出作用域时**无论是否发生异常**，都能自动、非阻塞地释放连接或关闭底层 Socket 套接字。
2. **异步生成器 (`async yield`)**：在内部包含 `yield` 语句的异步协程函数。它不一次性返回一个完整的容器，而是允许通过异步非阻塞的方式，在产生数据时向调用方逐步推送数据（产成数据时挂起，消费后再恢复）。

---

### 第二步：提供最小但真实的代码示例

以下代码展示了如何使用 `httpx.AsyncClient` 进行异步 HTTP 请求，并通过异步生成器逐行读取响应内容。

```python
import asyncio
import httpx

async def fetch_stream_data(url: str):
    # 异步上下文管理器自动管理连接池的开启与关闭
    async with httpx.AsyncClient() as client:
        # 使用流式模式发起请求，此时仅读取 HTTP 响应头，不读取报文主体
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise RuntimeError(f"HTTP 请求失败: {response.status_code}")
            
            # 使用 async for 异步遍历生成器，按块（Chunk）非阻塞读取响应体
            async for chunk in response.aiter_bytes(chunk_size=1024):
                # 模拟处理数据块
                yield chunk

async def main():
    target_url = "https://httpbin.org/stream/5"  # 模拟产生 5 行数据的流式接口
    print("开始异步流式拉取数据...")
    async for data_chunk in fetch_stream_data(target_url):
        print(f"收到数据块: {data_chunk.decode('utf-8').strip()}")

if __name__ == "__main__":
    asyncio.run(main())
```

> [!NOTE]
> 请注意 `client.stream` 和 `response.aiter_bytes`。使用同步的 `requests` 库时，我们无法在非阻塞事件循环中挂起 I/O 等待，而 `httpx` 基于 `asyncio` 的套接字封装，实现了真正的非阻塞读取。

---

### 第三步：展示主动破坏与常见报错（防错设计）

在异步网络 I/O 中，最常遇到的两类异常是：**网络超时** 和 **异步上下文管理协议违规**。

#### 1. 网络超时未设置导致的无限挂起
*   **破坏手段**：请求一个极其缓慢或不存在的地址，并且不定义超时参数。默认情况下，如果不进行控制，协程可能会永久挂起。
*   **防御代码**：
    ```python
    # 显式传入超时控制元组 (连接超时, 写入超时, 读取超时, 总池超时)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        ...
    ```

#### 2. 在异步上下文管理器外部访问流式响应体
*   **破坏代码**：
    ```python
    async def bad_usage():
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", "https://httpbin.org/stream/5") as response:
                pass # 离开作用域，底层 TCP 连接已被释放并归还连接池
            
            # 试图在退出 async with 之后读取流数据，将引发异常
            async for chunk in response.aiter_bytes():
                print(chunk)
    ```
*   **报错堆栈特征**：
    `httpx.StreamClosed: The response stream has already been closed.`
*   **修复方案**：必须确保所有对流式数据读取的操作（如 `aiter_bytes()` 或 `aiter_lines()`）完全被包裹在 `async with client.stream(...)` 的生命周期上下文内。

---

### 第四步：设计默写与主动召回机制

请尝试在脑海中完成以下填空题（用于自我检测对异步上下文与流式迭代的掌握）：

```python
import httpx

async def download_file_streamingly(url: str, save_path: str):
    # 【填空1：声明异步上下文管理器，创建一个 AsyncClient 实例】
    _________ httpx.AsyncClient() as client:
        # 【填空2：以流式模式发起请求】
        _________ client.stream("GET", url) as response:
            response.raise_for_status()
            with open(save_path, "wb") as f:
                # 【填空3：使用异步迭代器逐块非阻塞读取字节流】
                _________ _________ chunk in response.___________(chunk_size=4096):
                    f.write(chunk)
```

> **【答案公布】**
> * 填空1：`async with`
> * 填空2：`async with`
> * 填空3：`async for` 和 `aiter_bytes`

---

### 第五步：剖析真实开源项目的用法

以大模型领域中最著名框架 **LangChain** 调用 OpenAI 的异步流式接口（`ChatOpenAI.astream`）为例：

#### 1. 真实应用场景
LangChain 需要通过 HTTP/2 Server-Sent Events (SSE) 协议，从 OpenAI/DeepSeek 接口异步接收流式文本。
#### 2. 底层数据模型与流式接收机制
在底层，LangChain 依靠像 `httpx.AsyncClient` 这样的异步 HTTP 客户端发起 POST 请求，传入 `stream=True`。它利用异步迭代器遍历 HTTP 流，并在解析 SSE 协议头（`data: ...`）后，通过 `async yield` 产生一个个 `ChatGenerationChunk` 对象。
#### 3. 生产环境下的异常处理
```python
# 伪代码：解析流时捕获网络异常与超时，保证上层接收端不会因为单个数据包丢失而彻底挂掉
try:
    async for line in response.aiter_lines():
        if line.startswith("data: "):
            # 解析 SSE 数据帧
            yield parse_sse_data(line)
except httpx.RemoteProtocolError as e:
    # 捕获远程协议异常（如服务器提前关闭连接）进行友好降级处理
    logger.warning(f"流式连接被服务器异常终止: {e}")
```

---

### 第六步：交付自底向上重构的最小引擎与测试

请移步至同一目录下的：
*   **练习模板**：[practice.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day12_async_adv/practice.py)
*   **标准参考答案**：[stream_client.py](file:///Users/zhouyi/03.AI/03.freshManStart/weekly/w02_pydantic_and_async/day_exercises/day12_async_adv/stream_client.py)

请先尝试在练习模板中手写补全核心逻辑，并通过主入口调试检验！
