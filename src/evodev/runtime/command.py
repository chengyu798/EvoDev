from pydantic import BaseModel


class CommandResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    output_truncated: bool = False
