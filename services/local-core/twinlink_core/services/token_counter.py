"""トークン数の決定的近似（twinlink.md §28）。

LLM不使用の決定的近似。ASCII文字は約4文字で1トークン、
非ASCII文字（日本語等）は1文字あたり約2/3トークンとして見積もる。
"""

import json
import math
from typing import Any


def estimate_tokens(text: str) -> int:
    """LLM不使用の決定的近似でトークン数を見積もる。最低1を返す。"""
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_count = len(text) - ascii_count
    estimated = math.ceil(ascii_count / 4) + math.ceil(non_ascii_count * 2 / 3)
    return max(1, estimated)


def estimate_json_tokens(obj: Any) -> int:
    """JSONへ直列化した文字列のトークン数を見積もる。"""
    return estimate_tokens(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
