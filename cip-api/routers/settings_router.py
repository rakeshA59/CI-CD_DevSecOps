"""
Settings Router – infra providers (AWS / Azure / GCP credentials) and the dev / test / prod environments.

Secret fields are encrypted (utils/secret_box) and never returned: the UI gets `saved: true` instead of a value.
Sending an empty secret keeps the saved one. Today the pipeline deploys to local Docker (dev + the UAT deploy for
test); the cloud credentials and the prod environment are recorded for the cloud-deploy stage.
"""

import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from llmapi.llm_provider import PROVIDERS
from repositories.pipeline_repository import PipelineRepository
from utils.secret_box import seal, unseal

router = APIRouter(prefix="/settings", tags=["Settings"])

#            name                 label                                   secret
INFRA = {
    "aws": ("AWS", [("access_key_id", "Access key ID", True), ("secret_access_key", "Secret access key", True),
                    ("session_token", "Session token (optional)", True), ("region", "Region (e.g. eu-west-1)", False),
                    ("role_arn", "IAM role ARN to assume (optional)", False)]),
    "azure": ("Azure", [("tenant_id", "Tenant ID", False), ("client_id", "Client (app) ID", False),
                        ("client_secret", "Client secret", True), ("subscription_id", "Subscription ID", False),
                        ("location", "Location (e.g. westeurope)", False)]),
    "gcp": ("Google Cloud", [("project_id", "Project ID", False), ("region", "Region (e.g. europe-west1)", False),
                             ("service_account_json", "Service account key (JSON)", True)]),
}
ENV_FIELDS = [("target", "Deploy target", False), ("infra_provider", "Infra provider", False),
              ("registry", "Image registry", False), ("base_url", "Base URL", False),
              ("cluster", "Cluster / service name", False), ("namespace", "Namespace / resource group", False),
              ("env_vars", "Environment variables (KEY=value, one per line)", True)]
TARGETS = ["local_docker", "kubernetes", "aws_ecs", "azure_container_apps", "gcp_cloud_run", "vm"]
ENVS = {"dev": ("Dev environment", "used now – the pipeline's 'Deploy (dev)' step (local Docker)", "local_docker"),
        "test": ("Test environment (UAT)", "used now – the UAT deploy after the approval (local Docker)", "local_docker"),
        "prod": ("Prod environment", "recorded – used when the cloud deploy stage is added", "kubernetes")}


SONAR = [("sonar_host_url", "SonarQube server URL (e.g. http://localhost:9000)", False), ("sonar_token", "SonarQube token", True)]
FROM_SETTINGS: set[str] = set()                 # variables that came from Settings (not from .env)


def saved_groups() -> dict[str, list]:
    """Settings key → its fields: the SonarQube connection and every LLM provider added with "+ Add model"."""
    return {"scanner:sonarqube": SONAR, **{f"llm:{pid}": p["fields"] for pid, p in PROVIDERS.items() if p.get("fields")}}


async def load_saved_env() -> None:
    """Make what was saved in Settings visible as environment variables (API process + the MCP servers it starts),
    so the scanners and the LLM provider read it like .env. A value in .env wins; a removed value is dropped."""
    repo, wanted = PipelineRepository(), {}
    for key, fields in saved_groups().items():
        saved = await repo.get_setting(key, {}) or {}
        for name, _, secret in fields:
            if saved.get(name):
                wanted[name] = unseal(saved[name]) if secret else saved[name]
    for name in FROM_SETTINGS - wanted.keys():
        os.environ.pop(name, None)
        FROM_SETTINGS.discard(name)
    for name, value in wanted.items():
        if name in FROM_SETTINGS or not (os.getenv(name) or os.getenv(name.upper())):
            os.environ[name] = value
            FROM_SETTINGS.add(name)


class Values(BaseModel):
    values: Dict[str, str] = {}


def _view(fields: list, saved: dict) -> list[dict]:
    return [{"name": n, "label": label, "secret": secret, "saved": bool(saved.get(n)),
             "value": "" if secret else saved.get(n, "")} for n, label, secret in fields]


def _merge(fields: list, saved: dict, values: dict) -> dict:
    out = dict(saved)
    for n, _, secret in fields:
        v = (values.get(n) or "").strip()
        if secret:
            if v:
                out[n] = seal(v)                     # empty = keep the saved secret
        else:
            out[n] = v
    return out


@router.get("")
async def get_settings() -> Any:
    repo = PipelineRepository()
    infra = {k: {"label": label, "fields": _view(fields, await repo.get_setting(f"infra:{k}", {}) or {})}
             for k, (label, fields) in INFRA.items()}
    envs = {}
    for k, (label, used, target) in ENVS.items():
        saved = await repo.get_setting(f"env:{k}", None) or {"target": target}
        envs[k] = {"label": label, "used": used, "fields": _view(ENV_FIELDS, saved)}
    return {"sonarqube": _view(SONAR, await repo.get_setting("scanner:sonarqube", {}) or {}),
            "infra": {"selected": await repo.get_setting("infra:selected", ""), "providers": infra},
            "environments": envs, "targets": TARGETS, "providers": ["none", *INFRA]}


@router.put("/sonarqube")
async def save_sonarqube(body: Values) -> Any:
    repo = PipelineRepository()
    saved = _merge(SONAR, await repo.get_setting("scanner:sonarqube", {}) or {}, body.values)
    await repo.set_setting("scanner:sonarqube", saved)
    await load_saved_env()                                 # used from the next scan on
    return {"saved": "sonarqube"}


@router.put("/infra/{provider}")
async def save_infra(provider: str, body: Values) -> Any:
    if provider not in INFRA:
        raise HTTPException(status_code=400, detail=f"unknown provider {provider}")
    repo = PipelineRepository()
    saved = await repo.get_setting(f"infra:{provider}", {}) or {}
    await repo.set_setting(f"infra:{provider}", _merge(INFRA[provider][1], saved, body.values))
    await repo.set_setting("infra:selected", provider)
    return {"saved": provider}


@router.delete("/infra/{provider}")
async def delete_infra(provider: str) -> Any:
    if provider not in INFRA:
        raise HTTPException(status_code=400, detail=f"unknown provider {provider}")
    repo = PipelineRepository()
    await repo.set_setting(f"infra:{provider}", {})
    if await repo.get_setting("infra:selected", "") == provider:
        await repo.set_setting("infra:selected", "")
    return {"removed": provider}


@router.put("/environments/{name}")
async def save_environment(name: str, body: Values) -> Any:
    if name not in ENVS:
        raise HTTPException(status_code=400, detail=f"unknown environment {name}")
    repo = PipelineRepository()
    saved = await repo.get_setting(f"env:{name}", {}) or {}
    await repo.set_setting(f"env:{name}", _merge(ENV_FIELDS, saved, body.values))
    return {"saved": name}
