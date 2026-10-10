"""Reasoning modes: the model and sampling temperature one persona call runs under.

A prediction runs every persona under every selected mode. Modes are collapsed
back into one view per persona by `confidence_score.aggregate`, so adding modes
adds samples, not weight.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_STRONG_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True)
class ReasoningMode:
    name: str
    model: str | None = None  # None: the client's default model
    temperature: float | None = None  # None: the provider's default


DEFAULT_MODE = ReasoningMode("default")

# Preset name -> mode names. "default" is exactly the pre-modes behaviour.
PRESETS: dict[str, tuple[str, ...]] = {
    "default": ("default",),
    "temps": ("t0.2", "t0.7", "t1.0"),  # same model, three temperatures
    "models": ("default", "strong"),  # two models, default temperature
    "full": ("base-t0.2", "base-t1.0", "strong-t0.2", "strong-t1.0"),
}


def catalog() -> dict[str, ReasoningMode]:
    """Every named mode. Read at call time so `.env` has been loaded."""
    strong = os.getenv("GEMINI_MODEL_STRONG") or DEFAULT_STRONG_MODEL
    modes = [
        DEFAULT_MODE,
        ReasoningMode("strong", strong),
        *(ReasoningMode(f"t{t}", None, float(t)) for t in ("0.2", "0.7", "1.0")),
        *(
            mode
            for t in (0.2, 1.0)
            for mode in (
                ReasoningMode(f"base-t{t}", None, t),
                ReasoningMode(f"strong-t{t}", strong, t),
            )
        ),
    ]
    return {m.name: m for m in modes}


def resolve_modes(spec: str | None) -> tuple[ReasoningMode, ...]:
    """`spec` is a preset or a comma-separated list of presets and mode names."""
    known = catalog()
    names: list[str] = []
    for token in (spec or "default").split(","):
        token = token.strip()
        if not token:
            continue
        if token in PRESETS:
            names.extend(PRESETS[token])
        elif token in known:
            names.append(token)
        else:
            options = ", ".join(sorted({*PRESETS, *known}))
            raise ValueError(f"Unknown mode {token!r}; choose from: {options}")
    unique = list(dict.fromkeys(names))
    if not unique:
        raise ValueError("No modes selected")
    return tuple(known[n] for n in unique)
