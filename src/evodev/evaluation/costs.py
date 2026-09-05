"""按显式配置的 Token 单价估算费用，不推测供应商账单。"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CostEstimate(BaseModel):
    """保存估算依据，价格未知时金额为空而非零。"""

    status: Literal["estimated", "unconfigured"]
    amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    scope: str = "本次修复运行；不含会话、规划及独立提示词评测"


def estimate_token_cost(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
    currency: str = "CNY",
) -> CostEstimate:
    """按输入与输出分别计费；缓存折扣、税费以供应商账单为准。"""
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError("Token 数量不能为负数")
    estimate = CostEstimate(
        status="unconfigured",
        currency=currency,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
    )
    if input_price_per_million is None or output_price_per_million is None:
        return estimate
    amount = (
        Decimal(prompt_tokens) * Decimal(str(input_price_per_million))
        + Decimal(completion_tokens) * Decimal(str(output_price_per_million))
    ) / Decimal(1_000_000)
    return estimate.model_copy(update={"status": "estimated", "amount": float(amount)})
