"""Classifiers behind one interface: `fit(X, y)`, then `predict_proba(X)` returns an
(n, 3) array in `dataset.CLASSES` order (down, flat, up).

Simplest first (`ml/spec.md`): regularised logistic regression, then LightGBM,
then a small MLP, which trains on the GPU when there is one. Always train the
simpler ones on the same rows as comparators, and prefer the simplest that ties.
X may hold NaN: logistic and the MLP impute training medians, LightGBM
handles it natively. A training set with a single class falls back to the
class frequencies.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
import torch
from torch import nn

# The scorer's 3-way outcome, in predict_proba column order; `ml.dataset` labels with it.
# Defined here, not imported, so `python ml/model.py` runs on its own.
CLASSES = ("down", "flat", "up")
N_CLASSES = len(CLASSES)


def get_device() -> torch.device:
    """CUDA GPU when available, otherwise CPU."""
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Classifier(Protocol):
    name: str

    def fit(self, X: np.ndarray, y: np.ndarray) -> Classifier: ...

    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...


def _all_classes(proba: np.ndarray, classes: Sequence[int]) -> np.ndarray:
    """Columns for the classes a model saw, widened to all three (unseen ones get 0)."""
    full = np.zeros((len(proba), N_CLASSES))
    full[:, np.asarray(classes, dtype=int)] = proba
    return full


class PriorModel:
    """Class frequencies with add-one smoothing: the no-skill reference for log-loss."""

    name = "prior"

    def fit(self, X: np.ndarray, y: np.ndarray) -> PriorModel:
        counts = np.bincount(y, minlength=N_CLASSES) + 1.0
        self.prior_ = counts / counts.sum()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.tile(self.prior_, (len(X), 1))


class LogisticModel:
    """Multinomial logistic regression on standardised features, L2-regularised.
    Small `C` = strong regularisation, the right default for a few hundred rows."""

    name = "logistic"

    def __init__(self, C: float = 0.1) -> None:
        self.C = C

    def fit(self, X: np.ndarray, y: np.ndarray) -> LogisticModel:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self._prior = PriorModel().fit(X, y) if len(np.unique(y)) < 2 else None
        if self._prior is None:
            self._pipeline = make_pipeline(
                SimpleImputer(strategy="median", keep_empty_features=True),
                StandardScaler(),
                LogisticRegression(C=self.C, max_iter=2000),
            ).fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._prior is not None:
            return self._prior.predict_proba(X)
        return _all_classes(self._pipeline.predict_proba(X), self._pipeline.classes_)

    def coefficients(self, feature_names: Sequence[str]) -> dict[str, dict[str, float]]:
        """Feature -> class -> weight per standard deviation (lever 3: which personas
        and strategies the stacker trusts). Empty for the class-frequency fallback."""
        if self._prior is not None:
            return {}
        model = self._pipeline[-1]
        classes = [CLASSES[c] for c in model.classes_]
        coef = model.coef_ if len(classes) > 2 else np.vstack([-model.coef_[0], model.coef_[0]])
        return {
            f: {c: float(coef[k, j]) for k, c in enumerate(classes)}
            for j, f in enumerate(feature_names)
        }


class BoostedTreesModel:
    """LightGBM with shallow trees, row/column subsampling and large leaves: daily
    returns are mostly noise, so the defaults lean hard against overfitting."""

    name = "lightgbm"

    def __init__(
        self,
        n_estimators: int = 200,
        learning_rate: float = 0.03,
        num_leaves: int = 15,
        min_child_samples: int = 100,
        seed: int = 0,
    ) -> None:
        self.params = dict(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
            min_child_samples=min_child_samples,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=seed,
            verbose=-1,
        )

    def fit(self, X: np.ndarray, y: np.ndarray) -> BoostedTreesModel:
        from lightgbm import LGBMClassifier

        self._prior = PriorModel().fit(X, y) if len(np.unique(y)) < 2 else None
        if self._prior is None:
            # A few hundred stacker rows can't fill 100-row leaves; cap at a tenth of the rows.
            leaf = min(self.params["min_child_samples"], max(len(X) // 10, 1))
            self._model = LGBMClassifier(**dict(self.params, min_child_samples=leaf)).fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._prior is not None:
            return self._prior.predict_proba(X)
        return _all_classes(self._model.predict_proba(X), self._model.classes_)


class MLPModel:
    """A small fully connected network (PyTorch), on the GPU when there is one.

    Inputs are median-imputed and standardised with training statistics. The
    last `validation_fraction` of the training rows (the most recent, since rows
    arrive in date order) picks the epoch to stop at; the weights from the best
    validation epoch are kept.
    """

    name = "mlp"

    def __init__(
        self,
        hidden: Sequence[int] = (32, 16),
        dropout: float = 0.1,
        lr: float = 1e-3,
        weight_decay: float = 1e-3,
        epochs: int = 200,
        batch_size: int = 512,
        patience: int = 20,
        validation_fraction: float = 0.2,
        seed: int = 0,
        device: str | torch.device | None = None,
    ) -> None:
        self.hidden, self.dropout = tuple(hidden), dropout
        self.lr, self.weight_decay = lr, weight_decay
        self.epochs, self.batch_size, self.patience = epochs, batch_size, patience
        self.validation_fraction, self.seed = validation_fraction, seed
        self.device = torch.device(device) if device is not None else get_device()

    def _network(self, n_features: int) -> nn.Module:
        layers: list[nn.Module] = []
        width = n_features
        for size in self.hidden:
            layers += [nn.Linear(width, size), nn.ReLU(), nn.Dropout(self.dropout)]
            width = size
        layers.append(nn.Linear(width, N_CLASSES))
        return nn.Sequential(*layers)

    def _tensor(self, X: np.ndarray) -> torch.Tensor:
        filled = np.where(np.isnan(X), self.median_, X)
        return torch.as_tensor((filled - self.mean_) / self.std_, dtype=torch.float32, device=self.device)

    def fit(self, X: np.ndarray, y: np.ndarray) -> MLPModel:
        self._prior = PriorModel().fit(X, y) if len(np.unique(y)) < 2 else None
        if self._prior is not None:
            return self
        torch.manual_seed(self.seed)
        self.seen_ = np.bincount(y, minlength=N_CLASSES) > 0  # unseen classes get 0, as the others
        self.median_ =np.nan_to_num(np.nanmedian(np.where(np.isnan(X).all(axis=0), 0.0, X), axis=0))
        filled = np.where(np.isnan(X), self.median_, X)
        self.mean_, std = filled.mean(axis=0), filled.std(axis=0)
        self.std_ = np.where(std == 0, 1.0, std)

        n_val = int(len(X) * self.validation_fraction) if len(X) >= 100 else 0
        inputs, targets = self._tensor(X), torch.as_tensor(y, dtype=torch.long, device=self.device)
        train_x, train_y = inputs[: len(X) - n_val], targets[: len(X) - n_val]
        val_x, val_y = inputs[len(X) - n_val :], targets[len(X) - n_val :]

        self._net = self._network(X.shape[1]).to(self.device)
        optimiser = torch.optim.AdamW(self._net.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        loss_fn = nn.CrossEntropyLoss()
        generator = torch.Generator(device="cpu").manual_seed(self.seed)
        best_loss, best_state, stale = float("inf"), None, 0
        for _ in range(self.epochs):
            self._net.train()
            order = torch.randperm(len(train_x), generator=generator).to(self.device)
            for start in range(0, len(order), self.batch_size):
                batch = order[start : start + self.batch_size]
                optimiser.zero_grad()
                loss_fn(self._net(train_x[batch]), train_y[batch]).backward()
                optimiser.step()
            if not n_val:
                continue
            self._net.eval()
            with torch.no_grad():
                val_loss = float(loss_fn(self._net(val_x), val_y))
            if val_loss < best_loss - 1e-5:
                best_loss, best_state, stale = val_loss, copy.deepcopy(self._net.state_dict()), 0
            else:
                stale += 1
                if stale >= self.patience:
                    break
        if best_state is not None:
            self._net.load_state_dict(best_state)
        self._net.eval()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._prior is not None:
            return self._prior.predict_proba(X)
        with torch.no_grad():
            proba = torch.softmax(self._net(self._tensor(X)), dim=1).cpu().numpy().astype(float)
        proba[:, ~self.seen_] = 0
        return proba / proba.sum(axis=1, keepdims=True)

    def __getstate__(self) -> dict:
        """Pickle on the CPU so a model trained on a GPU loads on a machine without one."""
        state = self.__dict__.copy()
        if "_net" in state:
            state["_net"] = copy.deepcopy(self._net).cpu()
        state["device"] = None
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self.device = get_device()
        if "_net" in state:
            self._net.to(self.device)


# Simplest first: move down the list only when the one above passed its gate.
MODELS: dict[str, Callable[[], Classifier]] = {
    "logistic": LogisticModel,
    "lightgbm": BoostedTreesModel,
    "mlp": MLPModel,
}


def make_model(name: str) -> Classifier:
    if name not in MODELS:
        raise ValueError(f"unknown model {name!r}; choose from {', '.join(MODELS)}")
    return MODELS[name]()


if __name__ == "__main__":
    device = get_device()
    print(f"torch {torch.__version__}, device: {device}")
    if device.type == "cuda":
        print(torch.cuda.get_device_name(0))
