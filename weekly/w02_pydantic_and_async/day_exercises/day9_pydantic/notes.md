# Day 9：Pydantic 数据校验与 JSON Schema

本节聚焦于 Pydantic 库在运行时的数据检验拦截、类型自动转换以及如何将其无缝转换为符合大模型 Function Calling 标准的 JSON Schema。

---

## 📖 核心概念讲解

### 1. 什么是 Pydantic 运行时校验？
与 `TypedDict` 等仅在静态检查阶段（IDE 层面）生效的类型注解不同，Pydantic 的 `BaseModel` 在**运行时**对所有传入的数据进行校验拦截与类型转换：
* **数据反序列化校验**：当数据通过 `BaseModel(**dict_data)` 实例化时，Pydantic 会自动遍历所有字段，校验数据是否符合声明的类型。
* **智能类型强制转换（Type Coercion）**：Pydantic 会尝试将兼容的输入转换为声明类型。例如，将字符串 `"123"` 自动转换为整数 `123`，将字符串 `"False"` 自动转换为布尔值 `False`。
* **输入边界防御**：一旦数据不符合类型契约，会立刻抛出 `ValidationError` 异常，阻止脏数据进入下游业务系统。

### 2. 使用 Field 配置字段级元数据
通过 `pydantic.Field`，我们可以为字段附加更丰富的元数据与细粒度的约束规则：
* `default` / `default_factory`：设置字段默认值。
* `description`：提供自然语言描述。**在 Agent 开发中，这个描述极其重要，大模型（LLM）正是通过这个描述理解工具参数的作用。**
* 约束项：如 `min_length` (字符串最小长度)、`gt`/`lt` (数值大于/小于)、`pattern` (正则匹配) 等。

### 3. @field_validator 的作用与使用规范
当内置的约束无法满足业务逻辑时，我们可以使用 `@field_validator` 编写自定义的字段校验器：
* **必须搭配 `@classmethod`**：在 Pydantic V2 中，字段校验器是在实例构建完成前执行的，因此它必须被显式声明为类方法。
* **第一形参必须是 `cls`**，第二形参 `v` 代表被校验的字段值，校验通过后必须 `return v`。
* 如果校验不通过，应抛出 `ValueError` 或 `AssertionError`，Pydantic 会自动将其包装并统一作为 `ValidationError` 抛出。

### 4. 导出 JSON Schema 与 Agent Tool Calling 关联
大模型（如 OpenAI、DeepSeek）的工具调用（Function Calling）功能，要求开发者使用一种符合特定格式的 JSON Schema 来说明工具的名称、描述以及入参结构。
* Pydantic 模型类提供了 `model_json_schema()` 方法，能够自动提取所有字段的类型、默认值、描述信息及约束，生成标准的 JSON Schema。
* 通过简单地对 `model_json_schema()` 的输出进行外层包装，就能直接生成大模型所需的 API 格式，极大简化了手动拼装 JSON schema 的繁琐过程。

### 5. 主流大模型 Function Tool Schema 结构对比

三大主流大模型（OpenAI, Claude, Gemini）在 API 层面接收工具定义时，外层的数据包装结构各有不同，但它们核心的参数描述部分（即 `parameters` 或 `input_schema`）都完全兼容 Pydantic 导出的 JSON Schema：

#### 1. OpenAI 格式
OpenAI 规范已被行业广泛接受为事实标准（如 DeepSeek 等也兼容此格式）：
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "获取指定城市的实时天气信息",
    "parameters": {
      "type": "object",
      "properties": {
        "city": { "type": "string", "description": "城市名称" },
        "date": { "type": "string", "description": "日期 YYYY-MM-DD" }
      },
      "required": ["city", "date"]
    }
  }
}
```

#### 2. Claude (Anthropic) 格式
Anthropic 独立的工具调用格式中，核心参数校验层字段命名为 `input_schema`：
```json
{
  "name": "get_weather",
  "description": "获取指定城市的实时天气信息",
  "input_schema": {
    "type": "object",
    "properties": {
      "city": { "type": "string", "description": "城市名称" },
      "date": { "type": "string", "description": "日期 YYYY-MM-DD" }
    },
    "required": ["city", "date"]
  }
}
```

#### 3. Gemini (Google) 格式
Gemini 接收的是一个工具集列表（`tools`），其中包含 `function_declarations` 数组：
```json
{
  "function_declarations": [
    {
      "name": "get_weather",
      "description": "获取指定城市的实时天气信息",
      "parameters": {
        "type": "object",
        "properties": {
          "city": { "type": "string", "description": "城市名称" },
          "date": { "type": "string", "description": "日期 YYYY-MM-DD" }
        },
        "required": ["city", "date"]
      }
    }
  ]
}
```

#### 4. 工具 Schema 核心参数说明

| 字段名称 | 对应平台 | 类型 | 作用与配置建议 |
| :--- | :--- | :--- | :--- |
| **`name`** | 所有平台 | `string` | **工具名称**。例如 `get_weather`。建议使用下划线命名法（snake_case），命名要具象且具有唯一性，以便大模型准确识别。 |
| **`description`** | 所有平台 | `string` | **工具描述**。例如：`获取指定城市的实时天气信息`。这是大模型判定“何时该调用此工具”的**最核心依据**。必须清晰描述工具的功能、局限性和适用场景。 |
| **`parameters` / `input_schema`** | OpenAI / Claude / Gemini | `object` | **参数定义主体**。其内部结构必须符合标准的 JSON Schema 规范，用以定义入参的属性列表及其类型。 |
| **`type`** | 所有平台参数内部 | `string` | **数据类型声明**。在最外层通常为 `object`。字段级别可以是 `string`, `number`, `integer`, `boolean`, `array` 等。 |
| **`properties`** | 所有平台参数内部 | `object` | **参数字段详情**。其中的每个 Key 对应一个参数名称（如 `city`），每个 Value 包含该参数的类型（`type`）、自然语言描述（`description`）以及其他细粒度校验约束。 |
| **`required`** | 所有平台参数内部 | `array[string]` | **必填参数声明列表**。列出所有没有默认值、大模型必须生成的参数字段名（如 `["city", "date"]`）。若漏掉此项，大模型可能会遗漏传入关键字段。 |

---

## 🛠️ 典型报错与防御性编程

当数据校验失败时，Pydantic 会抛出 `pydantic.ValidationError`。

### 1. 异常结构解析
```python
from pydantic import ValidationError

try:
    WeatherToolArgs(city="", date="2026-07-01")  # city 限制了 min_length=1
except ValidationError as e:
    # errors() 方法返回一个包含所有校验错误的列表
    for error in e.errors():
        print(f"字段: {error['loc']}")
        print(f"错误类型: {error['type']}")
        print(f"错误原因: {error['msg']}")
```

### 2. 生产环境下的防御性编程
在 Agent 接收大模型生成的工具参数时，我们应该总是用 `try-except` 捕获 `ValidationError`：
```python
try:
    # 尝试解析 LLM 的输出参数
    tool_args = WeatherToolArgs.model_validate_json(llm_output_json_str)
except ValidationError as e:
    # 格式化错误并作为 Prompt 返回给大模型，要求其重试并修正参数
    error_message = f"参数校验失败，请修正后重新输出。错误详情: {e.errors()}"
    # ... 将 error_message 反馈给大模型
```

---

## 💡 课后召回问题答案验证

1. **为什么 `@field_validator` 必须配合 `@classmethod`？**
   * 因为校验发生在类实例化（Instance Construction）之前。此时还没有 `self` 实例，只能通过类（`cls`）来进行方法调用。显式使用 `@classmethod` 还能完美避开静态类型检查器（如 MyPy / Pyright）在分析 IDE 自动补全时的类型冲突。
2. **`model_json_schema()` 是所有 Python 类通用的吗？**
   * 否。它是继承了 `pydantic.BaseModel` 的类特有的类方法。普通 Python 类或基础类型需要使用 `pydantic.TypeAdapter` 进行包装转换才能生成 JSON Schema。
