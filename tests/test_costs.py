"""验证费用计算、未知价格和配置输入边界。"""

import pytest
from pydantic import ValidationError

from evodev.config import Settings
from evodev.evaluation.costs import estimate_token_cost


def test_unknown_price_is_not_zero() -> None:
    estimate = estimate_token_cost(100, 20, input_price_per_million=1)
    assert estimate.status == "unconfigured"
    assert estimate.amount is None


def test_cost_retains_pricing_and_currency() -> None:
    estimate = estimate_token_cost(
        100_000,
        50_000,
        input_price_per_million=2,
        output_price_per_million=8,
        currency="USD",
    )
    assert estimate.amount == 0.6
    assert estimate.status == "estimated"
    assert estimate.currency == "USD"
    assert estimate.input_price_per_million == 2


def test_explicit_zero_price_is_valid() -> None:
    estimate = estimate_token_cost(
        100,
        20,
        input_price_per_million=0,
        output_price_per_million=0,
    )
    assert estimate.status == "estimated"
    assert estimate.amount == 0


@pytest.mark.parametrize("price", [-1, float("inf"), float("nan")])
def test_invalid_prices_rejected(price: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_input_price_per_million=price)
    with pytest.raises(ValidationError):
        estimate_token_cost(1, 1, input_price_per_million=price)


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValueError, match="不能为负数"):
        estimate_token_cost(-1, 0)
