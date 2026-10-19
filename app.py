from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from flask import Flask, jsonify, render_template, request

from config import DATA_DIR, MODEL_DIR, REPORT_DIR, TEMPLATE_DIR, STATIC_DIR
from src.analysis import failure_table, recent_validation
from src.modeling import load_backtest, load_importance, load_metadata, load_prediction
from src.tracking import live_metrics, load_predictions, recent_predictions

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
UPDATE_LOCK = threading.Lock()


def _read_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def _num(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _sources() -> list[dict[str, Any]]:
    files = [
        ("BTC 日线", "btc_daily.csv", "date"),
        ("合并数据", "dataset_raw.csv", "date"),
        ("特征数据", "dataset_features.csv", "date"),
        ("恐慌贪婪", "fear_greed.csv", "date"),
        ("链上数据", "onchain.csv", "date"),
        ("合约数据", "derivatives.csv", "date"),
        ("新闻", "news_raw.csv", "date"),
        ("回测", "backtest.csv", "date"),
        ("实盘预测", "predictions.csv", "target_date"),
    ]
    out = []
    for label, name, date_col in files:
        path = DATA_DIR / name
        if not path.exists():
            out.append({"name": label, "rows": 0, "last_date": None, "updated": None, "ok": False})
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            last = None
            if date_col in df.columns and len(df):
                last = pd.to_datetime(df[date_col], errors="coerce").max()
                last = None if pd.isna(last) else pd.Timestamp(last).strftime("%Y-%m-%d")
            out.append(
                {
                    "name": label,
                    "rows": int(len(df)),
                    "last_date": last,
                    "updated": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "ok": True,
                }
            )
        except Exception:
            out.append({"name": label, "rows": 0, "last_date": None, "updated": None, "ok": False})
    return out


def _market() -> dict[str, Any]:
    df = _read_csv("dataset_features.csv")
    if df.empty:
        return {"candles": {"dates": [], "values": [], "volumes": []}, "last": None}
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    values = [
        [_num(r.open), _num(r.close), _num(r.low), _num(r.high)]
        for r in df.itertuples()
    ]
    volumes = [_num(v) for v in df["volume"].tolist()]
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    change = (_num(last["close"]) or 0) / (_num(prev["close"]) or 1) - 1
    return {
        "candles": {"dates": dates, "values": values, "volumes": volumes},
        "last": {
            "date": pd.Timestamp(last["date"]).strftime("%Y-%m-%d"),
            "close": _num(last["close"]),
            "open": _num(last["open"]),
            "high": _num(last["high"]),
            "low": _num(last["low"]),
            "volume": _num(last["volume"]),
            "change_1d": change,
        },
    }


def _markers() -> list[dict[str, Any]]:
    backtest = load_backtest()
    if backtest.empty:
        return []
    backtest = backtest.sort_values("date").tail(365)
    return [
        {
            "date": pd.Timestamp(r.date).strftime("%Y-%m-%d"),
            "price": _num(r.actual_close),
            "correct": bool(r.correct),
            "predicted": "up" if int(r.pred_direction) == 1 else "down",
        }
        for r in backtest.itertuples()
    ]


def _news() -> list[dict[str, Any]]:
    df = _read_csv("news_raw.csv")
    if df.empty:
        return []
    df = df.sort_values(["date", "score"], ascending=[False, False]).head(24)
    return [
        {
            "date": pd.Timestamp(r.date).strftime("%Y-%m-%d"),
            "source": str(r.source),
            "title": str(r.title),
            "score": _num(r.score),
            "link": str(getattr(r, "link", "") or ""),
        }
        for r in df.itertuples()
    ]


def dashboard_payload() -> dict[str, Any]:
    market = _market()
    prediction = load_prediction()
    metadata = load_metadata()
    importance = load_importance()
    metrics = (metadata.get("metrics") or {})
    importance_rows = [
        {"feature": str(r.feature), "importance": _num(r.importance)}
        for r in importance.head(18).itertuples()
    ] if not importance.empty else []
    report_path = REPORT_DIR / "latest.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    return {
        "ready": bool(market["candles"]["dates"] and prediction),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "prediction": prediction,
        "metrics": {
            "all": metrics.get("all", {}),
            "recent_90": metrics.get("recent_90", {}),
            "rolling_30": metrics.get("rolling_30", []),
            "live": live_metrics(),
        },
        "markers": _markers(),
        "validation": recent_validation(12),
        "live_predictions": recent_predictions(12),
        "failures": failure_table(10),
        "news": _news(),
        "importance": importance_rows,
        "sources": _sources(),
        "model": {
            "version": metadata.get("version"),
            "trained_at": metadata.get("trained_at"),
            "training_rows": metadata.get("training_rows"),
            "last_training_date": metadata.get("last_training_date"),
        },
        "report": report,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def api_dashboard():
    try:
        return jsonify(dashboard_payload())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ready": False, "error": str(exc)}), 500


@app.get("/api/report")
def api_report():
    path = REPORT_DIR / "latest.md"
    if not path.exists():
        return jsonify({"report": ""})
    return jsonify({"report": path.read_text(encoding="utf-8")})


@app.get("/api/health")
def api_health():
    return jsonify(
        {
            "ok": True,
            "features": (DATA_DIR / "dataset_features.csv").exists(),
            "model": (MODEL_DIR / "latest_model.joblib").exists(),
            "prediction": (DATA_DIR / "latest_prediction.json").exists(),
        }
    )


@app.post("/api/update")
def api_update():
    if not UPDATE_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "已有更新任务在运行"}), 409
    try:
        from src.pipeline import update

        result = update(news_days=2)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        UPDATE_LOCK.release()


@app.after_request
def no_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    print("BTC predictor dashboard: http://127.0.0.1:5055", flush=True)
    app.run(host="127.0.0.1", port=5055, debug=False, threaded=True)
