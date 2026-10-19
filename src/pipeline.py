from __future__ import annotations

from typing import Any

import pandas as pd

from config import DATA_DIR, NEWS_BACKFILL_DAYS
from src.analysis import write_daily_report
from src.data_pipeline import build_dataset, refresh_all
from src.features import build_features, load_features
from src.modeling import (
    WEEKLY_BACKTEST_PATH,
    compute_feature_importance,
    evaluate,
    load_backtest,
    train_final,
    train_final_weekly,
    walk_forward,
)
from src.tracking import evaluate_pending, live_metrics, record_prediction


def _btc() -> pd.DataFrame:
    path = DATA_DIR / "btc_daily.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def _weekly_backtest(df: pd.DataFrame) -> pd.DataFrame:
    return walk_forward(
        df,
        target_col="target_return_7",
        target_close_col="target_close_7",
        output_path=WEEKLY_BACKTEST_PATH,
        label="weekly",
    )


def _weekly_metrics(backtest: pd.DataFrame) -> dict[str, Any]:
    metrics = evaluate(backtest, include_strategy=False)
    non_overlap = backtest.sort_values("date").reset_index(drop=True).iloc[::7].reset_index(drop=True)
    metrics["non_overlap"] = evaluate(non_overlap, include_strategy=False)
    return metrics


def _run_core(df: pd.DataFrame) -> dict[str, Any]:
    print("=== features/model: importance ===", flush=True)
    importance = compute_feature_importance(df)

    print("=== daily walk-forward backtest ===", flush=True)
    backtest = walk_forward(df)
    daily_metrics = evaluate(backtest)
    print(f"[pipeline] daily backtest accuracy: {daily_metrics.get('all', {}).get('accuracy')}", flush=True)

    print("=== weekly walk-forward backtest ===", flush=True)
    weekly_bt = _weekly_backtest(df)
    weekly_metrics = _weekly_metrics(weekly_bt)
    print(f"[pipeline] weekly backtest accuracy: {weekly_metrics.get('all', {}).get('accuracy')}", flush=True)

    print("=== final models (daily + weekly) ===", flush=True)
    weekly_prediction = train_final_weekly(df, weekly_bt, importance=importance)
    prediction, metadata = train_final(
        df,
        backtest,
        weekly_prediction=weekly_prediction,
        weekly_metrics=weekly_metrics,
        importance=importance,
    )
    weekly_prediction["version"] = prediction["version"]
    weekly_prediction["generated_at"] = prediction["generated_at"]
    return {
        "backtest": backtest,
        "daily_metrics": daily_metrics,
        "weekly_backtest": weekly_bt,
        "weekly_metrics": weekly_metrics,
        "prediction": prediction,
        "weekly_prediction": weekly_prediction,
        "metadata": metadata,
    }


def bootstrap(news_days: int = NEWS_BACKFILL_DAYS, with_cross_asset: bool = True) -> dict[str, Any]:
    print("=== bootstrap: refresh data ===", flush=True)
    try:
        refresh_all(include_news=True, news_days=news_days)
    except Exception as exc:  # noqa: BLE001
        print(f"[bootstrap] news refresh failed, continuing without new news: {exc}", flush=True)
        refresh_all(include_news=False)
        build_dataset()
    print("=== bootstrap: features ===", flush=True)
    build_features()
    df = load_features()
    print(f"[bootstrap] feature rows: {len(df)}", flush=True)
    core = _run_core(df)

    cross_asset = None
    if with_cross_asset:
        print("=== bootstrap: cross-asset check (BTC/ETH/SOL) ===", flush=True)
        from src.cross_asset import run_cross_asset

        cross_asset = run_cross_asset()
        for name, info in cross_asset.items():
            acc = (info.get("metrics", {}).get("all", {}) or {}).get("accuracy")
            print(f"[cross-asset] {name}: accuracy={acc}", flush=True)

    evaluate_pending(_btc())
    evaluate_pending(_btc(), weekly=True)
    record_prediction(core["prediction"])
    record_prediction(core["weekly_prediction"], weekly=True)
    report = write_daily_report()
    prediction = core["prediction"]
    print(
        f"[bootstrap] prediction: {prediction['target_date']} {prediction['direction_cn']} {prediction['predicted_close']:.2f}",
        flush=True,
    )
    print(f"[bootstrap] report: {report}", flush=True)
    return {
        "prediction": prediction,
        "weekly_prediction": core["weekly_prediction"],
        "metrics": core["daily_metrics"],
        "weekly_metrics": core["weekly_metrics"],
        "live": live_metrics(),
        "weekly_live": live_metrics(weekly=True),
        "cross_asset": cross_asset,
        "report": str(report),
    }


def update(news_days: int = 2) -> dict[str, Any]:
    print("=== update: refresh data ===", flush=True)
    refresh_all(include_news=True, news_days=news_days)
    print("=== update: features ===", flush=True)
    build_features()
    df = load_features()
    print("=== update: evaluate pending live predictions ===", flush=True)
    evaluate_pending(_btc())
    evaluate_pending(_btc(), weekly=True)
    core = _run_core(df)
    record_prediction(core["prediction"])
    record_prediction(core["weekly_prediction"], weekly=True)
    report = write_daily_report()
    prediction = core["prediction"]
    print(f"[update] backtest accuracy: {core['daily_metrics'].get('all', {}).get('accuracy')}", flush=True)
    print(
        f"[update] prediction: {prediction['target_date']} {prediction['direction_cn']} {prediction['predicted_close']:.2f}",
        flush=True,
    )
    return {
        "prediction": prediction,
        "weekly_prediction": core["weekly_prediction"],
        "metrics": core["daily_metrics"],
        "weekly_metrics": core["weekly_metrics"],
        "live": live_metrics(),
        "weekly_live": live_metrics(weekly=True),
        "report": str(report),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update()
    else:
        bootstrap()
