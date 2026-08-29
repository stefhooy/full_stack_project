"""The ONE place in the codebase allowed to know that MODEL_PROVIDER exists.

get_llm() returns a LangChain chat model with tools already bindable via
.bind_tools(...). Everything downstream (src/agent/graph.py) just calls
get_llm() and treats the result as "a chat model" — it never branches on
provider. That's the seam: adding Gemini for real later means filling in one
branch here, nothing else in the agent changes.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from src.config import settings


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    provider = settings.model_provider

    if provider == "groq":
        from langchain_groq import ChatGroq

        if not settings.groq_api_key:
            raise RuntimeError(
                "MODEL_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com/keys and put it in .env."
            )
        from pydantic import SecretStr

        return ChatGroq(
            model=settings.groq_model,
            api_key=SecretStr(settings.groq_api_key),
            temperature=temperature,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    if provider == "gemini":
        # Seam reserved for Slice 8 (Gemini as a fallback provider). Not
        # implemented yet — deliberately not adding the langchain-google-genai
        # dependency until this slice actually needs it.
        raise NotImplementedError(
            "MODEL_PROVIDER=gemini is reserved for a later slice. "
            "Install langchain-google-genai and implement this branch when needed."
        )

    raise ValueError(f"Unknown MODEL_PROVIDER: {provider!r}")
