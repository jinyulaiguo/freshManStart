from typing import Any, Dict, Set
import re

class SimpleChain:
    """
    一个工业级微型提示词链对象（LLM Chain）。
    """
    def __init__(self, template: str, temperature: float = 0.7) -> None:
        if not isinstance(template, str):
            raise TypeError("Template must be a string")
        if not template.strip():
            raise ValueError("Template cannot be empty")
            
        self._template = template
        self._expected_variables = set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template))
        self.temperature = temperature  # 触发 setter 校验
        self.__call_count = 0  # 双下划线私有变量，记录调用次数

    @property
    def template(self) -> str:
        return self._template

    @property
    def temperature(self) -> float:
        return self._temperature

    @temperature.setter
    def temperature(self, value: float) -> None:
        if not isinstance(value, (int, float)):
            raise TypeError("Temperature must be a number")
        if not (0.0 <= value <= 2.0):
            raise ValueError("Temperature must be between 0.0 and 2.0")
        self._temperature = float(value)

    @property
    def call_count(self) -> int:
        return self.__call_count

    @property
    def expected_variables(self) -> Set[str]:
        return self._expected_variables

    def __call__(self, inputs: Dict[str, Any]) -> str:
        if not isinstance(inputs, dict):
            raise TypeError("Inputs must be a dictionary")
            
        missing_vars = self._expected_variables - inputs.keys()
        if missing_vars:
            raise ValueError(f"Missing required variables: {missing_vars}")
            
        self.__call_count += 1
        return self._template.format(**inputs)

    def __repr__(self) -> str:
        return f"SimpleChain(template={self._template!r}, temperature={self._temperature}, expected_variables={self._expected_variables})"

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "SimpleChain":
        if not isinstance(config, dict):
            raise TypeError("Config must be a dictionary")
            
        template = config.get("template")
        temperature = config.get("temperature", 0.7)
        return cls(template=template, temperature=temperature) # type: ignore
