from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    id: str
    name: str
    role: str
    prompt_version: str = "1"
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    allowed_tools: list[str] = Field(default_factory=list)
    output_schema: str
    max_tool_calls: int = Field(default=20, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
