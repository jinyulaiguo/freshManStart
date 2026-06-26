# Day 5 学习笔记：接口抽象、设计模式与动态反射

在大模型智能体（Agent）开发中，随着系统功能的增加，硬编码的逻辑（如大量的 `if-else` 判断）会导致代码变得臃肿不堪、极难维护。同时，如何保证第三方插件的安全插入、如何对大模型的调用指令进行安全执行，以及如何优雅地解耦 Agent 的内部推理与外部日志展示，是走向工业级生产环境必须面对的关键课题。

---

## 目录
1. [零基础入门：接口、反射与设计模式的 Agent 映射](#零基础入门接口反射与设计模式的-agent-映射)
2. [核心机制对比总览（快速索引表格）](#核心机制对比总览快速索引表格)
3. [知识点一：结构化子类型 `Protocol` (PEP 544)（六步学习法拆解）](#知识点一结构化子类型-protocol-pep-544)
4. [知识点二：安全反射执行机制（`getattr` 防御性设计）（六步学习法拆解）](#知识点二安全反射执行机制getattr-防御性设计)
5. [知识点三：面向 Agent 架构的设计模式集成（单例、工厂、观察者）（六步学习法拆解）](#知识点三面向-agent-架构的设计模式集成单例工厂观察者)
6. [加餐知识点：多线程单例穿透与双重检查锁定 (DCL) 机制](#加餐知识点多线程单例穿透与双重检查锁定-dcl-机制)
7. [开源项目深度剖析：优秀设计模式与反射机制的真实示例](#开源项目深度剖析优秀设计模式与反射机制的真实示例)

---

## 零基础入门：接口、反射与设计模式的 Agent 映射

在迈向高阶架构前，我们先用最通俗的语言搞懂这三个生僻词汇到底在大模型 Agent 中扮演什么角色：

### 1. 接口约束（ABC 与 Protocol）
*   **什么是接口？** 接口就像是一份“商业合同”。它规定了签署方必须履行的职责（拥有哪些属性、实现哪些方法），但它自己不负责干活。
*   **在 Agent 中的映射**：我们定义一个 `ToolProtocol`（工具合同）。合同规定凡是工具都必须拥有 `name` 属性和 `run` 方法。不管是搜索引擎、计算器还是数据库执行器，只要满足这两个条件，Agent 就可以安全地接入并调用它。

### 2. 动态反射（Reflection）
*   **什么是反射？** 反射是程序在**运行状态中**，能够“自我剖析”并动态获取对象信息或调用其方法的能力。
*   **在 Agent 中的映射**：大模型（LLM）进行 Function Calling 时，输出的是 JSON 格式的文本：`{"tool_name": "send_email", "args": {...}}`。我们无法在写代码时预知 LLM 究竟要调哪个工具，所以必须依靠反射机制，通过工具名字符串 `"send_email"` 动态在代码中找到 `send_email` 方法并执行。

### 3. 设计模式（Design Patterns）
*   **什么是设计模式？** 它们是前人在特定软件设计场景下总结出的“最佳套路”，用来解决对象创建、耦合、通信等经典痛点。
*   **在 Agent 中的映射**：
    *   **单例模式**：全局只保持一个 LLM 网络连接池（`LLMClient`），避免每个 Agent 创建时都重复握手建立 TCP 连接。
    *   **工厂模式**：根据 LLM 的意图，动态实例化不同角色（如 `CoderAgent`、`PlannerAgent`）。
    *   **观察者模式**：Agent 推理链（ReAct）执行过程漫长，我们将“打印日志”、“前端 WebSocket 刷新”等逻辑作为“观察者”挂载到 Agent 身上，实现核心算法与外围展示的彻底解耦。

---

## 核心机制对比总览（快速索引表格）

| 机制 / 模式 | 核心原理 | 解决了什么痛点？ | Agent 实战典型场景 |
| :--- | :--- | :--- | :--- |
| **抽象基类 `abc.ABC`** | **名义子类型 (Nominal)**。子类必须显式继承（`class A(Base)`），强制在运行时或静态检查中实现抽象方法。 | 防止子类遗漏核心方法导致运行时报错。但强继承关系会导致严重的强绑定耦合（MRO 冲突）。 | 框架内部高度统一的核心组件定义（如自定义 BaseAgent 基类）。 |
| **协议 `typing.Protocol`** | **结构化子类型 (Structural)**。也称静态鸭子类型（PEP 544）。只要类结构上实现了对应方法和属性，即视为契约实现。 | 避免强继承绑定，允许非侵入式地约束外部贡献的 Tool，享受静态类型工具（mypy）的严苛安全提示。 | 第三方插件/外置 Tool 的非侵入式类型提示校验。 |
| **动态反射 `getattr`** | 通过属性/方法的字符串名称，在运行期动态寻找并返回该属性的引用。 | 摆脱臃肿的 `if tool_name == "xxx":` 等硬编码，使得 Tool 调用机制天然支持开闭原则（OCP）。 | 将大模型 Function Calling 输出的工具名字符串安全映射到 Python 类方法并执行。 |
| **单例模式 (Singleton)** | 保证一个类在全局内存中**仅有一个实例**，并提供全局唯一的访问入口。 | 避免频繁建立底层大模型 API 连接、重载配置文件导致的内存和连接资源严重浪费。 | 全局唯一的 `LLMClient` 客户端、全局配置类 `AppConfig`。 |
| **观察者模式 (Observer)** | 允许一个目标对象（Subject）注册多个观察者（Observer），并在自身状态改变时自动广播通知所有观察者。 | 避免核心推理循环中混入 console 打印、WebSocket 推送、日志持久化等杂乱的 I/O 代码。 | Agent 状态轨迹追踪与流式事件广播（如 ReAct 循环中的 `THINKING -> ACTING -> DONE`）。 |

---

## 知识点一：结构化子类型 `Protocol` (PEP 544)

### 第零步：找到最小痛点场景
> **没有它，我的代码会在哪里卡住？**
在为 Agent 框架设计自定义插件生态时，如果使用 `abc.ABC`，你要求外部贡献者编写的工具类必须继承你的 `BaseTool`。万一贡献者使用的底层类库（如 `Pydantic` 或者是特殊的 API 包装库）已经有了一个深度的继承体系，Python 的多重继承极易引发 **MRO (Method Resolution Order) 冲突**。
如果不作任何约束，只靠运行时“鸭子类型”盲跑，那么写错参数（如把 `run(self, query: str)` 写成 `run(self, q: str)`）只会在大模型真正触发该工具的瞬间引发运行时报错，无法在**开发期/静态编译期**被 IDE 捕捉到。

### 第一步：建立类比锚点

> [!NOTE]
> **什么是鸭子类型 (Duck Typing)？**
> 源自名言：“如果它走起路来像鸭子，叫起来也像鸭子，那么它就是鸭子。”
> 在编程中的精髓在于：**关注行为，而不关注类型**。只要一个对象在结构上实现了对应的方法和属性，我们就可以把它当成该类型来调用，而不需要通过强继承确认家谱。

*   **生活类比**：**USB 接口规范**。
    *   **abc.ABC 强绑定**：要求任何可以充电的设备在出厂时必须在商业关系上声明属于“USB 官方直属子公司”（必须继承 `USBDevice`），否则插头插上去也拒绝导电。
    *   **Protocol 静态契约**：只要你这个硬件的插头尺寸是 12mm x 4.5mm、触点具备 4 个金属极（实现了 `name` 和 `run`），不管你是电风扇、手机还是暖手宝，插上即可正常工作。

*   **三句话复述**：
    1. `Protocol` 是静态类型检查（PEP 544）的鸭子类型契约。
    2. 子类实现该协议时**无需显式继承**它，只要结构（属性、方法、参数签名）一致即可通过校验。
    3. 它通过 `mypy` 等静态分析工具，在程序还没运行前就锁死接口规范。

### 第二步：最小但真实的代码与单步调试
```python
from typing import Protocol

# 1. 用 Protocol 声明一个规范
class ToolProtocol(Protocol):
    @property
    def name(self) -> str: ...
    def run(self, query: str) -> str: ...

# 2. 隐式实现（完全不继承任何父类）
class ScraperTool:
    @property
    def name(self) -> str:
        return "web_scraper"
        
    def run(self, query: str) -> str:
        return f"已抓取关于 {query} 的数据"

# 3. 静态多态注入验证
def execute_tool(tool: ToolProtocol, q: str) -> None:
    print(f"执行 {tool.name}: {tool.run(q)}")

# 调试与预测：
# 执行 mypy 校验，分析为什么在没有继承关系的情况下，ScraperTool 实例可以被完美传参给 tool: ToolProtocol。
```

### 第三步：主动破坏与报错记录
1. **破坏属性**：删除 `ScraperTool` 的 `name` 属性，运行 `mypy` 校验该脚本。
   * **报错信息**：`error: Argument 1 to "execute_tool" has incompatible type "ScraperTool"; expected "ToolProtocol"` 
   * **详细指明**：`note: "ScraperTool" is missing following "ToolProtocol" protocol member: name`
2. **破坏参数签名**：将 `ScraperTool.run(self, query: str)` 改为 `run(self, query: int)`。
   * **报错信息**：参数类型不匹配报错，mypy 拦截该非兼容实现。

### 第四步：默写
*   **行动**：关掉所有文档，凭记忆手写一个满足静态 Protocol 规范隐式实现的最小工具类。

### 第五步：阅读优秀项目
在很多现代轻量级 Python 框架（例如基于类型提示的 `FastAPI` 内部校验、或者是 `typing.SupportsRead` 系列标准库）中，都广泛使用了 `Protocol`。通过鸭子类型静态检测，这使得它们在极度解耦的前提下，依然拥有不输于 Java 强接口定义的类型安全性。

---

## 知识点二：安全反射执行机制（`getattr` 防御性设计）

### 第零步：找到最小痛点场景
> **没有它，我的代码会在哪里卡住？**
LLM 调用工具的核心机制是“文本转换”。模型返回的 JSON 里只有工具名字的**字符串**（如 `"send_email"`）。我们必须在程序中通过这个字符串动态找到对应的方法。
如果使用反射 `func = getattr(toolbox, tool_name)`，万一有恶意用户通过 Prompt 注入攻击，诱导大模型输出 `"__init__"` 或 `"_delete_database"`（内部敏感方法），反射执行器在不做防守时会直接执行这些敏感方法，导致内存泄漏、安全穿透甚至程序崩溃。

### 第一步：建立类比锚点
*   **生活类比**：**商场电话内线拨号**。
    *   **没有反射**：前台脑子里记死了所有柜台的转接电话。商场一旦新增柜台，前台就得去培训更新脑子里的代码。
    *   **直接反射（getattr）**：前台直接根据电话薄名字转接（如“餐厅”、“影院”）。
    *   **安全反射防卫**：电话薄中被拉上了“安全警戒线”。所有以 `_` 开头的号码（如总经理私人专线、保安初始化内线）禁止外部拨打，非柜台电话（如静态常量广告牌）禁止转接。

### 第二步：最小但真实的代码与单步调试
```python
from typing import Any

class SafeToolbox:
    def __init__(self):
        self.version = "v1"  # 常量属性，非 Callable

    def get_weather(self, city: str) -> str:
        return f"{city} 天气晴朗。"

    def _secret_auth(self):
        return "管理员密码已泄露！"

def safe_run(toolbox: Any, name: str, **kwargs) -> Any:
    # 规则 1：拦截下划线开头的所有属性
    if name.startswith("_"):
        raise PermissionError("禁止调用私有方法")
    # 规则 2：反射属性
    attr = getattr(toolbox, name, None)
    if attr is None:
        raise AttributeError("工具不存在")
    # 规则 3：可调用校验
    if not callable(attr):
        raise TypeError("获取的属性不是可执行函数")
        
    return attr(**kwargs)
```

### 第三步：主动破坏与报错记录
1. **输入私有方法**：调用 `safe_run(tb, "_secret_auth")`。
   * **报错信息**：`PermissionError: 禁止调用私有方法`。
2. **输入非可调用属性**：调用 `safe_run(tb, "version")`。
   * **报错信息**：`TypeError: 获取的属性不是可执行函数`。
3. **输入不存在方法**：调用 `safe_run(tb, "hack")`。
   * **报错信息**：`AttributeError: 工具不存在`。

### 第四步：默写
*   **行动**：写出带私有前缀拦截、`getattr` 安全获取、`callable` 校验及 `TypeError` 包装的 `safe_call` 代码。

### 第五步：阅读优秀项目
在 `LiteLLM` 或 `AutoGen` 等工具路由执行框架中，大模型触发的具体 Python 函数都要经过一套严格的类型签名解析与权限沙箱过滤（Sandbox Filter）。确保传入的参数经过强类型验证，调用的函数名字绝对在“公开工具白名单”之内。

---

## 知识点三：面向 Agent 架构的设计模式集成（单例、工厂、观察者）

### 第零步：找到最小痛点场景
> **没有它，我的代码会在哪里卡住？**
1.  **单例问题**：`LLMClient` 负责与 OpenAI 或本地大模型通过 HTTPS 交互。如果每次请求或创建新 Agent 时都重新执行 `client = LLMClient()` 并初始化，系统会频繁进行 TCP 三次握手和 SSL 证书验证，直接导致响应卡顿、接口延迟。
2.  **观察者问题**：Agent 在执行长链思考时，我们需要控制台高亮彩色打印、需要将运行日志同步保存到本地文件、还需要通过 WebSockets 实时将数据流推给前端网页。如果把这三套打印、存盘、发送的网络代码都写死在 Agent 类的核心循环中，Agent 类会迅速退化成一个无法测试和重构的“面条类”。

### 第一步：建立类比锚点
*   **单例模式**：**整栋大楼唯一的自来水主管**。不论你是厨房用水、卫生间用水，都是去接这同一根主管的自来水，而不是每个房间重新从地底钻一口新井。
*   **观察者模式**：**电台广播**。
    *   Agent 是“电台广播台（Subject）”，它在思考和执行工具时，只管向外播报“我正在思考”、“我调用了搜索工具”（广播事件）。
    *   控制台打印、文件日志写入、前端 UI（Observers）都是订阅了这个频道的“收音机”。它们各自做自己的事（打印、写盘、画UI），广播台本身完全不需要知道是谁在听。

### 第二步：最小但真实的代码与单步调试
```python
import threading
from typing import List

# ==========================================
# 1. 线程安全单例模式
# ==========================================
class LLMClient:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

# ==========================================
# 2. 观察者模式解耦
# ==========================================
class Observer:
    def update(self, state: str) -> None: ...

class ConsoleObserver(Observer):
    def update(self, state: str) -> None:
        print(f"[Console Log] {state}")

class AgentSubject:
    def __init__(self):
        self._observers: List[Observer] = []

    def attach(self, obs: Observer):
        self._observers.append(obs)

    def notify(self, state: str):
        for obs in self._observers:
            try:
                obs.update(state)
            except Exception as e:
                # 隔离防护：单个观察者挂掉，不阻断核心
                print(f"观察者出错被防卫隔离: {e}")
```

### 第三步：主动破坏与报错记录
1. **多线程并发测试单例**：使用 100 个线程同时尝试 `LLMClient()` 获取实例，断言其 `id` 地址是否一致。若去掉 `_lock` 会发现极端高并发时可能会产生不同的内存地址对象（见下文加餐）。
2. **观察者执行出错**：在 `ConsoleObserver` 中故意抛出异常。如果没有 `Subject` 的 `try-except` 包裹，整个 Agent 执行流在运行到一半广播状态时会直接崩掉中断。
   * **报错信息**：`RuntimeError / ZeroDivisionError` 截断核心推理。
   * **防卫措施**：`notify` 中对单次通知调用进行 `try-except` 并记录日志。

### 第四步：默写
*   **行动**：关掉所有参考，闭卷手写经典的 `Subject/Observer` 绑定以及多线程单例的初始化。

### 第五步：阅读优秀项目
*   **LangChain Callbacks**：LangChain 的核心逻辑与外围处理完全是通过观察者模式实现解耦的。其 `CallbackManager` 持有一系列的 `BaseCallbackHandler`。在 LLM 启动、报错、结束时，分别向观察者发送 `on_llm_start`、`on_tool_error` 等状态包。
*   **AutoGen Event System**：通过统一的 Event Hub 订阅，极度优美地解耦了 Agent 之间的会话流和 UI 可视化展示。

---

## 加餐知识点：多线程单例穿透与双重检查锁定 (DCL) 机制

在单线程环境下，我们实现单例非常简单：
```python
class EasySingleton:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

### 为什么在多线程环境下会失效（穿透）？
在并发环境下，如果有 2 个以上的线程同时执行到 `if cls._instance is None:`：
1. 线程 A 判断为 `True`，准备开始创建实例，但此时 CPU 时间片用完了，线程 A 处于挂起等待状态；
2. 线程 B 抢占 CPU，执行到这里，由于线程 A 还没来得及对 `_instance` 赋值，因此线程 B 也判断为 `True`，随即进入创建逻辑并返回了 **实例 B**；
3. 线程 A 重新拿回 CPU 控制权，继续执行创建，返回了 **实例 A**。
*   **后果**：全局一共生成了两个不同的实例，单例原则破产！

### 解决方案：双重检查锁定 (Double-Checked Locking, DCL)
为了防止这一穿透，我们必须在多线程中引入 `Lock` 锁：
```python
class SafeSingleton:
    _instance = None
    _lock = threading.Lock()  # 全局线程锁

    def __new__(cls):
        # 第一次判定 (无锁状态下进行)：
        # 如果已经实例化过了，直接返回，避免每次获取单例时都要加锁竞争，大幅提高高并发性能。
        if cls._instance is None:
            # 加锁锁定临界区：
            with cls._lock:
                # 第二次判定 (有锁状态下进行)：
                # 这是为了防止线程 A 和线程 B 同时穿透了第一层判定，
                # 在排队等待获取锁的过程中，当第一个拿到锁的线程创建完毕释放锁后，
                # 后面排队进入临界区的线程可以通过第二层判断直接获取已建好的实例，从而避免重复创建。
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**双重锁定的精髓**：
1. **外层 `if`**：过滤掉绝大部分已实例化后的访问请求，避免不必要的加锁开销（因为加锁非常消耗 CPU 周期）；
2. **内层 `if`**：应对极端情况下初始阶段的并发穿透，守护临界区，锁死唯一生成权。
这是高并发工业级系统下实现全局单例的标准金律。

---

## 🚀 开源项目深度剖析：优秀设计模式与反射机制的真实示例

在真实的工业级 AI 智能体框架中，Day 5 学习的这些知识点是如何被运用的？我们来看看 **LangChain** 与 **AutoGen** 的源码设计与精炼示例。

### 1. LangChain Callbacks 机制中的“防崩溃观察者模式”

#### 💡 工程背景
在 LangChain 中，执行一个链（Chain）会经过很多步骤（如 LLM 开始、LLM 结束、Tool 开始、Tool 结束等）。如果将日志打点、数据流推送（如 Gradio/Streamlit UI 刷新）、数据库 Trace 记录等逻辑直接写在 Chain 的运行流程里，代码会高度耦合。
因此，LangChain 采用**观察者模式**：定义了 `BaseCallbackHandler`（观察者协议），并由 `CallbackManager`（广播主体）分发状态。

#### 🛠️ 真实精炼示例
以下是高度模拟 LangChain Callbacks 核心机制的代码，重点展示了它是如何**在广播中对观察者进行异常防卫隔离**的：

```python
import sys
from typing import List, Any, Dict

# 观察者协议 (Protocol)
class BaseCallbackHandler:
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        """LLM 开始推理时的回调"""
        ...
    def on_tool_start(self, tool_name: str, input_str: str, **kwargs: Any) -> None:
        """工具开始执行时的回调"""
        ...

# 具体的观察者 A：本地控制台打印
class ConsoleCallbackHandler(BaseCallbackHandler):
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        print(f"\033[92m[Console] LLM 开始推理，提示词: {prompts}\033[0m")

# 具体的观察者 B：用于 Trace 日志上传的处理器（故意模拟故障）
class CloudTraceCallbackHandler(BaseCallbackHandler):
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        # 模拟因为网络或鉴权失败抛出异常
        raise ConnectionRefusedError("[CloudTrace] 上传 Trace 失败，API 鉴权失效！")

# 广播主体 (Subject)
class CallbackManager:
    def __init__(self, handlers: List[BaseCallbackHandler]) -> None:
        self.handlers = handlers

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        """广播状态，对每一个观察者做单独的防崩溃拦截"""
        for handler in self.handlers:
            try:
                handler.on_llm_start(serialized, prompts, **kwargs)
            except Exception as e:
                # 异常隔离：不能因为上传 Trace 失败，就把用户的核心大模型会话流程给整崩溃了！
                print(f"[警告] Callback Handler {handler.__class__.__name__} 执行出错，已隔离拦截。 详情: {e}", 
                      file=sys.stderr)
```

#### 🔍 核心讲解
*   **异常沙箱**：在 `CallbackManager` 的循环中，每一次对 `handler` 的调用都单独用 `try-except` 包裹。这样即使外置的监控插件（如 `CloudTraceCallbackHandler`）因为断网崩溃，控制台日志打印依然能正常工作，核心 LLM 调用更不会受到丝毫影响，提供了工业级的容灾能力。

---

### 2. AutoGen 中的“反射路由”与“参数安全自动强转”

#### 💡 工程背景
大模型生成 Function Calling 指令后，框架需要通过函数名字符串（如 `"calculate"`）定位到具体的 Python 函数，并自动把 LLM 输出的字符串参数转化为 Python 对应函数的强类型入参。
这其中有两大痛点：
1. **安全性**：防止 LLM 传错属性或调用内部非公开方法。
2. **类型自动映射**：LLM 输出的参数全是文本，如何自动强转为函数签名上指定的 `int`、`float` 等类型？

#### 🛠️ 真实精炼示例
以下是高度模拟 AutoGen 中工具反射路由与参数强转换的核心逻辑：

```python
import json
import inspect
from typing import Callable, Dict, Any, get_type_hints

# 1. 定义两个真实的工具函数
def calculate_tax(income: float, tax_rate: float = 0.1) -> float:
    """计算个人所得税"""
    return income * tax_rate

def search_wikipedia(query: str, limit: int = 3) -> str:
    """查询维基百科"""
    return f"维基百科检索关键词: '{query}', 返回前 {limit} 条结果。"


# 2. 具备自动参数转换的安全反射调度器
class AutoGenToolRegistry:
    def __init__(self) -> None:
        # 用白名单方式存储注册的公开工具，阻断对私有方法、魔法方法的反射攻击
        self._registry: Dict[str, Callable[..., Any]] = {}

    def register_tool(self, func: Callable[..., Any]) -> None:
        self._registry[func.__name__] = func

    def execute_tool_call(self, tool_name: str, arguments_json: str) -> Any:
        # A. 白名单安全过滤：限制只能调用已显式注册在注册表中的工具，杜绝 getattr 穿透
        if tool_name not in self._registry:
            raise KeyError(f"拒绝调用: 未注册的工具方法 '{tool_name}'。")

        target_func = self._registry[tool_name]
        raw_args = json.loads(arguments_json)  # 示例: {"income": "50000", "tax_rate": "0.12"}
        
        # B. 参数签名内省与自动转换类型
        sig = inspect.signature(target_func)
        type_hints = get_type_hints(target_func)
        validated_args = {}

        for param_name, param in sig.parameters.items():
            if param_name in raw_args:
                val = raw_args[param_name]
                # 获取函数定义的强类型提示 (如 float, int)
                expected_type = type_hints.get(param_name, str)
                
                # 自动将大模型返回的字符串强转为函数所要求的真实类型
                try:
                    validated_args[param_name] = expected_type(val)
                except (ValueError, TypeError) as e:
                    raise TypeError(f"工具 '{tool_name}' 参数 '{param_name}' 类型强转失败，"
                                    f"期望: {expected_type.__name__}, 得到的值: '{val}'。")
            elif param.default == inspect.Parameter.empty:
                # 缺失必填参数
                raise ValueError(f"缺少必填参数: '{param_name}'")

        # C. 安全执行
        return target_func(**validated_args)

# 模拟大模型的 Tool Call 输出
if __name__ == "__main__":
    registry = AutoGenToolRegistry()
    registry.register_tool(calculate_tax)
    registry.register_tool(search_wikipedia)

    # 模拟大模型输出的 JSON 参数 (全是字符串类型的数值)
    mock_json = '{"income": "120000.50", "tax_rate": "0.15"}'
    result = registry.execute_tool_call("calculate_tax", mock_json)
    print(f"安全反射与自动转换执行结果: {result} (类型: {type(result).__name__})")
```

#### 🔍 核心讲解
*   **白名单防卫 (Registry 模式)**：相比于直接 `getattr(object, tool_name)`，工业级框架更喜欢通过一个 `_registry` 字典建立工具白名单。只有显式注册的函数才能被调用，从根本上杜绝了对系统内部敏感对象或未授权方法的反射攻击。
*   **反射内省 (`inspect.signature` & `get_type_hints`)**：这是 Python 反射机制中非常强大的工具。它可以“看穿”函数的参数列表与类型声明。通过提取声明类型（如 `float`），执行器可以安全地执行 `float("120000.50")`，屏蔽了由大模型返回纯文本参数导致的参数类型不匹配报错。

