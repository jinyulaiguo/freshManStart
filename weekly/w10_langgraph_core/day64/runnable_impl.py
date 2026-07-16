"""
Day 64 参考标准答案：自定义 Runnable 协议组件实现与流式闭环验证

设计意图：
    本模块实现了 `SensitiveWordFilterRunnable` 组件。该组件继承自 LangChain 核心中的 
    `Runnable` 契约，旨在对接收的文本数据进行防御性的类型拦截，并自动将预置的敏感词库进行忽略
    大小写替换。同时对外提供标准的异步处理通道 (`ainvoke`) 和流式输出通道 (`astream`)，
    为下游状态图节点的类型安全性打下底层组件规范基石。

类与函数结构：
    - SensitiveWordFilterRunnable(Runnable[str, str]): 自定义的可运行过滤实体类。
        - __init__(sensitive_words: list[str], replacement: str = "*"): 初始化敏感词表。
        - invoke(input: str, config: RunnableConfig | None = None) -> str: 同步调用接口，调用异步方法。
        - ainvoke(input: str, config: RunnableConfig | None = None) -> str: 核心异步单次调用接口。
        - astream(input: str, config: RunnableConfig | None = None) -> AsyncIterator[str]: 异步流式输出接口。

关键数据流流向：
    1. 外部字符串输入 -> 校验是否为 str (若非，引发 TypeError) -> 剔除首尾空白符。
    2. 使用正则表达式查找匹配的敏感词，忽略大小写，并原地替换为等长 replacement 字符。
    3. 模拟异步并发延迟 0.1s -> ainvoke 返回清洗完毕文本。
    4. astream 底层先拉起 ainvoke 生成净化文本，再使用异步生成器逐字 yield 并带有 0.02s 的流式输出停顿。
"""

import asyncio
import re
from typing import AsyncIterator
from langchain_core.runnables import Runnable, RunnableConfig


class SensitiveWordFilterRunnable(Runnable[str, str]):
    """自定义敏感词拦截可运行组件，完全符合 LangChain Runnable 契约。"""

    def __init__(self, sensitive_words: list[str], replacement: str = "*") -> None:
        """初始化过滤规则与敏感词库。

        Args:
            sensitive_words: 需要被拦截替换的敏感词列表。
            replacement: 用于替换敏感词的占位字符，默认为 '*'。
        """
        # 将输入敏感词统一转换成小写，便于统一大小写匹配
        self.sensitive_words = [word.lower() for word in sensitive_words]
        self.replacement = replacement

    def invoke(self, input: str, config: RunnableConfig | None = None) -> str:
        """同步单次调用接口。

        通过当前运行事件循环，以同步阻塞方式等待异步 ainvoke 完成，以兼容同步 LCEL 链。

        Args:
            input: 待处理的输入文本。
            config: 可运行组件的运行时配置字典。

        Returns:
            过滤替换后的文本。
        """
        # 步骤 1：利用事件循环同步执行异步 ainvoke 方法
        return asyncio.run(self.ainvoke(input, config))

    async def ainvoke(self, input: str, config: RunnableConfig | None = None) -> str:
        """异步单次调用通道，包含防御性校验与过滤替换逻辑。

        Args:
            input: 待处理的输入文本。
            config: 可运行组件的运行时配置字典。

        Returns:
            过滤并处理后的文本。

        Raises:
            TypeError: 当输入参数不是 str 类型时抛出。
        """
        # 步骤 1：防御性类型校验，防止非法数据流入下游节点
        if not isinstance(input, str):
            raise TypeError(f"期望输入类型为 str, 但接收到了 {type(input).__name__}")

        # 步骤 2：去除首尾空格清洗
        purified = input.strip()

        # 步骤 3：遍历敏感词库，执行忽略大小写的正则等长字符替换
        for word in self.sensitive_words:
            # 使用 re.IGNORECASE 实现忽略大小写匹配，并且为了规避正则特殊字符，使用 re.escape
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            # 原地替换为等同于敏感词长度的占位符串
            purified = pattern.sub(self.replacement * len(word), purified)

        # 步骤 4：模拟 0.1 秒的非阻塞并发 I/O 延迟
        await asyncio.sleep(0.1)

        # 步骤 5：返回过滤后的净化文本
        return purified

    async def astream(self, input: str, config: RunnableConfig | None = None) -> AsyncIterator[str]:
        """异步流式输出通道，逐步投递过滤后的字符。

        Args:
            input: 待处理的输入文本。
            config: 可运行组件的运行时配置字典。

        Yields:
            逐步生成并净化的字符片段。
        """
        # 步骤 1：获取完整过滤后的净化文本
        purified_text = await self.ainvoke(input, config)

        # 步骤 2：遍历净化后的文本，逐个字符 yield 产出
        for char in purified_text:
            yield char
            # 步骤 3：每次 yield 之间使用 asyncio.sleep 模拟流式网络传输时延
            await asyncio.sleep(0.02)


if __name__ == "__main__":
    async def main():
        print("====== 开始运行 Day 64 自定义 Runnable 契约标准答案验证 ======\n")
        
        # 实例化自定义的可运行实体，设定拦截词
        filter_runnable = SensitiveWordFilterRunnable(
            sensitive_words=["exploit", "malware", "dangerous"],
            replacement="*"
        )
        
        test_input = "  This is a dangerous exploit and containing malware payload!  "
        print(f"原始测试输入: {repr(test_input)}")
        
        # 1. 验证 ainvoke 接口
        print("\n[测试 1] 正在调用 ainvoke 通道...")
        purified_text = await filter_runnable.ainvoke(test_input)
        print(f"ainvoke 输出结果: {repr(purified_text)}")
        assert purified_text == "This is a ********* ******* and containing ******* payload!"
        print("✅ ainvoke 输出结果与断言一致！")
            
        # 2. 验证 astream 接口
        print("\n[测试 2] 正在调用 astream 流式通道...")
        print("astream 净化输出流: ", end="", flush=True)
        streamed_result = []
        async for chunk in filter_runnable.astream(test_input):
            print(chunk, end="", flush=True)
            streamed_result.append(chunk)
        print("\n流式传输结束。")
        assert "".join(streamed_result) == purified_text
        print("✅ astream 流式拼接结果与 ainvoke 一致！")

        # 3. 验证输入防御性校验拦截
        print("\n[测试 3] 正在验证防御性类型过滤 (传入非法非字符)...")
        try:
            await filter_runnable.ainvoke(12345) # type: ignore
            print("❌ 错误：未成功拦截非法输入类型！")
        except TypeError as e:
            print(f"✅ 成功拦截非法类型输入，抛出预期异常: {e}")
            assert "期望输入类型为 str" in str(e)
            
        print("\n====== Day 64 自定义 Runnable 契约标准答案全部验证通过！ ======")

    # 启动异步自测
    asyncio.run(main())
