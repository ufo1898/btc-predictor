from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR, REPORT_DIR
from src.modeling import load_backtest, load_importance, load_metadata, load_prediction
from src.tracking import live_metrics


def _load_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.2f}%"
    except Exception:
        return "-"


def _news_for_date(news: pd.DataFrame, date: pd.Timestamp, limit: int = 4) -> list[dict[str, Any]]:
    if news.empty:
        return []
    day = news[news["date"] == pd.Timestamp(date).normalize()].copy()
    if day.empty:
        return []
    day["abs_score"] = day["score"].abs()
    day = day.sort_values("abs_score", ascending=False).head(limit)
    return [
        {
            "title": str(row["title"]),
            "source": str(row["source"]),
            "score": float(row["score"]),
            "link": str(row.get("link", "")),
        }
        for _, row in day.iterrows()
    ]


def explain_failure(row: pd.Series, feature_row: pd.Series | None, news_rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    pred_dir = "上涨" if int(row["pred_direction"]) == 1 else "下跌"
    actual_dir = "上涨" if int(row["actual_direction"]) == 1 else "下跌"
    reasons.append(f"方向反转：预测{pred_dir}，实际{actual_dir}")

    predicted = float(row["pred_return"])
    actual = float(row["actual_return"])
    if abs(actual - predicted) > 0.02:
        reasons.append(f"幅度偏差大：预测{_pct(predicted)}，实际{_pct(actual)}")

    if feature_row is not None:
        rsi = feature_row.get("rsi_14")
        if pd.notna(rsi):
            if float(rsi) > 70 and actual < 0:
                reasons.append(f"RSI 超买（{float(rsi):.1f}）后回落")
            elif float(rsi) < 30 and actual > 0:
                reasons.append(f"RSI 超卖（{float(rsi):.1f}）后反弹")
        volume_z = feature_row.get("volume_z_20")
        if pd.notna(volume_z) and abs(float(volume_z)) > 2:
            reasons.append("成交量异常放大，短线结构被打破")
        dxy = feature_row.get("dxy_ret_1")
        if pd.notna(dxy) and abs(float(dxy)) > 0.008:
            reasons.append(f"美元指数单日变动 {_pct(dxy)}")
        spx = feature_row.get("spx_ret_1")
        if pd.notna(spx) and abs(float(spx)) > 0.012:
            reasons.append(f"标普单日变动 {_pct(spx)}")
        vix = feature_row.get("vix_change_1")
        if pd.notna(vix) and abs(float(vix)) > 0.12:
            reasons.append(f"VIX 单日变动 {_pct(vix)}")

    if news_rows:
        avg = float(np.mean([n["score"] for n in news_rows]))
        if avg > 0.25 and actual < 0:
            reasons.append("当日新闻偏利好，但价格未兑现，可能已被提前定价")
        elif avg < -0.25 and actual > 0:
            reasons.append("当日新闻偏利空，但价格逆势上涨，可能利空出尽")

    if len(reasons) == 1:
        reasons.append("暂未发现单一宏观/新闻解释，优先视为噪声或模型盲区")
    return reasons


def failure_table(limit: int = 12) -> list[dict[str, Any]]:
    backtest = load_backtest()
    features = _load_csv("dataset_features.csv")
    news = _load_csv("news_raw.csv")
    if backtest.empty:
        return []
    feature_index = features.set_index("date") if not features.empty else None
    wrong = backtest[backtest["correct"] == 0].sort_values("date").tail(limit)
    rows = []
    for _, row in wrong.iloc[::-1].iterrows():
        date = pd.Timestamp(row["date"]).normalize()
        feature_row = feature_index.loc[date] if feature_index is not None and date in feature_index.index else None
        if isinstance(feature_row, pd.DataFrame):
            feature_row = feature_row.iloc[-1]
        headlines = _news_for_date(news, date)
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "predicted": "上涨" if int(row["pred_direction"]) == 1 else "下跌",
                "actual": "上涨" if int(row["actual_direction"]) == 1 else "下跌",
                "predicted_return": float(row["pred_return"]),
                "actual_return": float(row["actual_return"]),
                "prob_up": float(row["prob_up"]),
                "reasons": explain_failure(row, feature_row, headlines),
                "news": headlines,
            }
        )
    return rows


def recent_validation(limit: int = 12) -> list[dict[str, Any]]:
    backtest = load_backtest()
    if backtest.empty:
        return []
    rows = []
    for _, row in backtest.sort_values("date").tail(limit).iloc[::-1].iterrows():
        rows.append(
            {
                "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                "predicted": "上涨" if int(row["pred_direction"]) == 1 else "下跌",
                "actual": "上涨" if int(row["actual_direction"]) == 1 else "下跌",
                "predicted_return": float(row["pred_return"]),
                "actual_return": float(row["actual_return"]),
                "predicted_close": float(row["pred_close"]),
                "actual_close": float(row["actual_close"]),
                "prob_up": float(row["prob_up"]),
                "correct": bool(row["correct"]),
            }
        )
    return rows


def write_daily_report() -> Path:
    prediction = load_prediction()
    metadata = load_metadata()
    backtest = load_backtest()
    importance = load_importance()
    news = _load_csv("news_raw.csv")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPORT_DIR / "daily"
    report_dir.mkdir(parents=True, exist_ok=True)

    lines = [f"# BTC 次日预测日报 {today}", ""]
    if prediction:
        lines += [
            "## 最新预测",
            "",
            f"- 已收盘 K 线：{prediction.get('last_candle_date')}",
            f"- 预测目标日：{prediction.get('target_date')}（UTC 日收盘）",
            f"- 当前收盘：${prediction.get('last_close'):,.2f}",
            f"- 预测收盘：${prediction.get('predicted_close'):,.2f}（{_pct(prediction.get('predicted_return'))}）",
            f"- 方向：{prediction.get('direction_cn')}；上涨概率：{float(prediction.get('prob_up', 0)) * 100:.1f}%",
            f"- 历史误差带（1σ）：${prediction.get('interval_low'):,.2f} ~ ${prediction.get('interval_high'):,.2f}",
            "",
        ]
    metrics = (metadata.get("metrics") or {}).get("all") or {}
    recent = (metadata.get("metrics") or {}).get("recent_90") or {}
    if metrics:
        lines += [
            "## 回测表现",
            "",
            f"- 全样本方向胜率：{metrics.get('accuracy', 0) * 100:.2f}%（{metrics.get('samples', 0)} 天）",
            f"- 近 90 天方向胜率：{recent.get('accuracy', 0) * 100:.2f}%（{recent.get('samples', 0)} 天）",
            f"- 始终看涨基线：{metrics.get('always_up_accuracy', 0) * 100:.2f}%",
            f"- 7 日动量基线：{metrics.get('momentum_accuracy', 0) * 100:.2f}%",
            f"- 逻辑回归基线：{metrics.get('logistic_accuracy', 0) * 100:.2f}%",
            f"- ≥65% 置信度胜率：{(metrics.get('high_conf_accuracy') or 0) * 100:.2f}%（覆盖 {metrics.get('high_conf_coverage', 0) * 100:.2f}%）",
            f"- 收盘价 MAPE：{metrics.get('mape_close', 0) * 100:.2f}%",
            f"- 理论多空收益（未计费用）：{_pct(metrics.get('strategy_return', 0))}",
            "",
        ]

    live = live_metrics()
    if live.get("samples") or live.get("pending"):
        live_acc = (
            f"{live['accuracy'] * 100:.2f}%"
            if live.get("samples") and live.get("accuracy") is not None
            else "暂无（等待次日收盘）"
        )
        lines += [
            "## 实盘预测记录",
            "",
            f"- 已评估：{live.get('samples', 0)} 天",
            f"- 方向胜率：{live_acc}",
            f"- 待验证：{live.get('pending', 0)} 天",
            "",
        ]

    validation = recent_validation(12)
    if validation:
        lines += ["## 最近验证", "", "| 日期 | 预测 | 实际 | 预测涨跌 | 实际涨跌 | 结果 |", "|---|---|---|---|---|---|"]
        for item in validation:
            lines.append(
                f"| {item['date']} | {item['predicted']} | {item['actual']} | "
                f"{_pct(item['predicted_return'])} | {_pct(item['actual_return'])} | "
                f"{'✓' if item['correct'] else '✗'} |"
            )
        lines.append("")

    failures = failure_table(8)
    if failures:
        lines += ["## 失败复盘", ""]
        for item in failures:
            lines.append(f"### {item['date']}")
            lines.append(f"- 预测 {item['predicted']}（{_pct(item['predicted_return'])}），实际 {item['actual']}（{_pct(item['actual_return'])}）")
            lines.append(f"- 原因：{'；'.join(item['reasons'])}")
            if item["news"]:
                lines.append("- 当日新闻：" + "；".join(n["title"] for n in item["news"][:3]))
            lines.append("")

    if not news.empty:
        latest_date = news["date"].max()
        latest_news = _news_for_date(news, latest_date, 8)
        if latest_news:
            lines += [f"## 最新新闻（{latest_date.date()}）", ""]
            for item in latest_news:
                lines.append(f"- [{item['source']}] {item['title']}（情绪 {item['score']:+.2f}）")
            lines.append("")

    if not importance.empty:
        lines += ["## 当前特征重要性", ""]
        for _, item in importance.head(10).iterrows():
            lines.append(f"- {item['feature']}: {float(item['importance']):.4f}")
        lines.append("")

    text = "\n".join(lines).strip() + "\n"
    dated = report_dir / f"{today}.md"
    dated.write_text(text, encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(text, encoding="utf-8")
    return dated


if __name__ == "__main__":
    print(write_daily_report())
