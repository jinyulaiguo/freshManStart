import pytest
from practice import SimpleChain

def test_basic_chain_call() -> None:
    """测试 SimpleChain 的基本实例化与调用功能"""
    template = "Hello {name}, your task is to {task}."
    chain = SimpleChain(template=template, temperature=0.5)

    # 1. 检查属性初始化
    assert chain.template == template
    assert chain.temperature == 0.5
    assert chain.expected_variables == {"name", "task"}
    assert chain.call_count == 0

    # 2. 正常调用
    inputs = {"name": "Alice", "task": "write python code"}
    result = chain(inputs)
    assert result == "Hello Alice, your task is to write python code."
    assert chain.call_count == 1

    # 3. 再次调用，检查计数器
    chain({"name": "Bob", "task": "run unit tests"})
    assert chain.call_count == 2

def test_temperature_validation() -> None:
    """测试温度参数的防御性校验逻辑"""
    chain = SimpleChain(template="Hello {name}")

    # 1. 设置合法温度
    chain.temperature = 1.5
    assert chain.temperature == 1.5
    
    # 2. 设置边界值
    chain.temperature = 0.0
    assert chain.temperature == 0.0
    chain.temperature = 2.0
    assert chain.temperature == 2.0
    
    # 3. 设置 int 类型应能自动转换为 float
    chain.temperature = 1
    assert isinstance(chain.temperature, float)
    assert chain.temperature == 1.0

    # 4. 触发非法范围校验 (ValueError)
    with pytest.raises(ValueError):
        chain.temperature = -0.1
        
    with pytest.raises(ValueError):
        chain.temperature = 2.1

    # 5. 触发非法类型校验 (TypeError)
    with pytest.raises(TypeError):
        chain.temperature = "hot"  # type: ignore
        
    with pytest.raises(TypeError):
        chain.temperature = None  # type: ignore

def test_read_only_template() -> None:
    """测试模板属性是否具备只读保护，防止被外部非法覆盖"""
    chain = SimpleChain(template="Hello {name}")
    
    with pytest.raises(AttributeError):
        chain.template = "New Template"  # type: ignore

def test_missing_variables() -> None:
    """测试在调用 chain 时传入缺失的占位符变量，是否能正确抛错并提示缺失字段"""
    chain = SimpleChain(template="Generate {item} in {language} format.")
    
    # 1. 缺失 item 和 language
    with pytest.raises(ValueError) as excinfo:
        chain({})
    assert "language" in str(excinfo.value)
    assert "item" in str(excinfo.value)

    # 2. 仅缺失 language
    with pytest.raises(ValueError) as excinfo:
        chain({"item": "json"})
    assert "language" in str(excinfo.value)
    assert "item" not in str(excinfo.value)

    # 3. 传入非法入参类型
    with pytest.raises(TypeError):
        chain("not-a-dict")  # type: ignore

def test_repr_format() -> None:
    """测试 __repr__ 调试输出格式是否规范"""
    chain = SimpleChain(template="Hello {name}", temperature=1.2)
    rep = repr(chain)
    
    # 验证是否符合 "SimpleChain(template='...', temperature=..., expected_variables={...})" 格式
    assert "SimpleChain" in rep
    assert "template='Hello {name}'" in rep
    assert "temperature=1.2" in rep
    assert "expected_variables={'name'}" in rep or "expected_variables=set(['name'])" in rep or "expected_variables=({'name'})" in rep

def test_from_dict_constructor() -> None:
    """测试类方法 from_dict 是否能正常构造实例并执行防御性校验"""
    config = {"template": "Translate {text} to French.", "temperature": 0.3}
    chain = SimpleChain.from_dict(config)
    
    assert chain.template == "Translate {text} to French."
    assert chain.temperature == 0.3
    
    # 异常校验：传入非字典
    with pytest.raises(TypeError):
        SimpleChain.from_dict("not-a-dict")  # type: ignore

def test_private_attribute_mangling() -> None:
    """测试双下划线私有属性是否确实被名称修饰（外部无法直接访问）"""
    chain = SimpleChain(template="Hello {name}")
    
    # 尝试直接访问双下划线的私有计数器，预期抛出 AttributeError
    with pytest.raises(AttributeError):
        _ = chain.__call_count  # type: ignore
    
    # 但它可以通过只读属性 call_count 正常读取
    assert chain.call_count == 0


