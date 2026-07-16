"""
Day 64 练习模版：自定义 Runnable 协议组件实现与流式闭环验证

设计意图：
    本模块旨在引导学员通过继承 `Runnable` 基类，深度理解 LangChain 的可运行协议。
    实现一个名为 `SensitiveWordFilterRunnable` 的自定义安全过滤组件，该组件通过重写异步 
    `ainvoke` 与流式生成器 `astream`，对外提供契约一致的异步过滤与流式输出服务。

类与函数结构：
    - SensitiveWordFilterRunnable(Runnable[str, str]): 自定义的可运行过滤组件。
        - __init__(sensitive_words: list[str], replacement: str = "*"): 构造方法。
        - ainvoke(input: str, config: RunnableConfig | None = None) -> str: 核心异步过滤。
        - astream(input: str, config: RunnableConfig | None = None) -> AsyncIterator[str]: 异步流式拦截输出。

关键数据流流向：
    1. 外部数据输入 -> 类型防御校验 -> 去除首尾空格并小写处理。
    2. 针对匹配到的敏感词，根据长度原地替换为 replacement 占位符。
    3. ainvoke 数据通路直接返回整串替换后的文本。
    4. astream 数据通路将替换后的文本切分为逐个字符，通过异步生成器依次 yield 投递出去。
"""

import asyncio
from typing import AsyncIterator
from langchain_core.runnables import Runnable, RunnableConfig

class SensitiveWordFilterRunnable(Runnable[str, str]):
    """自定义敏感词拦截可运行实体，支持异步调用与异步流式输出。"""

    def __init__(self, sensitive_words: list[str], replacement: str = "*") -> None:
        """初始化过滤规则。

        Args:
            sensitive_words: 需要被拦截替换的敏感词列表。
            replacement: 用于替换敏感词的占位字符，默认为 '*'。
        """
        self.sensitive_words = [word.lower() for word in sensitive_words]
        self.replacement = replacement

    def invoke(self, input: str, config: RunnableConfig | None = None) -> str:
        """同步调用方法（必须实现 Runnable 的抽象方法，本练习中可直接通过 asyncio 桥接 ainvoke）。

        Args:
            input: 待处理的输入文本。
            config: 可运行组件的运行时配置字典。

        Returns:
            过滤替换后的文本。
        """
        # 提示：可直接利用事件循环同步拉起 ainvoke
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
        # TODO: 步骤 1：对输入 input 进行严格的防御性类型校验，如果不是字符串，抛出 TypeError
        # TODO: 步骤 2：对输入进行首尾空格清洗
        # TODO: 步骤 3：遍历敏感词库，执行忽略大小写的正则或字符串替换
        # TODO: 步骤 4：模拟 0.1 秒的非阻塞并发 I/O 延迟
        # TODO: 步骤 5：返回过滤后的净化文本
        raise NotImplementedError("TODO: 请实现自定义 Runnable 的 ainvoke 逻辑")

    async def astream(self, input: str, config: RunnableConfig | None = None) -> AsyncIterator[str]:
        """异步流式输出通道，逐步投递过滤后的字符片段。

        Args:
            input: 待处理的输入文本。
            config: 可运行组件的运行时配置字典。

        Yields:
            逐步生成并净化的字符片段。
        """
        # TODO: 步骤 1：调用自身的 ainvoke 方法获取整段净化后的文本
        # TODO: 步骤 2：遍历净化后的文本，逐个字符或按分块 yield 产出
        # TODO: 步骤 3：每次 yield 之间使用 asyncio.sleep 模拟网络流式传输间隔 (例如 0.05s)
        # 注意：此处必须声明为异步生成器 (使用 async for 或直接 yield)
        if False:
            yield "" # 占位用于维持异步生成器语法结构
        raise NotImplementedError("TODO: 请实现自定义 Runnable 的 astream 逻辑")


if __name__ == "__main__":
    async def main():
        print("====== 开始运行 Day 64 自定义 Runnable 契约练习 ======\n")
        
        # 实例化自定义的可运行实体，设定拦截词
        filter_runnable = SensitiveWordFilterRunnable(
            sensitive_words=["exploit", "malware", "dangerous"],
            replacement="*"
        )
        
        test_input = "  This is a dangerous exploit and containing malware payload!  "
        print(f"原始测试输入: {repr(test_input)}")
        
        # 1. 验证 ainvoke 接口
        try:
            print("\n[测试 1] 正在调用 ainvoke 通道...")
            purified_text = await filter_runnable.ainvoke(test_input)
            print(f"ainvoke 输出结果: {repr(purified_text)}")
        except NotImplementedError as e:
            print(f"❌ ainvoke 测试被拦截: {e}")
        except Exception as e:
            print(f"❌ ainvoke 运行发生异常: {e}")
            
        # 2. 验证 astream 接口
        try:
            print("\n[测试 2] 正在调用 astream 流式通道...")
            print("astream 净化输出流: ", end="", flush=True)
            async for chunk in filter_runnable.astream(test_input):
                print(chunk, end="", flush=True)
            print("\n流式传输结束。")
        except NotImplementedError as e:
            print(f"\n❌ astream 测试被拦截: {e}")
        except Exception as e:
            print(f"\n❌ astream 运行发生异常: {e}")

        # 3. 验证输入防御性校验拦截
        try:
            print("\n[测试 3] 正在验证防御性类型过滤 (传入非法非字符)...")
            await filter_runnable.ainvoke(12345) # type: ignore
            print("❌ 错误：未成功拦截非法输入类型！")
        except TypeError as e:
            print(f"✅ 成功拦截非法类型输入，抛出预期异常: {e}")
        except NotImplementedError:
            print("❌ 校验测试被拦截：请先实现 ainvoke 中的防御性校验")
        except Exception as e:
            print(f"❌ 运行发生未预期异常: {type(e).__name__} - {e}")

    # 启动异步测试环境
    asyncio.run(main())
