"""
LLM Router – which providers are configured, and the default one chosen in the UI.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from core.settings import DEFAULT_LLM_PROVIDER
from llmapi.llm_provider import PROVIDERS, LLMProvider
from models.pipeline_models import ProviderSelection
from repositories.pipeline_repository import PipelineRepository
from routers.settings_router import FROM_SETTINGS, Values, _merge, _view, load_saved_env

router = APIRouter(prefix="/llm", tags=["LLM"])


@router.get("/providers")
async def list_providers() -> Any:
    """Every provider, whether it is configured (.env or Settings – values never returned), the fields of the
    "+ Add model" form, and the current default."""
    repo = PipelineRepository()
    default = await repo.get_setting("llm_provider", DEFAULT_LLM_PROVIDER)
    out = []
    for p in LLMProvider.available():
        fields = PROVIDERS[p["id"]].get("fields", [])
        saved = await repo.get_setting(f"llm:{p['id']}", {}) or {}
        out.append({**p, "fields": _view(fields, saved),
                    "source": "settings" if any(n in FROM_SETTINGS for n, _, _ in fields) else ".env" if p["configured"] and fields else ""})
    return {"default": default, "providers": out}


@router.put("/providers/{provider}")
async def save_provider(provider: str, body: Values) -> Any:
    """"+ Add model": keys / model of a provider, encrypted in Settings (a value in .env still wins)."""
    fields = (PROVIDERS.get(provider) or {}).get("fields")
    if not fields:
        raise HTTPException(status_code=400, detail=f"unknown provider {provider}")
    repo = PipelineRepository()
    await repo.set_setting(f"llm:{provider}", _merge(fields, await repo.get_setting(f"llm:{provider}", {}) or {}, body.values))
    await load_saved_env()
    return {"saved": provider}


@router.delete("/providers/{provider}")
async def remove_provider(provider: str) -> Any:
    repo = PipelineRepository()
    await repo.set_setting(f"llm:{provider}", {})
    await load_saved_env()
    p = next((x for x in LLMProvider.available() if x["id"] == provider), {})
    if await repo.get_setting("llm_provider", DEFAULT_LLM_PROVIDER) == provider and not p.get("configured"):
        await repo.set_setting("llm_provider", "none")      # never leave an unconfigured provider in use
    return {"removed": provider}


@router.put("/default")
async def set_default_provider(sel: ProviderSelection) -> Any:
    if sel.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unknown provider {sel.provider}")
    p = next(x for x in LLMProvider.available() if x["id"] == sel.provider)
    if not p["configured"] and sel.provider != "none":
        raise HTTPException(status_code=400, detail=f"{p['label']} is not configured – missing {', '.join(p['missing'])}")
    await PipelineRepository().set_setting("llm_provider", sel.provider)
    return {"default": sel.provider}


@router.post("/test")
async def test_provider(sel: ProviderSelection) -> Any:
    """Send one tiny prompt to check the key / deployment works."""
    llm = await LLMProvider().get_llm(sel.provider)
    if llm is None:
        return {"ok": False, "message": "not configured – add its keys with + Add model (or in cip-api/.env)"}
    try:
        reply = await llm.ainvoke("Reply with the single word: ready")
        return {"ok": True, "message": str(reply.content)[:100]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}
