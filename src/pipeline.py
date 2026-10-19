from __future__ import annotations

from typing import Any

import pandas as pd

from config import DATA_DIR, NEWS_BACKFILL_DAYS
from src.analysis import write_daily_report
from src.data_pipeline import build_dataset, refresh_all
from src.features import build_features, load_features
from src.modeling import evaluate, load_backtest, train_final, walk_forward
from src.tracking import evaluate_pending, live_metrics, record_prediction


def _btc() -> pd.DataFrame:
    path = DATA_DIR / "btc_daily.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def bootstrap(news_days: int = NEWS_BACKFILL_DAYS) -> dict[str, Any]:
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
    print("=== bootstrap: walk-forward backtest ===", flush=True)
    backtest = walk_forward(df)
    metrics = evaluate(backtest)
    print(f"[bootstrap] backtest accuracy: {metrics.get('all', {}).get('accuracy')}", flush=True)
    print("=== bootstrap: final model ===", flush=True)
    prediction, metadata = train_final(df, backtest)
    evaluate_pending(_btc())
    record_prediction(prediction)
    report = write_daily_report()
    print(f"[bootstrap] prediction: {prediction['target_date']} {prediction['direction_cn']} {prediction['predicted_close']:.2f}", flush=True)
    print(f"[bootstrap] report: {report}", flush=True)
    return {"prediction": prediction, "metrics": metrics, "live": live_metrics(), "report": str(report)}


def update(news_days: int = 2) -> dict[str, Any]:
    print("=== update: refresh data ===", flush=True)
    refresh_all(include_news=True, news_days=news_days)
    print("=== update: features ===", flush=True)
    build_features()
    df = load_features()
    print("=== update: evaluate pending live predictions ===", flush=True)
    evaluate_pending(_btc())
    print("=== update: walk-forward backtest ===", flush=True)
    backtest = walk_forward(df)
    metrics = evaluate(backtest)
    print("=== update: final model ===", flush=True)
    prediction, metadata = train_final(df, backtest)
    record_prediction(prediction)
    report = write_daily_report()
    print(f"[update] backtest accuracy: {metrics.get('all', {}).get('accuracy')}", flush=True)
    print(f"[update] prediction: {prediction['target_date']} {prediction['direction_cn']} {prediction['predicted_close']:.2f}", flush=True)
    return {"prediction": prediction, "metrics": metrics, "live": live_metrics(), "report": str(report)}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update()
    else:
        bootstrap()
