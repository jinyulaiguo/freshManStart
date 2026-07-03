"""
设计方案：
- 设计意图：构建类型安全且支持语义校验的工具参数协议模型，供大模型工具接口调用时进行强校验。使用 Pydantic BaseModel、Field、字段校验器与模型联合校验器，拦截越界的请求，防止非法输入传导到底层网络及本地 CPU。
- 类与函数结构：
  - `CalculatorArgs` 类：校验计算器输入 x、y 以及 operator 运算符（白名单校验）。
  - `WeatherArgs` 类：校验天气查询参数，限制查询天数范围为 [1, 7] 且城市名称非空。
  - `ExchangeArgs` 类：校验汇率转换参数，对货币代码进行大写规整，校验金额必须大于 0，且源货币与目标货币不能相同。
- 关键数据流向：
  - 外部传入的 JSON 字符串 -> Pydantic `model_validate_json()` -> 字段级校验器清洗 (field_validator) -> 模型级校验器拦截 (model_validator) -> 输出合法的强类型实参模型。
"""

from pydantic import BaseModel, Field, field_validator, model_validator

class CalculatorArgs(BaseModel):
    """计算器工具入参校验模型"""
    x: float = Field(description="第一个操作数 (浮点数)")
    y: float = Field(description="第二个操作数 (浮点数)")
    operator: str = Field(description="运算符，限定为 '+', '-', '*', '/' 之一")

    @model_validator(mode="after")
    def validate_operator(self) -> "CalculatorArgs":
        valid_ops = {"+", "-", "*", "/"}
        if self.operator not in valid_ops:
            raise ValueError(f"不支持的运算符: '{self.operator}'。目前仅支持: {valid_ops}")
        return self

class WeatherArgs(BaseModel):
    """天气查询工具入参校验模型"""
    city: str = Field(
        description="待查询天气的城市英文或中文拼音名称（如 'Beijing' 或 'Shanghai'）",
        min_length=1
    )
    days: int = Field(
        default=1,
        ge=1,
        le=7,
        description="预测天数，最大支持 7 天"
    )

class ExchangeArgs(BaseModel):
    """汇率转换工具入参校验模型"""
    base_currency: str = Field(description="源货币的三位英文代码（如 USD、EUR、CNY）")
    target_currency: str = Field(description="目标货币的三位英文代码（如 USD、EUR、CNY）")
    amount: float = Field(gt=0, description="待转换的金额，必须大于 0")

    @field_validator("base_currency", "target_currency")
    @classmethod
    def clean_currency_code(cls, v: str) -> str:
        # 去除首尾空格并转换为大写形式
        if not isinstance(v, str):
            raise TypeError("货币代码必须为字符串")
        cleaned = v.strip().upper()
        if len(cleaned) != 3:
            raise ValueError(f"货币代码必须是 3 位 ISO 代码，当前输入为: {v}")
        return cleaned

    @model_validator(mode="after")
    def check_different_currency(self) -> "ExchangeArgs":
        # 相同货币互转在业务上是无意义的，需在校验层直接拦截
        if self.base_currency == self.target_currency:
            raise ValueError(
                f"源货币 '{self.base_currency}' 与目标货币不能相同"
            )
        return self
