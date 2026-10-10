"""Data models shared by the agents, the aggregator and the API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Direction = Literal["up", "down", "flat"]
# "unclear": personas split or lean only weakly; distinct from expecting a flat price.
Call = Literal["up", "down", "flat", "unclear"]


class PersonaView(BaseModel):
    """What one persona agent returns. This is also the JSON schema sent to Gemini."""

    direction: Direction = Field(
        description="Expected price move over the horizon; flat means inside the flat band"
    )
    conviction: float = Field(
        ge=0, le=1, description="0 = no conviction, 1 = maximum conviction"
    )
    rationale: str = Field(description="Two or three sentences in this persona's voice")
    key_factors: list[str] = Field(
        description="Up to four data points from the input that drove the view"
    )


class PersonaResult(BaseModel):
    persona_id: str
    strategy: str
    age_band: str
    mode: str = "default"  # the reasoning mode (model + temperature) this view came from
    model: str | None = None
    temperature: float | None = None
    view: PersonaView | None = None
    error: str | None = None


class Prediction(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    ticker: str
    horizon_days: int
    direction: Call
    confidence: float = Field(
        description="Signal strength behind the call, 0-1. Not a calibrated probability."
    )
    net_score: float = Field(description="-1 (all max-conviction down) to +1 (all up)")
    agreement: float = Field(description="Share of personas whose direction matches the call")
    by_strategy: dict[str, float]
    modes: list[str] = Field(default_factory=lambda: ["default"])
    by_mode: dict[str, float] = Field(
        default_factory=dict, description="Net score if only that reasoning mode had voted"
    )
    stability: float | None = Field(
        default=None,
        description="Share of persona-mode samples matching the call; 0 when unclear",
    )
    flat_band_pct: float = Field(description="Moves within +/- this percent count as flat")
    last_price: float
    quote_source: str = Field(
        default="yfinance", description="Where last_price came from: yfinance REST or a live feed"
    )
    data_as_of: str
    next_earnings_date: str | None
    earnings_within_horizon: bool | None
    baselines: dict[str, Direction] = Field(description="Naive calls to score the model against")
    linear_regression: dict[str, Any] | None
    headline_sentiment: dict[str, Any] | None = None
    risk: dict[str, Any] | None = Field(
        default=None, description="ATR-based stop distance and position size for a 1% risk budget"
    )
    features: dict[str, float | None] | None = Field(
        default=None,
        description="Numeric inputs the personas saw, logged to train the stacker (ml/spec.md)",
    )
    generated_at: datetime
    model: str
    prompt_version: str
    personas: list[PersonaResult]
    data_warnings: list[str]
    audit: dict[str, Any] | None = Field(
        default=None,
        description="Company overview, data checks, risk checklist and news digest (audit/)",
    )
