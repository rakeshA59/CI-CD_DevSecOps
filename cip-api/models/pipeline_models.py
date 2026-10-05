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
    mode: str = Field("quick", description="quick = fixed flow · guided = questionnaire → derived pipeline → approval → UAT")


class QuestionnaireAnswers(BaseModel):
    answers: dict = Field(default_factory=dict, description="question id -> value (see the run's pending questions)")


class ApprovalDecision(BaseModel):
    decision: str = Field(description="approve | reject")
    by: str = Field("reviewer", max_length=80)
    comment: str = Field("", max_length=500)


class ProviderSelection(BaseModel):
    provider: str
