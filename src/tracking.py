from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR

PREDICTIONS_PATH = DATA_DIR / "predictions.csv"
WEEKLY_PREDICTIONS_PATH = DATA_DIR / "weekly_predictions.csv"

COLUMNS = [
    "target_date",
    "last_candle_date",
    "generated_at",
    "version",
    "last_close",
    "predicted_close",
    "predicted_return",
    "direction",
    "prob_up",
    "confidence",
    "interval_low",
    "interval_high",
    "actual_close",
    "actual_return",
    "actual_direction",
    "correct",
    "evaluated_at",
]

_PATHS = {"daily": PREDICTIONS_PATH, "weekly": WEEKLY_PREDICTIONS_PATH}


def _path(weekly: bool) -> Path:
    return _PATHS["weekly" if weekly else "daily"]


def load_predictions(weekly: bool = False) -> pd.DataFrame:
    path = _path(weekly)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in ("target_date", "last_candle_date", "generated_at", "evaluated_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def record_prediction(prediction: dict[str, Any], weekly: bool = False) -> pd.DataFrame:
    df = load_predictions(weekly)
    target = pd.Timestamp(prediction["target_date"]).normalize()
    row = {
        "target_date": target,
        "last_candle_date": pd.Timestamp(prediction["last_candle_date"]).normalize(),
        "generated_at": pd.Timestamp(prediction["generated_at"]),
        "version": prediction.get("version"),
        "last_close": float(prediction["last_close"]),
        "predicted_close": float(prediction["predicted_close"]),
        "predicted_return": float(prediction["predicted_return"]),
        "direction": prediction.get("direction"),
        "prob_up": float(prediction.get("prob_up", 0.5)),
        "confidence": float(prediction.get("confidence", 0.5)),
        "interval_low": float(prediction.get("interval_low", np.nan)),
        "interval_high": float(prediction.get("interval_high", np.nan)),
        "actual_close": np.nan,
        "actual_return": np.nan,
        "actual_direction": np.nan,
        "correct": np.nan,
        "evaluated_at": pd.NaT,
    }
    if not df.empty:
        existing = df.index[df["target_date"] == target]
        if len(existing):
            idx = existing[-1]
            if pd.isna(df.loc[idx, "actual_close"]):
                for key, value in row.items():
                    df.loc[idx, key] = value
                df.to_csv(_path(weekly), index=False, encoding="utf-8-sig")
                return df
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df = df.sort_values("target_date").reset_index(drop=True)
    df.to_csv(_path(weekly), index=False, encoding="utf-8-sig")
    return df


def evaluate_pending(btc: pd.DataFrame, weekly: bool = False) -> pd.DataFrame:
    df = load_predictions(weekly)
    if df.empty or btc.empty:
        return df
    btc = btc.copy()
    btc["date"] = pd.to_datetime(btc["date"]).dt.normalize()
    complete_mask = btc["complete"].astype(str).str.lower().isin(["true", "1", "1.0", "yes"])
    complete = btc[complete_mask].set_index("date")["close"]
    if complete.empty:
        return df
    changed = False
    for idx, row in df.iterrows():
        if pd.notna(row.get("actual_close")):
            continue
        target = pd.Timestamp(row["target_date"]).normalize()
        if target not in complete.index:
            continue
        actual_close = float(complete.loc[target])
        last_close = float(row["last_close"])
        actual_return = actual_close / last_close - 1
        actual_direction = 1 if actual_return > 0 else 0
        df.loc[idx, "actual_close"] = actual_close
        df.loc[idx, "actual_return"] = actual_return
        df.loc[idx, "actual_direction"] = actual_direction
        df.loc[idx, "correct"] = int(actual_direction == (1 if row["direction"] == "up" else 0))
        df.loc[idx, "evaluated_at"] = pd.Timestamp(datetime.now(timezone.utc)).floor("s").tz_convert(None)
        changed = True
    if changed:
        df.to_csv(_path(weekly), index=False, encoding="utf-8-sig")
    return df


def live_metrics(weekly: bool = False) -> dict[str, Any]:
    df = load_predictions(weekly)
    if df.empty:
        return {"samples": 0, "accuracy": None, "recent_30": None, "pending": 0}
    evaluated = df[df["correct"].notna()].copy()
    pending = int(df["correct"].isna().sum())
    if evaluated.empty:
        return {"samples": 0, "accuracy": None, "recent_30": None, "pending": pending}
    evaluated["correct"] = evaluated["correct"].astype(int)
    recent = evaluated.tail(30)
    mae = None
    if evaluated["actual_close"].notna().any():
        mae = float((evaluated["predicted_close"] - evaluated["actual_close"]).abs().mean())
    return {
        "samples": int(len(evaluated)),
        "accuracy": float(evaluated["correct"].mean()),
        "recent_30": float(recent["correct"].mean()) if len(recent) else None,
        "pending": pending,
        "mae_close": mae,
        "last_target": pd.Timestamp(evaluated["target_date"].iloc[-1]).strftime("%Y-%m-%d"),
    }


def recent_predictions(limit: int = 12, weekly: bool = False) -> list[dict[str, Any]]:
    df = load_predictions(weekly)
    if df.empty:
        return []
    rows = []
    for _, row in df.sort_values("target_date").tail(limit).iloc[::-1].iterrows():
        rows.append(
            {
                "target_date": pd.Timestamp(row["target_date"]).strftime("%Y-%m-%d"),
                "predicted_close": float(row["predicted_close"]),
                "actual_close": None if pd.isna(row["actual_close"]) else float(row["actual_close"]),
                "predicted_return": float(row["predicted_return"]),
                "actual_return": None if pd.isna(row["actual_return"]) else float(row["actual_return"]),
                "direction": row["direction"],
                "prob_up": float(row["prob_up"]),
                "correct": None if pd.isna(row["correct"]) else bool(row["correct"]),
            }
        )
    return rows
