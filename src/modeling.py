from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.isotonic import IsotonicRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import (
    BLOCK_BOOTSTRAP_BLOCK,
    BOOTSTRAP_ROUNDS,
    CALIBRATION_CV,
    CALIBRATION_METHOD,
    DATA_DIR,
    DEFAULT_FUNDING_RATE_8H,
    FEATURE_COLUMNS,
    FUNDING_SETTLEMENTS_PER_DAY,
    MIN_TRAIN_DAYS,
    MODEL_DIR,
    RANDOM_STATE,
    SLIPPAGE_RATE,
    TAKER_FEE_RATE,
    TEST_BLOCK_DAYS,
    WEEKLY_HORIZON,
)

BACKTEST_PATH = DATA_DIR / "backtest.csv"
WEEKLY_BACKTEST_PATH = DATA_DIR / "backtest_weekly.csv"
PREDICTION_PATH = DATA_DIR / "latest_prediction.json"
MODEL_PATH = MODEL_DIR / "latest_model.joblib"
METADATA_PATH = MODEL_DIR / "metadata.json"
IMPORTANCE_PATH = DATA_DIR / "feature_importance.csv"

COST_MODEL = {
    "taker_fee_rate": TAKER_FEE_RATE,
    "slippage_rate": SLIPPAGE_RATE,
    "funding_settlements_per_day": FUNDING_SETTLEMENTS_PER_DAY,
    "default_funding_rate_8h": DEFAULT_FUNDING_RATE_8H,
    "notes": "100% notional, no leverage; fee and slippage charged on both legs of every position change",
}


def _classifier() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=20,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=RANDOM_STATE,
    )


def _regressor() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=300,
        learning_rate=0.05,
        max_leaf_nodes=15,
        min_samples_leaf=20,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=RANDOM_STATE,
    )


def _logistic() -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, C=0.5, solver="lbfgs")),
        ]
    )


class _ColumnGuard(BaseEstimator, TransformerMixin):
    """Drop columns that are all-NaN or constant within the fitting slice.

    Keeps NaN values intact so HistGradientBoosting can use its native missing
    handling. Median imputation measurably hurt walk-forward accuracy, and HGB
    cannot bin empty/constant columns inside cross-validation folds.
    """

    def fit(self, X, y=None):
        frame = pd.DataFrame(X)
        self.keep_ = [
            col
            for col in frame.columns
            if frame[col].notna().any() and frame[col].nunique(dropna=True) >= 2
        ]
        if not self.keep_:
            self.keep_ = list(frame.columns[:1])
        return self

    def transform(self, X):
        frame = pd.DataFrame(X)
        keep = [col for col in self.keep_ if col in frame.columns]
        if not keep:
            keep = list(frame.columns[:1])
        return frame[keep]


def _hgb_pipeline(model: Any) -> Pipeline:
    return Pipeline(
        [
            ("guard", _ColumnGuard()),
            ("model", model),
        ]
    )


def _classifier_pipeline() -> Pipeline:
    return _hgb_pipeline(_classifier())


def _regressor_pipeline() -> Pipeline:
    return _hgb_pipeline(_regressor())


def _calibration_method() -> str:
    return CALIBRATION_METHOD if CALIBRATION_METHOD in {"sigmoid", "isotonic"} else "sigmoid"


class _TimeSeriesCalibratedClassifier:
    """Probability calibration fitted on expanding-window out-of-fold predictions.

    sklearn's CalibratedClassifierCV uses shuffled CV, which destroys the
    temporal structure of financial data and produced a near-zero/negative
    slope. Here the calibrator only sees predictions made by models trained on
    strictly earlier rows of the same training slice, mirroring deployment and
    keeping the test block untouched.
    """

    def __init__(self, method: str = "sigmoid", n_splits: int = 3):
        self.method = method
        self.n_splits = n_splits

    def fit(self, X, y):
        X = pd.DataFrame(X)
        y = pd.Series(np.asarray(y))
        self.model_ = _classifier_pipeline().fit(X, y)
        n = len(X)
        initial = max(int(n * 0.5), min(100, n - 1))
        folds = max(1, int(self.n_splits))
        fold_size = max(1, (n - initial) // folds)
        preds: list[np.ndarray] = []
        labels: list[np.ndarray] = []
        for i in range(folds):
            train_end = initial + i * fold_size
            test_end = n if i == folds - 1 else initial + (i + 1) * fold_size
            if test_end <= train_end or train_end < 40:
                continue
            model = _classifier_pipeline().fit(X.iloc[:train_end], y.iloc[:train_end])
            preds.append(model.predict_proba(X.iloc[train_end:test_end])[:, 1])
            labels.append(y.iloc[train_end:test_end].to_numpy())
        self.kind_ = "identity"
        if preds:
            p_oof = np.clip(np.concatenate(preds), 1e-6, 1 - 1e-6)
            y_oof = np.concatenate(labels)
            if len(np.unique(y_oof)) > 1:
                if self.method == "isotonic":
                    self.calibrator_ = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                    self.calibrator_.fit(p_oof, y_oof)
                    self.kind_ = "isotonic"
                else:
                    # No intercept: the calibrated curve is monotone and keeps
                    # p=0.5 as its fixed point, so direction decisions are
                    # identical to the raw probability rule.
                    self.linear_ = LogisticRegression(C=1e6, solver="lbfgs", fit_intercept=False)
                    self.linear_.fit(logit(p_oof).reshape(-1, 1), y_oof)
                    if float(self.linear_.coef_[0, 0]) <= 0:
                        self.kind_ = "identity"
                    else:
                        self.kind_ = "sigmoid"
        return self

    def _calibrate(self, prob: np.ndarray) -> np.ndarray:
        prob = np.clip(prob, 1e-6, 1 - 1e-6)
        if self.kind_ == "sigmoid":
            return np.clip(self.linear_.predict_proba(logit(prob).reshape(-1, 1))[:, 1], 1e-6, 1 - 1e-6)
        if self.kind_ == "isotonic":
            return np.clip(self.calibrator_.predict(prob), 1e-6, 1 - 1e-6)
        return prob

    def predict_proba(self, X) -> np.ndarray:
        prob = self.model_.predict_proba(X)[:, 1]
        calibrated = self._calibrate(prob)
        return np.column_stack([1 - calibrated, calibrated])

    def predict(self, X) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _calibrated_classifier() -> _TimeSeriesCalibratedClassifier:
    return _TimeSeriesCalibratedClassifier(method=_calibration_method(), n_splits=CALIBRATION_CV)


def _raw_prob(clf, X: pd.DataFrame) -> np.ndarray | None:
    """Raw (uncalibrated) positive-class probabilities from the fitted base model."""
    try:
        return clf.model_.predict_proba(X)[:, 1]
    except Exception:  # noqa: BLE001
        return None


def _xy(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    target_col: str = "target_return",
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    feature_columns = feature_columns or FEATURE_COLUMNS
    data = df[df[target_col].notna()].copy()
    X = data[feature_columns].astype(float)
    y_dir = (data[target_col] > 0).astype(int)
    y_ret = data[target_col].astype(float)
    return X, y_dir, y_ret


def _active_features(X: pd.DataFrame) -> list[str]:
    """Drop columns that are entirely missing or constant in this training slice."""
    return [col for col in X.columns if X[col].nunique(dropna=True) >= 2]


def _predict_bundle(clf, reg, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    prob = clf.predict_proba(X)[:, 1]
    raw_prob = _raw_prob(clf, X)
    raw = reg.predict(X)
    return prob, raw_prob, raw


def _signed_return(prob: np.ndarray, raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    direction = (prob >= 0.5).astype(int)
    flat = np.isclose(prob, 0.5, atol=1e-12)
    direction[flat] = (raw[flat] >= 0).astype(int)
    clipped = np.clip(raw, -0.15, 0.15)
    absolute = np.abs(clipped)
    absolute = np.where(absolute < 0.001, 0.001, absolute)
    signed = np.where(direction == 1, absolute, -absolute)
    return direction, signed


def walk_forward(
    df: pd.DataFrame,
    min_train: int = MIN_TRAIN_DAYS,
    block: int = TEST_BLOCK_DAYS,
    feature_columns: list[str] | None = None,
    target_col: str = "target_return",
    target_close_col: str = "target_close",
    output_path: Path = BACKTEST_PATH,
    label: str = "daily",
) -> pd.DataFrame:
    feature_columns = feature_columns or FEATURE_COLUMNS
    data = df[df[target_col].notna()].sort_values("date").reset_index(drop=True)
    if len(data) <= min_train + 10:
        raise RuntimeError(f"Not enough training rows for {label}: {len(data)}")
    records: list[dict[str, Any]] = []
    for start in range(min_train, len(data), block):
        train = data.iloc[:start]
        test = data.iloc[start : start + block]
        if test.empty:
            break
        X_train_full, y_dir, y_ret = _xy(train, feature_columns, target_col)
        X_test_full = test[feature_columns].astype(float)
        active = _active_features(X_train_full)
        if not active:
            raise RuntimeError("No usable features in training slice")
        X_train = X_train_full[active]
        X_test = X_test_full[active]
        clf = _calibrated_classifier().fit(X_train, y_dir)
        reg = _regressor_pipeline().fit(X_train, y_ret)
        logit = _logistic().fit(X_train, y_dir)
        prob, raw_prob, raw = _predict_bundle(clf, reg, X_test)
        direction, signed = _signed_return(prob, raw)
        logistic_prob = logit.predict_proba(X_test)[:, 1]
        logistic_dir = (logistic_prob >= 0.5).astype(int)
        for i, (_, row) in enumerate(test.iterrows()):
            actual_dir = int(row[target_col] > 0)
            funding = row.get("funding_rate_mean")
            funding = float(funding) if pd.notna(funding) else np.nan
            records.append(
                {
                    "date": row["date"],
                    "close": float(row["close"]),
                    "prob_up": float(prob[i]),
                    "prob_up_raw": float(raw_prob[i]) if raw_prob is not None else np.nan,
                    "pred_direction": int(direction[i]),
                    "pred_return_raw": float(raw[i]),
                    "pred_return": float(signed[i]),
                    "pred_close": float(row["close"] * (1 + signed[i])),
                    "actual_close": float(row[target_close_col]),
                    "actual_return": float(row[target_col]),
                    "actual_direction": actual_dir,
                    "correct": int(direction[i] == actual_dir),
                    "funding_rate_mean": funding,
                    "logistic_prob_up": float(logistic_prob[i]),
                    "logistic_direction": int(logistic_dir[i]),
                    "logistic_correct": int(logistic_dir[i] == actual_dir),
                    "always_up_correct": int(actual_dir == 1),
                    "momentum_direction": int(float(row.get("ret_7", 0) or 0) > 0),
                }
            )
        chunk = records[-len(test):]
        print(
            f"[{label} backtest] {test['date'].iloc[0].date()} -> {test['date'].iloc[-1].date()}: "
            f"acc={np.mean([r['correct'] for r in chunk]):.3f}",
            flush=True,
        )
    out = pd.DataFrame(records)
    if not out.empty:
        out["momentum_correct"] = (out["momentum_direction"] == out["actual_direction"]).astype(int)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_path, index=False, encoding="utf-8-sig")
    return out


def _strategy_stats(sub: pd.DataFrame) -> dict[str, Any]:
    actual = sub["actual_return"].astype(float).to_numpy()
    directions = sub["pred_direction"].astype(int).to_numpy()
    if not len(actual):
        return {}
    gross = np.where(directions == 1, actual, -actual)
    prev = np.concatenate([[0], directions[:-1]])
    turnover = np.abs(directions - prev).astype(float)
    fees = turnover * TAKER_FEE_RATE
    slippage = turnover * SLIPPAGE_RATE
    if "funding_rate_mean" in sub.columns:
        funding_rate = pd.to_numeric(sub["funding_rate_mean"], errors="coerce").to_numpy(dtype=float)
        funding_rate = np.where(np.isnan(funding_rate), DEFAULT_FUNDING_RATE_8H, funding_rate)
    else:
        funding_rate = np.full(len(sub), DEFAULT_FUNDING_RATE_8H)
    funding = directions * funding_rate * FUNDING_SETTLEMENTS_PER_DAY
    net = gross - fees - slippage - funding
    equity_gross = np.cumprod(1.0 + gross)
    equity_net = np.cumprod(1.0 + net)
    drawdown = equity_net / np.maximum.accumulate(equity_net) - 1.0
    std = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    sharpe = float(np.mean(net) / std * np.sqrt(365)) if std > 0 else None
    buy_hold = float(np.prod(1.0 + actual) - 1.0)
    return {
        "strategy_return": float(equity_net[-1] - 1.0),
        "strategy_return_gross": float(equity_gross[-1] - 1.0),
        "strategy_cost_drag": float((equity_net[-1] - 1.0) - (equity_gross[-1] - 1.0)),
        "fees_paid": float(fees.sum()),
        "slippage_paid": float(slippage.sum()),
        "funding_paid": float(funding.sum()),
        "turnover_total": float(turnover.sum()),
        "turnover_per_day": float(turnover.mean()),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
        "always_long_return": buy_hold,
        "cost_model": COST_MODEL,
    }


def _significance(correct: pd.Series) -> dict[str, Any]:
    arr = correct.astype(int).to_numpy()
    n = len(arr)
    if n == 0:
        return {}
    k = int(arr.sum())
    accuracy = k / n
    try:
        from scipy.stats import binomtest

        binom_two = float(binomtest(k, n, 0.5).pvalue)
        binom_greater = float(binomtest(k, n, 0.5, alternative="greater").pvalue)
    except Exception:  # noqa: BLE001
        from math import erfc

        z = (k - 0.5 * n) / np.sqrt(0.25 * n)
        binom_greater = float(0.5 * erfc(z / np.sqrt(2)))
        binom_two = float(min(1.0, 2.0 * min(binom_greater, 1.0 - binom_greater)))
    rng = np.random.default_rng(RANDOM_STATE)
    idx = rng.integers(0, n, size=(BOOTSTRAP_ROUNDS, n))
    bootstrap = arr[idx].mean(axis=1)
    ci_low, ci_high = (float(v) for v in np.quantile(bootstrap, [0.025, 0.975]))
    bootstrap_p = float(np.mean(bootstrap <= 0.5))
    blocks = int(np.ceil(n / BLOCK_BOOTSTRAP_BLOCK))
    starts = rng.integers(0, n, size=(BOOTSTRAP_ROUNDS, blocks))
    offsets = np.arange(BLOCK_BOOTSTRAP_BLOCK)
    block_idx = (starts[:, :, None] + offsets[None, None, :]) % n
    block_bootstrap = arr[block_idx].reshape(BOOTSTRAP_ROUNDS, -1)[:, :n].mean(axis=1)
    block_ci_low, block_ci_high = (float(v) for v in np.quantile(block_bootstrap, [0.025, 0.975]))
    block_p = float(np.mean(block_bootstrap <= 0.5))
    return {
        "samples": n,
        "accuracy": float(accuracy),
        "edge": float(accuracy - 0.5),
        "binom_p_two_sided": binom_two,
        "binom_p_greater": binom_greater,
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "bootstrap_p_le_50": bootstrap_p,
        "block_bootstrap_ci_low": block_ci_low,
        "block_bootstrap_ci_high": block_ci_high,
        "block_bootstrap_p_le_50": block_p,
        "significant_at_5pct": bool(binom_two < 0.05),
    }


def _calibration_stats(sub: pd.DataFrame) -> dict[str, Any]:
    prob = sub["prob_up"].astype(float).clip(1e-6, 1 - 1e-6).to_numpy()
    actual = sub["actual_direction"].astype(int).to_numpy()
    pred_direction = sub["pred_direction"].astype(int).to_numpy()
    correct = sub["correct"].astype(int).to_numpy()
    brier = float(np.mean((prob - actual) ** 2))
    log_loss = float(-np.mean(actual * np.log(prob) + (1 - actual) * np.log(1 - prob)))
    confidence = np.maximum(prob, 1 - prob)
    predicted_correct_prob = np.where(pred_direction == 1, prob, 1 - prob)
    bins = []
    for lo, hi in ((0.5, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)):
        mask = (confidence >= lo) & (confidence < hi)
        if not mask.any():
            continue
        avg_conf = float(confidence[mask].mean())
        acc = float(correct[mask].mean())
        bins.append(
            {
                "range": f"{lo:.2f}-{min(hi, 1.0):.2f}",
                "count": int(mask.sum()),
                "avg_confidence": avg_conf,
                "accuracy": acc,
                "gap": float(avg_conf - acc),
            }
        )
    ece = float(sum(b["count"] / len(sub) * abs(b["gap"]) for b in bins)) if bins else None
    out: dict[str, Any] = {
        "brier": brier,
        "log_loss": log_loss,
        "ece": ece,
        "reliability": bins,
    }
    if "prob_up_raw" in sub.columns:
        raw = pd.to_numeric(sub["prob_up_raw"], errors="coerce")
        mask = raw.notna()
        if mask.any():
            raw_arr = raw[mask].astype(float).clip(1e-6, 1 - 1e-6).to_numpy()
            out["brier_raw"] = float(np.mean((raw_arr - actual[mask.to_numpy()]) ** 2))
    return out


def _metrics(sub: pd.DataFrame, include_strategy: bool = True) -> dict[str, Any]:
    if sub.empty:
        return {}
    y_true = sub["actual_direction"].astype(int)
    y_pred = sub["pred_direction"].astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, y_pred, labels=[0, 1], zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    try:
        auc = float(roc_auc_score(y_true, sub["prob_up"])) if y_true.nunique() == 2 else None
    except Exception:
        auc = None
    auc_raw = None
    if "prob_up_raw" in sub.columns:
        raw = pd.to_numeric(sub["prob_up_raw"], errors="coerce")
        if raw.notna().any() and y_true.nunique() == 2:
            try:
                auc_raw = float(roc_auc_score(y_true, raw.fillna(0.5)))
            except Exception:
                auc_raw = None
    confidence = np.maximum(sub["prob_up"], 1 - sub["prob_up"])
    high_mask = confidence >= 0.65
    buckets = []
    for lo, hi in ((0.5, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 1.01)):
        mask = (confidence >= lo) & (confidence < hi)
        if mask.any():
            buckets.append(
                {
                    "range": f"{lo:.2f}-{min(hi, 1.0):.2f}",
                    "count": int(mask.sum()),
                    "accuracy": float(sub.loc[mask, "correct"].mean()),
                }
            )
    out: dict[str, Any] = {
        "samples": int(len(sub)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "precision_down": float(precision[0]),
        "recall_down": float(recall[0]),
        "precision_up": float(precision[1]),
        "recall_up": float(recall[1]),
        "f1_up": float(f1[1]),
        "auc": auc,
        "auc_raw": auc_raw,
        "mae_return": float(mean_absolute_error(sub["actual_return"], sub["pred_return"])),
        "rmse_return": float(np.sqrt(mean_squared_error(sub["actual_return"], sub["pred_return"]))),
        "mae_close": float(mean_absolute_error(sub["actual_close"], sub["pred_close"])),
        "mape_close": float(mean_absolute_percentage_error(sub["actual_close"], sub["pred_close"])),
        "high_conf_samples": int(high_mask.sum()),
        "high_conf_coverage": float(high_mask.mean()),
        "high_conf_accuracy": float(sub.loc[high_mask, "correct"].mean()) if high_mask.any() else None,
        "always_up_accuracy": float(sub["actual_direction"].mean()),
        "momentum_accuracy": float(sub["momentum_correct"].mean()),
        "logistic_accuracy": float(sub["logistic_correct"].mean()),
        "confusion": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "tp": int(cm[1, 1])},
        "confidence_buckets": buckets,
    }
    if "prob_up_raw" in sub.columns:
        raw = pd.to_numeric(sub["prob_up_raw"], errors="coerce")
        if raw.notna().any():
            raw_direction = (raw.fillna(0.5) >= 0.5).astype(int)
            out["raw_accuracy"] = float((raw_direction == y_true).mean())
            out["raw_decision_flips"] = int((raw_direction != y_pred).sum())
    out.update(_calibration_stats(sub))
    out.update(_significance(sub["correct"]))
    if include_strategy:
        out.update(_strategy_stats(sub))
    return out


def evaluate(backtest: pd.DataFrame, include_strategy: bool = True) -> dict[str, Any]:
    if backtest.empty:
        return {}
    backtest = backtest.sort_values("date").reset_index(drop=True)
    all_metrics = _metrics(backtest, include_strategy=include_strategy)
    recent = backtest.tail(90)
    recent_metrics = _metrics(recent, include_strategy=include_strategy)
    rolling = (
        backtest.set_index("date")["correct"].rolling(30).mean().reset_index().rename(columns={"correct": "accuracy"})
    )
    rolling["date"] = pd.to_datetime(rolling["date"]).dt.strftime("%Y-%m-%d")
    return {
        "all": all_metrics,
        "recent_90": recent_metrics,
        "rolling_30": rolling.dropna().to_dict("records"),
        "cost_model": COST_MODEL,
        "calibration_method": _calibration_method(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def compute_feature_importance(data: pd.DataFrame, holdout: int = 120) -> pd.DataFrame:
    data = data[data["target_return"].notna()].sort_values("date").reset_index(drop=True)
    if len(data) < 250:
        return pd.DataFrame(columns=["feature", "importance"])
    train = data.iloc[:-holdout]
    test = data.iloc[-holdout:]
    X_train_full, y_train, _ = _xy(train)
    X_test_full = test[FEATURE_COLUMNS].astype(float)
    active = _active_features(X_train_full)
    if not active:
        return pd.DataFrame(columns=["feature", "importance"])
    X_train = X_train_full[active]
    X_test = X_test_full[active]
    y_test = (test["target_return"] > 0).astype(int)
    model = _classifier_pipeline().fit(X_train, y_train)
    result = permutation_importance(model, X_test, y_test, n_repeats=3, random_state=RANDOM_STATE, scoring="accuracy")
    out = pd.DataFrame({"feature": active, "importance": result.importances_mean})
    out = out.sort_values("importance", ascending=False).reset_index(drop=True)
    out.to_csv(IMPORTANCE_PATH, index=False, encoding="utf-8-sig")
    return out


def _feature_snapshot(row: pd.Series, importance: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    if importance.empty:
        return []
    items = []
    for _, item in importance.head(limit).iterrows():
        name = item["feature"]
        value = row.get(name)
        if pd.isna(value):
            value = None
        else:
            value = float(value)
        items.append({"feature": name, "importance": float(item["importance"]), "value": value})
    return items


def _residual_sigma(backtest: pd.DataFrame | None, tail: int = 180) -> float:
    if backtest is None or backtest.empty:
        return 0.02
    residuals = (backtest["pred_return"] - backtest["actual_return"]).tail(tail)
    if len(residuals) < 20:
        return 0.02
    return float(residuals.std())


def train_final(
    df: pd.DataFrame,
    backtest: pd.DataFrame | None = None,
    weekly_prediction: dict[str, Any] | None = None,
    weekly_metrics: dict[str, Any] | None = None,
    feature_columns: list[str] | None = None,
    importance: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    feature_columns = feature_columns or FEATURE_COLUMNS
    data = df[df["target_return"].notna()].sort_values("date").reset_index(drop=True)
    if len(data) < MIN_TRAIN_DAYS:
        raise RuntimeError(f"Not enough training rows: {len(data)}")
    X_train_full, y_dir, y_ret = _xy(data, feature_columns)
    active = _active_features(X_train_full)
    if not active:
        raise RuntimeError("No usable features in final training set")
    X_train = X_train_full[active]
    clf = _calibrated_classifier().fit(X_train, y_dir)
    reg = _regressor_pipeline().fit(X_train, y_ret)
    logit = _logistic().fit(X_train, y_dir)

    if importance is None:
        importance = compute_feature_importance(df)
    latest = df.sort_values("date").iloc[-1]
    X_latest = pd.DataFrame([latest[active].astype(float)], columns=active)
    prob, raw_prob, raw = _predict_bundle(clf, reg, X_latest)
    direction, signed = _signed_return(prob, raw)
    last_close = float(latest["close"])
    pred_close = float(last_close * (1 + signed[0]))
    target_date = pd.Timestamp(latest["date"]) + pd.Timedelta(days=1)

    residual_std = _residual_sigma(backtest)
    band = max(residual_std, 0.005) * last_close

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prediction = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_days": 1,
        "last_candle_date": pd.Timestamp(latest["date"]).strftime("%Y-%m-%d"),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "last_close": last_close,
        "predicted_close": pred_close,
        "predicted_return": float(signed[0]),
        "predicted_return_raw": float(raw[0]),
        "direction": "up" if int(direction[0]) == 1 else "down",
        "direction_cn": "上涨" if int(direction[0]) == 1 else "下跌",
        "prob_up": float(prob[0]),
        "prob_up_raw": float(raw_prob[0]) if raw_prob is not None else None,
        "confidence": float(max(prob[0], 1 - prob[0])),
        "interval_low": float(pred_close - band),
        "interval_high": float(pred_close + band),
        "interval_sigma": residual_std,
        "calibration_method": _calibration_method(),
        "top_features": _feature_snapshot(latest, importance),
    }
    if weekly_prediction:
        prediction["weekly"] = weekly_prediction

    model_bundle = {
        "classifier": clf,
        "regressor": reg,
        "logistic": logit,
        "features": active,
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(data)),
        "last_training_date": pd.Timestamp(data["date"].iloc[-1]).strftime("%Y-%m-%d"),
        "calibration_method": _calibration_method(),
    }
    joblib.dump(model_bundle, MODEL_PATH)
    PREDICTION_PATH.write_text(json.dumps(prediction, ensure_ascii=False, indent=2), encoding="utf-8")

    metrics = evaluate(backtest) if backtest is not None and not backtest.empty else {}
    if weekly_metrics:
        metrics["weekly"] = weekly_metrics
    metadata = {
        "version": version,
        "trained_at": model_bundle["trained_at"],
        "training_rows": model_bundle["training_rows"],
        "last_training_date": model_bundle["last_training_date"],
        "features": active,
        "calibration_method": _calibration_method(),
        "cost_model": COST_MODEL,
        "metrics": metrics,
        "feature_importance": importance.head(20).to_dict("records") if not importance.empty else [],
    }
    METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return prediction, metadata


def train_final_weekly(
    df: pd.DataFrame,
    backtest: pd.DataFrame | None = None,
    feature_columns: list[str] | None = None,
    importance: pd.DataFrame | None = None,
) -> dict[str, Any]:
    feature_columns = feature_columns or FEATURE_COLUMNS
    target_col = "target_return_7"
    data = df[df[target_col].notna()].sort_values("date").reset_index(drop=True)
    if len(data) < MIN_TRAIN_DAYS:
        raise RuntimeError(f"Not enough weekly training rows: {len(data)}")
    X_train_full, y_dir, y_ret = _xy(data, feature_columns, target_col)
    active = _active_features(X_train_full)
    if not active:
        raise RuntimeError("No usable features in weekly training set")
    X_train = X_train_full[active]
    clf = _calibrated_classifier().fit(X_train, y_dir)
    reg = _regressor_pipeline().fit(X_train, y_ret)
    if importance is None:
        importance = load_importance()
    latest = df.sort_values("date").iloc[-1]
    X_latest = pd.DataFrame([latest[active].astype(float)], columns=active)
    prob, raw_prob, raw = _predict_bundle(clf, reg, X_latest)
    direction, signed = _signed_return(prob, raw)
    last_close = float(latest["close"])
    pred_close = float(last_close * (1 + signed[0]))
    target_date = pd.Timestamp(latest["date"]) + pd.Timedelta(days=WEEKLY_HORIZON)
    residual_std = _residual_sigma(backtest, tail=120)
    band = max(residual_std, 0.01) * last_close
    return {
        "horizon_days": WEEKLY_HORIZON,
        "last_candle_date": pd.Timestamp(latest["date"]).strftime("%Y-%m-%d"),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "last_close": last_close,
        "predicted_close": pred_close,
        "predicted_return": float(signed[0]),
        "predicted_return_raw": float(raw[0]),
        "direction": "up" if int(direction[0]) == 1 else "down",
        "direction_cn": "上涨" if int(direction[0]) == 1 else "下跌",
        "prob_up": float(prob[0]),
        "prob_up_raw": float(raw_prob[0]) if raw_prob is not None else None,
        "confidence": float(max(prob[0], 1 - prob[0])),
        "interval_low": float(pred_close - band),
        "interval_high": float(pred_close + band),
        "interval_sigma": residual_std,
        "calibration_method": _calibration_method(),
        "top_features": _feature_snapshot(latest, importance),
    }


def load_backtest(path: Path = BACKTEST_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def load_weekly_backtest() -> pd.DataFrame:
    return load_backtest(WEEKLY_BACKTEST_PATH)


def load_prediction() -> dict[str, Any]:
    if not PREDICTION_PATH.exists():
        return {}
    return json.loads(PREDICTION_PATH.read_text(encoding="utf-8"))


def load_metadata() -> dict[str, Any]:
    if not METADATA_PATH.exists():
        return {}
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def load_importance() -> pd.DataFrame:
    if not IMPORTANCE_PATH.exists():
        return pd.DataFrame(columns=["feature", "importance"])
    return pd.read_csv(IMPORTANCE_PATH, encoding="utf-8-sig")
