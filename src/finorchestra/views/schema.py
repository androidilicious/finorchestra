"""The structured view object: the only thing an agent is allowed to hand to the allocation engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class View(BaseModel):
    asset: str = Field(description="Asset code as shown in the prompt (masked or real ticker).")
    direction: Literal["overweight", "underweight", "neutral"]
    expected_excess_return_annual: float = Field(
        description="Expected return over cash, per year, e.g. 0.03 for +3%. Sign must match direction."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("expected_excess_return_annual")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(-0.15, min(0.15, float(v)))


class ViewSet(BaseModel):
    regime_assessment: str = Field(default="", description="One sentence on the macro regime.")
    views: list[View] = Field(min_length=1, max_length=10)
    rationale: str = Field(default="", description="Two or three sentences of reasoning.")

    def normalized(self) -> ViewSet:
        """Make signs consistent with directions and drop neutral views with zero magnitude."""
        out = []
        for v in self.views:
            q = v.expected_excess_return_annual
            if v.direction == "overweight":
                q = abs(q)
            elif v.direction == "underweight":
                q = -abs(q)
            else:
                q = 0.0
            out.append(v.model_copy(update={"expected_excess_return_annual": q}))
        return self.model_copy(update={"views": out})


class StanceResult(BaseModel):
    stance: float = Field(ge=-1.0, le=1.0, description="-1 very dovish ... +1 very hawkish")
    key_phrases: list[str] = Field(default_factory=list, max_length=6)
