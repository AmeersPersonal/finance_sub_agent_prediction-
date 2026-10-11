"""Combine persona views into one call.

Each persona puts its conviction (0-1) behind one direction. A persona that
ran under several reasoning modes is collapsed first (mean conviction per
direction across its modes). Personas are then averaged within each strategy
and strategies across each other, so a strategy with more age bands, or a
persona sampled more often, doesn't get more say. Net score = up mass - down
mass.

    |net| >= FLAT_BAND               -> up / down, confidence = |net|
    otherwise, flat mass is largest  -> flat, confidence = flat mass
    otherwise                        -> unclear (personas split, or lean only weakly)

"flat" means the personas expect the price to stay inside the flat band;
"unclear" means they don't agree on anything. The two used to be conflated.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ai.schemas import Call, PersonaResult, PersonaView

FLAT_BAND = 0.15  # |net score| below this isn't a directional call
DIRECTIONS = ("up", "down", "flat")

# strategy -> persona id -> that persona's views, one per reasoning mode
Groups = dict[str, dict[str, list[PersonaView]]]


@dataclass(frozen=True)
class Aggregate:
    direction: Call
    confidence: float
    net_score: float  # -1 (every persona max-conviction down) to +1
    agreement: float  # strategy-balanced share of personas matching the call; 0 if unclear
    by_strategy: dict[str, float]  # each strategy's own net score
    stability: float = 0.0  # share of persona-mode samples matching the call; 0 if unclear
    by_mode: dict[str, float] | None = None  # net score had only that mode voted


def _group(results: Sequence[PersonaResult]) -> Groups:
    groups: Groups = defaultdict(lambda: defaultdict(list))
    for r in results:
        if r.view is not None:
            groups[r.strategy][r.persona_id].append(r.view)
    return groups


def _persona_mass(views: list[PersonaView]) -> dict[str, float]:
    return {
        d: sum(v.conviction for v in views if v.direction == d) / len(views) for d in DIRECTIONS
    }


def _persona_direction(views: list[PersonaView]) -> str:
    """The direction carrying the most conviction across a persona's modes; ties go
    to the most frequent direction, then up/down/flat order."""
    mass = _persona_mass(views)
    counts = Counter(v.direction for v in views)
    return max(DIRECTIONS, key=lambda d: (mass[d], counts[d]))


def _strategy_mass(personas: dict[str, list[PersonaView]], direction: str) -> float:
    return sum(_persona_mass(v)[direction] for v in personas.values()) / len(personas)


def _shares(groups: Groups, strategy_weights: Mapping[str, float] | None) -> dict[str, float]:
    weights = {s: (strategy_weights or {}).get(s, 1.0) for s in groups}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Strategy weights must sum to a positive number")
    return {s: w / total for s, w in weights.items()}


def _net(groups: Groups, share: Mapping[str, float]) -> float:
    return sum(
        share[s] * (_strategy_mass(p, "up") - _strategy_mass(p, "down")) for s, p in groups.items()
    )


def aggregate(
    results: Sequence[PersonaResult], strategy_weights: Mapping[str, float] | None = None
) -> Aggregate:
    """Failed persona-mode samples are skipped. Strategies missing from
    `strategy_weights` weigh 1.0."""
    groups = _group(results)
    if not groups:
        raise ValueError("No persona produced a view")

    share = _shares(groups, strategy_weights)
    mass = {
        d: sum(share[s] * _strategy_mass(p, d) for s, p in groups.items()) for d in DIRECTIONS
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
        share[s] * sum(_persona_direction(v) == direction for v in p.values()) / len(p)
        for s, p in groups.items()
    )
    samples = [v for p in groups.values() for views in p.values() for v in views]
    stability = sum(v.direction == direction for v in samples) / len(samples)

    by_mode: dict[str, float] = {}
    for mode in dict.fromkeys(r.mode for r in results if r.view is not None):
        mode_groups = _group([r for r in results if r.mode == mode])
        by_mode[mode] = round(_net(mode_groups, _shares(mode_groups, strategy_weights)), 4)

    return Aggregate(
        direction=direction,
        confidence=round(confidence, 4),
        net_score=round(net, 4),
        agreement=round(agreement, 4),
        by_strategy={
            s: round(_strategy_mass(p, "up") - _strategy_mass(p, "down"), 4)
            for s, p in groups.items()
        },
        stability=round(stability, 4),
        by_mode=by_mode,
    )
