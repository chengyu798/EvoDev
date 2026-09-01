from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    resolved: bool
    baseline_passed: bool | None = None
    tests_passed: bool
    review_passed: bool
    changed_files_count: int = Field(ge=0)
    added_lines: int = Field(ge=0)
    deleted_lines: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    duration_ms: int = Field(ge=0)
