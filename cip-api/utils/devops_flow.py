"""The guided flow's configuration (config/devops_flow.yml): questionnaire + stage catalogue, loaded once."""

from functools import lru_cache
from pathlib import Path

import yaml

FLOW_FILE = Path(__file__).resolve().parents[1] / "config" / "devops_flow.yml"

# Why the steps that are not pipeline stages exist (used by the stage reports)
EXTRA_WHY = {
    "checkout": "Get an exact, isolated copy of the code this run is about (the original is never changed).",
    "plan": "Understand the tech stack – components, languages, build / test commands – so the right tools are used.",
    "questionnaire": "Collect what the code cannot tell: where the pipeline runs, cloud, delivery type, server, tests, approvals.",
    "design": "Derive the stages and tools of this pipeline from the code and the answers.",
}


@lru_cache(maxsize=1)
def flow_config() -> dict:
    return yaml.safe_load(FLOW_FILE.read_text(encoding="utf-8"))


def stage_catalog() -> dict[str, dict]:
    return {s["id"]: s for s in flow_config()["stages"]}


def why_of(step_id: str) -> str:
    """The catalogue's reason for the stage a step belongs to."""
    head = step_id.split(".")[0]
    stage = {"scan": "scan", "security_gate": "security_review", "build": "build_test_package", "test": "build_test_package",
             "test_gate": "build_test_package", "package": "build_test_package", "image": "build_test_package",
             "container_gate": "build_test_package", "release": "release", "deploy": "deploy_dev",
             "functional": "functional_tests", "functional_gate": "functional_tests", "ui_tests": "ui_tests", "ui_gate": "ui_tests", "publish_tests": "publish_tests",
             "approval": "approval", "deploy_uat": "deploy_uat", "report": "report"}.get(head)
    return stage_catalog().get(stage, {}).get("why") or EXTRA_WHY.get(head, "")
