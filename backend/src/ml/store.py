"""Save and load trained models under `data/models/` (gitignored), each with a
sidecar JSON saying what it was trained on.

Models are pickled (joblib), so only load files this code wrote: unpickling
runs code. Never commit `data/`.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from ml.model import Classifier

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


def git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def save(
    model: Classifier, name: str, meta: dict[str, Any], directory: Path = DEFAULT_DIR
) -> Path:
    """Writes `<name>-<UTC timestamp>.joblib` and a `.json` sidecar beside it; returns
    the model's path. `meta` should say what the rows were (tickers, horizon,
    target, features or columns) and how it scored."""
    directory.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(timezone.utc)
    path = directory / f"{name}-{trained_at:%Y%m%dT%H%M%S%fZ}.joblib"  # sorts by time
    joblib.dump(model, path)
    sidecar = {
        **meta,
        "name": name,
        "model": model.name,
        "file": path.name,
        "trained_at": trained_at.isoformat(),
        "git_revision": git_revision(),
    }
    path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
    return path


def load(path: Path) -> tuple[Classifier, dict[str, Any]]:
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return joblib.load(path), meta


def latest(name: str, directory: Path = DEFAULT_DIR) -> Path | None:
    """The most recently trained `name` model, by the timestamp in its file name."""
    paths = sorted(directory.glob(f"{name}-*.joblib"))
    return paths[-1] if paths else None
