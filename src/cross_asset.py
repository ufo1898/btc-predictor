from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from config import ASSET_SYMBOLS, CROSS_ASSET_FEATURES, DATA_DIR
from src.data_pipeline import build_cross_asset_dataset
from src.features import build_features
from src.modeling import evaluate, load_backtest, walk_forward

CROSS_ASSET_JSON = DATA_DIR / "cross_asset.json"
CROSS_ASSET_CSV = DATA_DIR / "cross_asset.csv"


def run_cross_asset() -> dict[str, Any]:
    """Train the same common-feature model on BTC/ETH/SOL and compare results."""
    summary: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for name, symbol in ASSET_SYMBOLS.items():
        raw_name = f"dataset_raw_cross_{name}.csv"
        feature_name = f"dataset_features_cross_{name}.csv"
        build_cross_asset_dataset(name)
        features = build_features(raw_name, feature_name, CROSS_ASSET_FEATURES)
        output_path = DATA_DIR / f"backtest_cross_{name}.csv"
        backtest = walk_forward(
            features,
            feature_columns=CROSS_ASSET_FEATURES,
            output_path=output_path,
            label=f"cross-{name}",
        )
        metrics = evaluate(backtest)
        all_metrics = metrics.get("all", {})
        summary[name] = {
            "symbol": symbol,
            "rows": int(len(features)),
            "backtest_samples": int(len(backtest)),
            "start": pd.Timestamp(backtest["date"].iloc[0]).strftime("%Y-%m-%d") if not backtest.empty else None,
            "end": pd.Timestamp(backtest["date"].iloc[-1]).strftime("%Y-%m-%d") if not backtest.empty else None,
            "metrics": metrics,
        }
        rows.append(
            {
                "asset": name,
                "symbol": symbol,
                "samples": all_metrics.get("samples"),
                "accuracy": all_metrics.get("accuracy"),
                "auc": all_metrics.get("auc"),
                "strategy_return_net": all_metrics.get("strategy_return"),
                "strategy_return_gross": all_metrics.get("strategy_return_gross"),
                "brier": all_metrics.get("brier"),
                "ece": all_metrics.get("ece"),
            }
        )
    CROSS_ASSET_JSON.parent.mkdir(parents=True, exist_ok=True)
    CROSS_ASSET_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(CROSS_ASSET_CSV, index=False, encoding="utf-8-sig")
    return summary


def load_cross_asset() -> dict[str, Any]:
    if CROSS_ASSET_JSON.exists():
        return json.loads(CROSS_ASSET_JSON.read_text(encoding="utf-8"))
    fallback: dict[str, Any] = {}
    for name, symbol in ASSET_SYMBOLS.items():
        backtest = load_backtest(DATA_DIR / f"backtest_cross_{name}.csv")
        if backtest.empty:
            continue
        metrics = evaluate(backtest)
        fallback[name] = {
            "symbol": symbol,
            "rows": int(len(backtest)),
            "backtest_samples": int(len(backtest)),
            "start": pd.Timestamp(backtest["date"].iloc[0]).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(backtest["date"].iloc[-1]).strftime("%Y-%m-%d"),
            "metrics": metrics,
        }
    return fallback


def load_cross_asset_backtest(name: str) -> pd.DataFrame:
    return load_backtest(DATA_DIR / f"backtest_cross_{name}.csv")


__all__ = [
    "CROSS_ASSET_CSV",
    "CROSS_ASSET_JSON",
    "load_cross_asset",
    "load_cross_asset_backtest",
    "run_cross_asset",
]
