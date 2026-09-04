"""验证文本规范化的公开行为。"""

from text_normalizer import slugify


def test_slugify_trims_and_lowercases_text() -> None:
    assert slugify("  Hello World  ") == "hello-world"


def test_slugify_collapses_internal_whitespace() -> None:
    assert slugify("EvoDev   Agent") == "evodev-agent"
