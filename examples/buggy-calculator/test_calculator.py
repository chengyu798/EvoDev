"""验证计算器的公开行为。"""

from calculator import add


def test_add_returns_sum() -> None:
    assert add(2, 3) == 5


def test_add_supports_negative_number() -> None:
    assert add(-2, 3) == 1
