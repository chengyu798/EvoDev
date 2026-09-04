"""提供用于 URL 标识的简单文本规范化。"""

import re


def slugify(value: str) -> str:
    """生成小写且以连字符分隔的 URL 标识。"""
    return re.sub(r"\s+", "-", value)
