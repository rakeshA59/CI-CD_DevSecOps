"""
LLM Router – which providers are configured, and the default one chosen in the UI.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from core.settings import DEFAULT_LLM_PROVIDER
from llmapi.llm_provider import PROVIDERS, LLMProvider
from models.pipeline_models import ProviderSelection
from repositories.pipeline_repository import PipelineRepository

router = APIRouter(prefix="/llm", tags=["LLM"])


@router.get("/providers")
async def list_providers() -> Any:
    """Every provider, whether its keys are set in .env (values never returned), and the current default."""
    default = await PipelineRepository().get_setting("llm_provider", DEFAULT_LLM_PROVIDER)
    return {"default": default, "providers": LLMProvider.available()}


@router.put("/default")
async def set_default_provider(sel: ProviderSelection) -> Any:
    if sel.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unknown provider {sel.provider}")
    await PipelineRepository().set_setting("llm_provider", sel.provider)
    return {"default": sel.provider}


@router.post("/test")
async def test_provider(sel: ProviderSelection) -> Any:
    """Send one tiny prompt to check the key / deployment works."""
    llm = await LLMProvider().get_llm(sel.provider)
    if llm is None:
        return {"ok": False, "message": "not configured – set its keys in cip-api/.env"}
    try:
        reply = await llm.ainvoke("Reply with the single word: ready")
        return {"ok": True, "message": str(reply.content)[:100]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}
