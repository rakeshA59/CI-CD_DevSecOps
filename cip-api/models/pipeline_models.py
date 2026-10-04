"""Request / response models of the pipeline API."""

from typing import List, Optional

from pydantic import BaseModel, Field


class RunOptions(BaseModel):
    run_tests: bool = True
    containerize: bool = True
    deploy: bool = True
    continue_on_fail: bool = True
    keep_running: bool = False
    scanners: Optional[List[str]] = Field(None, description="scanner names to run; empty = defaults for the repo's languages")


class StartPipelineRequest(BaseModel):
    source: str = Field(description="GitHub URL, org/repo or a local folder path")
    branch: Optional[str] = None
    llm_provider: Optional[str] = Field(None, description="azure_openai | openai | anthropic | gemini | none")
    options: RunOptions = RunOptions()


class ProviderSelection(BaseModel):
    provider: str
