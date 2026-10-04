"""
LLM Provider.

One place that turns the provider chosen in the UI (or `llm_provider` in .env) into a LangChain chat model.
The .env keys are the same ones sdlc-api uses:

    azure_openai   openai_base_url, openai_api_key, openai_deployment_name, openai_api_version
    openai         openai_api_key, openai_model (openai_base_url optional) – when no deployment name is set
    anthropic      anthropic_api_key, anthropic_deployment_name / anthropic_model, anthropic_base_url (optional)
    gemini         google_api_key, gemini_model
    none           no LLM: agents use their deterministic fallback

Each provider also reads <prefix>_temperature and <prefix>_max_tokens (prefix: openai, anthropic, gemini).
Agents call `await LLMProvider().get_llm(provider)` and then `.bind_tools(...)` / `.with_structured_output(...)`.
"""

import logging
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from core.settings import DEFAULT_LLM_PROVIDER, env

PROVIDERS = {
    "azure_openai": {"label": "Azure OpenAI", "env": ["openai_base_url", "openai_api_key", "openai_deployment_name"],
                     "model_env": "openai_deployment_name"},
    "openai": {"label": "OpenAI", "env": ["openai_api_key", "openai_model"], "model_env": "openai_model"},
    "anthropic": {"label": "Anthropic Claude", "env": ["anthropic_api_key"], "model_env": "anthropic_deployment_name",
                  "default_model": "claude-sonnet-4-5"},
    "gemini": {"label": "Google Gemini", "env": ["google_api_key"], "model_env": "gemini_model",
               "default_model": "gemini-2.5-flash-lite"},
    "none": {"label": "No LLM (rules only)", "env": []},
}


def _num(name: str, default: float) -> float:
    try:
        return float(env(name, default))
    except ValueError:
        return default


def _missing(pid: str) -> list[str]:
    missing = [e for e in PROVIDERS[pid]["env"] if not env(e)]
    # openai_* keys serve Azure and plain OpenAI, as in sdlc-api: a deployment name means Azure OpenAI.
    if pid == "openai" and env("openai_deployment_name"):
        missing.append("openai_deployment_name is set, so use Azure OpenAI")
    return missing


class LLMProvider:
    """Asynchronously configure and return the chat model of a provider."""

    @staticmethod
    def available() -> list[dict]:
        """Every provider with whether its keys are set (key values are never returned)."""
        out = []
        for pid, p in PROVIDERS.items():
            model = env(p["model_env"], p.get("default_model", "")) if "model_env" in p else ""
            if pid == "anthropic":
                model = model or env("anthropic_model", p["default_model"])
            out.append({"id": pid, "label": p["label"], "configured": not _missing(pid), "missing": _missing(pid),
                        "model": model})
        return out

    async def get_llm(self, provider: Optional[str]) -> Optional[BaseChatModel]:
        """Chat model for `provider`, or None for 'none' / missing keys (callers then use their fallback)."""
        provider = (provider or DEFAULT_LLM_PROVIDER or "none").lower()
        if provider not in PROVIDERS or provider == "none":
            return None
        if _missing(provider):
            logging.warning("[LLMProvider] %s selected but not configured (missing: %s) – running without LLM",
                            provider, ", ".join(_missing(provider)))
            return None
        try:
            if provider == "azure_openai":
                from langchain_openai import AzureChatOpenAI

                return AzureChatOpenAI(
                    azure_endpoint=env("openai_base_url"),
                    api_key=env("openai_api_key"),
                    api_version=env("openai_api_version", "2025-04-01-preview"),
                    azure_deployment=env("openai_deployment_name"),
                    temperature=_num("openai_temperature", 0.1),
                    max_tokens=int(_num("openai_max_tokens", 16000)),
                    max_retries=2, timeout=180,
                )
            if provider == "openai":
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=env("openai_model"), api_key=env("openai_api_key"), base_url=env("openai_base_url") or None,
                    temperature=_num("openai_temperature", 0.1), max_tokens=int(_num("openai_max_tokens", 16000)),
                    max_retries=2, timeout=180,
                )
            if provider == "anthropic":
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=env("anthropic_deployment_name") or env("anthropic_model", "claude-sonnet-4-5"),
                    api_key=env("anthropic_api_key"),
                    base_url=env("anthropic_base_url") or env("azure_anthropic_base_url") or None,
                    temperature=_num("anthropic_temperature", 0.1),
                    # capped: the Anthropic SDK refuses very large non-streaming requests; agent replies are short
                    max_tokens=min(int(_num("anthropic_max_tokens", 16000)), 16000),
                    max_retries=2, timeout=300,
                )
            if provider == "gemini":
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(
                    model=env("gemini_model", "gemini-2.5-flash-lite"), google_api_key=env("google_api_key"),
                    temperature=_num("gemini_temperature", 0.1),
                    max_output_tokens=int(_num("gemini_max_tokens", 8192)),
                )
        except Exception:
            logging.exception("[LLMProvider] could not create the %s model", provider)
        return None
