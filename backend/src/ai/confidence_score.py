"""Combine persona views into one call.

Each persona puts its conviction (0-1) behind one direction. Votes are averaged
within each strategy first and then across strategies, so a strategy with more
age bands doesn't get more say. Net score = up mass - down mass.

    |net| >= FLAT_BAND               -> up / down, confidence = |net|
    otherwise, flat mass is largest  -> flat, confidence = flat mass
    otherwise                        -> unclear (personas split, or lean only weakly)

"flat" means the personas expect the price to stay inside the flat band;
"unclear" means they don't agree on anything. The two used to be conflated.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ai.schemas import Call, PersonaResult, PersonaView

FLAT_BAND = 0.15  # |net score| below this isn't a directional call


@dataclass(frozen=True)
class Aggregate:
    direction: Call
    confidence: float
    net_score: float  # -1 (every persona max-conviction down) to +1
    agreement: float  # strategy-balanced share of personas matching the call; 0 if unclear
    by_strategy: dict[str, float]  # each strategy's own net score


def _mass(views: list[PersonaView], direction: str) -> float:
    return sum(v.conviction for v in views if v.direction == direction) / len(views)


def aggregate(
    results: Sequence[PersonaResult], strategy_weights: Mapping[str, float] | None = None
) -> Aggregate:
    """Personas that errored are skipped. Strategies missing from `strategy_weights`
    weigh 1.0."""
    groups: dict[str, list[PersonaView]] = defaultdict(list)
    for r in results:
        if r.view is not None:
            groups[r.strategy].append(r.view)
    if not groups:
        raise ValueError("No persona produced a view")

    weights = {s: (strategy_weights or {}).get(s, 1.0) for s in groups}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Strategy weights must sum to a positive number")
    share = {s: w / total for s, w in weights.items()}

    mass = {
        d: sum(share[s] * _mass(views, d) for s, views in groups.items())
        for d in ("up", "down", "flat")
    }
    net = mass["up"] - mass["down"]

    direction: Call
    if abs(net) >= FLAT_BAND:
        direction, confidence = ("up" if net > 0 else "down"), abs(net)
    elif mass["flat"] > max(mass["up"], mass["down"]):
        direction, confidence = "flat", mass["flat"]
    else:
        direction, confidence = "unclear", 0.0

    agreement = sum(
        share[s] * sum(v.direction == direction for v in views) / len(views)
        for s, views in groups.items()
    )
    return Aggregate(
        direction=direction,
        confidence=round(confidence, 4),
        net_score=round(net, 4),
        agreement=round(agreement, 4),
        by_strategy={
            s: round(_mass(views, "up") - _mass(views, "down"), 4) for s, views in groups.items()
        },
    )
