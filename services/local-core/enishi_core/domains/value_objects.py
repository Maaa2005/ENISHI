"""ドメイン横断で使う共通の値オブジェクト。

`schemas/` はこれを再エクスポートしてよいが、`domains` パッケージが `schemas` を
import することはない（依存の向き `schemas -> domains -> services -> models` を保つため）。
"""

from datetime import time

from pydantic import BaseModel, Field, model_validator


class DateRange(BaseModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class TimeRange(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def validate_order(self) -> "TimeRange":
        try:
            start = time.fromisoformat(self.start)
            end = time.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("time range must contain valid times") from exc
        if start >= end:
            raise ValueError("time range start must be before end")
        return self
