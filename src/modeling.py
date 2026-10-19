from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
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
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import (
    DATA_DIR,
    FEATURE_COLUMNS,
    MIN_TRAIN_DAYS,
    MODEL_DIR,
    RANDOM_STATE,
    TEST_BLOCK_DAYS,
)

BACKTEST_PATH = DATA_DIR / "backtest.csv"
PREDICTION_PATH = DATA_DIR / "latest_prediction.json"
MODEL_PATH = MODEL_DIR / "latest_model.joblib"
METADATA_PATH = MODEL_DIR / "metadata.json"
IMPORTANCE_PATH = DATA_DIR / "feature_importance.csv"


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
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=2000, C=0.5, solver="lbfgs")),
        ]
    )


def _xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    data = df[df["target_return"].notna()].copy()
    X = data[FEATURE_COLUMNS].astype(float)
    y_dir = (data["target_return"] > 0).astype(int)
    y_ret = data["target_return"].astype(float)
    return X, y_dir, y_ret


def _active_features(X: pd.DataFrame) -> list[str]:
    """Drop columns that are entirely missing or constant in this training slice."""
    return [col for col in X.columns if X[col].nunique(dropna=True) >= 2]


def _predict_bundle(clf, reg, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    prob = clf.predict_proba(X)[:, 1]
    raw = reg.predict(X)
    return prob, raw


def _signed_return(prob: np.ndarray, raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    direction = (prob >= 0.5).astype(int)
    flat = np.isclose(prob, 0.5, atol=1e-12)
    direction[flat] = (raw[flat] >= 0).astype(int)
    clipped = np.clip(raw, -0.15, 0.15)
    absolute = np.abs(clipped)
    absolute = np.where(absolute < 0.001, 0.001, absolute)
    signed = np.where(direction == 1, absolute, -absolute)
    return direction, signed


def walk_forward(df: pd.DataFrame, min_train: int = MIN_TRAIN_DAYS, block: int = TEST_BLOCK_DAYS) -> pd.DataFrame:
    data = df[df["target_return"].notna()].sort_values("date").reset_index(drop=True)
    if len(data) <= min_train + 10:
        raise RuntimeError(f"Not enough training rows: {len(data)}")
    records: list[dict[str, Any]] = []
    for start in range(min_train, len(data), block):
        train = data.iloc[:start]
        test = data.iloc[start : start + block]
        if test.empty:
            break
        X_train_full, y_dir, y_ret = _xy(train)
        X_test_full = test[FEATURE_COLUMNS].astype(float)
        active = _active_features(X_train_full)
        if not active:
            raise RuntimeError("No usable features in training slice")
        X_train = X_train_full[active]
        X_test = X_test_full[active]
        clf = _classifier().fit(X_train, y_dir)
        reg = _regressor().fit(X_train, y_ret)
        logit = _logistic().fit(X_train, y_dir)
        prob, raw = _predict_bundle(clf, reg, X_test)
        direction, signed = _signed_return(prob, raw)
        logistic_prob = logit.predict_proba(X_test)[:, 1]
        logistic_dir = (logistic_prob >= 0.5).astype(int)
        for i, (_, row) in enumerate(test.iterrows()):
            actual_dir = int(row["target_return"] > 0)
            records.append(
                {
                    "date": row["date"],
                    "close": float(row["close"]),
                    "prob_up": float(prob[i]),
                    "pred_direction": int(direction[i]),
                    "pred_return_raw": float(raw[i]),
                    "pred_return": float(signed[i]),
                    "pred_close": float(row["close"] * (1 + signed[i])),
                    "actual_close": float(row["target_close"]),
                    "actual_return": float(row["target_return"]),
                    "actual_direction": actual_dir,
                    "correct": int(direction[i] == actual_dir),
                    "logistic_prob_up": float(logistic_prob[i]),
                    "logistic_direction": int(logistic_dir[i]),
                    "logistic_correct": int(logistic_dir[i] == actual_dir),
                    "always_up_correct": int(actual_dir == 1),
                    "momentum_direction": int(float(row.get("ret_7", 0) or 0) > 0),
                }
            )
        print(
            f"[backtest] {test['date'].iloc[0].date()} -> {test['date'].iloc[-1].date()}: "
            f"acc={np.mean([r['correct'] for r in records[-len(test):]]):.3f}",
            flush=True,
        )
    out = pd.DataFrame(records)
    if not out.empty:
        out["momentum_correct"] = (out["momentum_direction"] == out["actual_direction"]).astype(int)
        out.to_csv(BACKTEST_PATH, index=False, encoding="utf-8-sig")
    return out


def _metrics(sub: pd.DataFrame) -> dict[str, Any]:
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
    strategy = np.where(y_pred == 1, sub["actual_return"], -sub["actual_return"])
    strategy_curve = (1 + pd.Series(strategy)).cumprod() - 1
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
    return {
        "samples": int(len(sub)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "precision_down": float(precision[0]),
        "recall_down": float(recall[0]),
        "precision_up": float(precision[1]),
        "recall_up": float(recall[1]),
        "f1_up": float(f1[1]),
        "auc": auc,
        "mae_return": float(mean_absolute_error(sub["actual_return"], sub["pred_return"])),
        "rmse_return": float(np.sqrt(mean_squared_error(sub["actual_return"], sub["pred_return"]))),
        "mae_close": float(mean_absolute_error(sub["actual_close"], sub["pred_close"])),
        "mape_close": float(mean_absolute_percentage_error(sub["actual_close"], sub["pred_close"])),
        "strategy_return": float(strategy_curve.iloc[-1]) if len(strategy_curve) else 0.0,
        "high_conf_samples": int(high_mask.sum()),
        "high_conf_coverage": float(high_mask.mean()),
        "high_conf_accuracy": float(sub.loc[high_mask, "correct"].mean()) if high_mask.any() else None,
        "always_up_accuracy": float(sub["actual_direction"].mean()),
        "momentum_accuracy": float(sub["momentum_correct"].mean()),
        "logistic_accuracy": float(sub["logistic_correct"].mean()),
        "confusion": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]), "fn": int(cm[1, 0]), "tp": int(cm[1, 1])},
        "confidence_buckets": buckets,
    }


def evaluate(backtest: pd.DataFrame) -> dict[str, Any]:
    if backtest.empty:
        return {}
    backtest = backtest.sort_values("date").reset_index(drop=True)
    all_metrics = _metrics(backtest)
    recent = backtest.tail(90)
    recent_metrics = _metrics(recent)
    rolling = (
        backtest.set_index("date")["correct"].rolling(30).mean().reset_index().rename(columns={"correct": "accuracy"})
    )
    rolling["date"] = pd.to_datetime(rolling["date"]).dt.strftime("%Y-%m-%d")
    return {
        "all": all_metrics,
        "recent_90": recent_metrics,
        "rolling_30": rolling.dropna().to_dict("records"),
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
    model = _classifier().fit(X_train, y_train)
    result = permutation_importance(model, X_test, y_test, n_repeats=3, random_state=RANDOM_STATE, scoring="accuracy")
    out = pd.DataFrame({"feature": active, "importance": result.importances_mean})
    out = out.sort_values("importance", ascending=False).reset_index(drop=True)
    out.to_csv(IMPORTANCE_PATH, index=False, encoding="utf-8-sig")
    return out


def _feature_snapshot(row: pd.Series, importance: pd.DataFrame) -> list[dict[str, Any]]:
    if importance.empty:
        return []
    items = []
    for _, item in importance.head(12).iterrows():
        name = item["feature"]
        value = row.get(name)
        if pd.isna(value):
            value = None
        else:
            value = float(value)
        items.append({"feature": name, "importance": float(item["importance"]), "value": value})
    return items


def train_final(df: pd.DataFrame, backtest: pd.DataFrame | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    data = df[df["target_return"].notna()].sort_values("date").reset_index(drop=True)
    if len(data) < MIN_TRAIN_DAYS:
        raise RuntimeError(f"Not enough training rows: {len(data)}")
    X_train_full, y_dir, y_ret = _xy(data)
    active = _active_features(X_train_full)
    if not active:
        raise RuntimeError("No usable features in final training set")
    X_train = X_train_full[active]
    clf = _classifier().fit(X_train, y_dir)
    reg = _regressor().fit(X_train, y_ret)
    logit = _logistic().fit(X_train, y_dir)

    importance = compute_feature_importance(df)
    latest = df.sort_values("date").iloc[-1]
    X_latest = pd.DataFrame([latest[active].astype(float)], columns=active)
    prob, raw = _predict_bundle(clf, reg, X_latest)
    direction, signed = _signed_return(prob, raw)
    last_close = float(latest["close"])
    pred_close = float(last_close * (1 + signed[0]))
    target_date = pd.Timestamp(latest["date"]) + pd.Timedelta(days=1)

    residual_std = 0.02
    if backtest is not None and not backtest.empty:
        residuals = (backtest["pred_return"] - backtest["actual_return"]).tail(180)
        if len(residuals) >= 20:
            residual_std = float(residuals.std())
    band = max(residual_std, 0.005) * last_close

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prediction = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_candle_date": pd.Timestamp(latest["date"]).strftime("%Y-%m-%d"),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "last_close": last_close,
        "predicted_close": pred_close,
        "predicted_return": float(signed[0]),
        "predicted_return_raw": float(raw[0]),
        "direction": "up" if int(direction[0]) == 1 else "down",
        "direction_cn": "上涨" if int(direction[0]) == 1 else "下跌",
        "prob_up": float(prob[0]),
        "confidence": float(max(prob[0], 1 - prob[0])),
        "interval_low": float(pred_close - band),
        "interval_high": float(pred_close + band),
        "interval_sigma": residual_std,
        "top_features": _feature_snapshot(latest, importance),
    }

    model_bundle = {
        "classifier": clf,
        "regressor": reg,
        "logistic": logit,
        "features": active,
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(data)),
        "last_training_date": pd.Timestamp(data["date"].iloc[-1]).strftime("%Y-%m-%d"),
    }
    joblib.dump(model_bundle, MODEL_PATH)
    PREDICTION_PATH.write_text(json.dumps(prediction, ensure_ascii=False, indent=2), encoding="utf-8")

    metrics = evaluate(backtest) if backtest is not None and not backtest.empty else {}
    metadata = {
        "version": version,
        "trained_at": model_bundle["trained_at"],
        "training_rows": model_bundle["training_rows"],
        "last_training_date": model_bundle["last_training_date"],
        "features": active,
        "metrics": metrics,
        "feature_importance": importance.head(20).to_dict("records") if not importance.empty else [],
    }
    METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return prediction, metadata


def load_backtest() -> pd.DataFrame:
    if not BACKTEST_PATH.exists():
        return pd.DataFrame()
    df = pd.read_csv(BACKTEST_PATH, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


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
