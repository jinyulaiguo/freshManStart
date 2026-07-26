from langchain_openai import ChatOpenAI
from src.config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential
from src.infrastructure.observability import get_logger

logger = get_logger("llm_gateway")

def get_llm() -> ChatOpenAI:
    """
    初始化大语言模型 (MiniMax)
    由于 MiniMax 兼容 OpenAI 格式，直接使用 ChatOpenAI。
    内置了基于 Tenacity 的 LangChain 重试机制。
    """
    logger.info("Initializing LLM Model", model=settings.MINIMAX_MODEL)
    return ChatOpenAI(
        model=settings.MINIMAX_MODEL,
        api_key=settings.MINIMAX_API_KEY,
        base_url=settings.MINIMAX_BASE_URL,
        max_retries=3,  # LangChain 内置重试
        timeout=60.0,
        streaming=True
    )

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def safe_llm_invoke(llm: ChatOpenAI, prompt: str):
    """
    提供给非 LangGraph 原生节点的外部安全调用包装
    """
    logger.debug("Invoking LLM with safe gateway", prompt_length=len(prompt))
    return await llm.ainvoke(prompt)
