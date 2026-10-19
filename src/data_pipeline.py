from __future__ import annotations

import email.utils
import math
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from config import (
    DATA_DIR,
    HISTORY_START,
    NEWS_BACKFILL_DAYS,
    NEWS_MAX_PER_DAY,
    NEWS_SLEEP_SECONDS,
    ONCHAIN_METRICS,
    RSS_FEEDS,
    SYMBOL,
    YAHOO_SYMBOLS,
)
from src.http import get, get_json


def _utc_date(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.tz_localize(None).normalize()


def _ms_date(value: int | float) -> pd.Timestamp:
    return pd.to_datetime(value, unit="ms", utc=True).tz_localize(None).normalize()


def _save(df: pd.DataFrame, name: str) -> Path:
    path = DATA_DIR / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "1.0", "yes"])


def _load(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def fetch_binance_klines(start: str = HISTORY_START) -> pd.DataFrame:
    """Fetch all daily BTCUSDT candles from Binance spot."""
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    rows: list[list[object]] = []
    cursor = start_ms
    while True:
        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={SYMBOL}&interval=1d&startTime={cursor}&limit=1000"
        )
        batch = get_json(url, timeout=30)
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        if len(batch) < 1000 or last_open <= cursor:
            break
        cursor = last_open + 86_400_000
        time.sleep(0.15)

    if not rows:
        raise RuntimeError("Binance returned no BTCUSDT candles")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    records = []
    for r in rows:
        close_time = int(r[6])
        records.append(
            {
                "date": _ms_date(int(r[0])),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
                "quote_volume": float(r[7]),
                "trades": int(r[8]),
                "taker_buy_base": float(r[9]),
                "taker_buy_quote": float(r[10]),
                "close_time": close_time,
                "complete": bool(close_time < now_ms),
            }
        )
    df = pd.DataFrame(records).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    _save(df, "btc_daily.csv")
    return df


def fetch_yahoo(name: str, symbol: str, range_: str = "10y") -> pd.DataFrame:
    """Fetch a daily macro series from Yahoo Finance."""
    encoded = symbol.replace("^", "%5E").replace("=", "%3D")
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?range={range_}&interval=1d&events=history"
    )
    payload = get_json(url, timeout=40)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo returned no result for {symbol}")
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = ((item.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    rows = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        rows.append({"date": _ms_date(int(ts) * 1000), "close": float(close)})
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    _save(df, f"macro_{name}.csv")
    return df


def fetch_all_macro() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for name, symbol in YAHOO_SYMBOLS.items():
        try:
            out[name] = fetch_yahoo(name, symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"[macro] {name} failed: {exc}", flush=True)
    return out


def fetch_fear_greed() -> pd.DataFrame:
    payload = get_json("https://api.alternative.me/fng/?limit=0&format=json", timeout=30)
    records = []
    for item in payload.get("data", []):
        try:
            records.append(
                {
                    "date": _utc_date(datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc)),
                    "fng_value": float(item["value"]),
                    "fng_class": item.get("value_classification", ""),
                }
            )
        except Exception:
            continue
    df = pd.DataFrame(records).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    _save(df, "fear_greed.csv")
    return df


def fetch_onchain() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for name, metric in ONCHAIN_METRICS.items():
        url = (
            f"https://api.blockchain.info/charts/{metric}"
            "?timespan=all&format=json&sampled=false"
        )
        try:
            payload = get_json(url, timeout=45)
            values = payload.get("values") or []
            rows = [
                {"date": _utc_date(datetime.fromtimestamp(int(v["x"]), tz=timezone.utc)), name: float(v["y"])}
                for v in values
            ]
            df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
            frames.append(df)
            print(f"[onchain] {name}: {len(df)} rows", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[onchain] {name} failed: {exc}", flush=True)
    if not frames:
        return pd.DataFrame()
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="date", how="outer")
    out = out.sort_values("date").reset_index(drop=True)
    _save(out, "onchain.csv")
    return out


def fetch_funding_rate() -> pd.DataFrame:
    start_ms = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    rows: list[dict[str, object]] = []
    cursor = start_ms
    while True:
        url = (
            "https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={SYMBOL}&startTime={cursor}&limit=1000"
        )
        batch = get_json(url, timeout=30)
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            rows.append(
                {
                    "date": _ms_date(int(item["fundingTime"])),
                    "funding_rate": float(item["fundingRate"]),
                }
            )
        last = int(batch[-1]["fundingTime"])
        if len(batch) < 1000 or last <= cursor:
            break
        cursor = last + 1
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    daily = (
        df.groupby("date", as_index=False)
        .agg(funding_rate_last=("funding_rate", "last"), funding_rate_mean=("funding_rate", "mean"))
        .sort_values("date")
    )
    _save(daily, "funding_rate.csv")
    return daily


def _fetch_futures_data(endpoint: str, columns: dict[str, str]) -> pd.DataFrame:
    url = (
        f"https://fapi.binance.com/futures/data/{endpoint}"
        f"?symbol={SYMBOL}&period=1d&limit=500"
    )
    payload = get_json(url, timeout=30)
    rows = []
    for item in payload or []:
        row = {"date": _ms_date(int(item["timestamp"]))}
        for src, dst in columns.items():
            row[dst] = float(item[src])
        rows.append(row)
    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date") if rows else pd.DataFrame()


def fetch_derivatives() -> pd.DataFrame:
    funding = fetch_funding_rate()
    try:
        oi = _fetch_futures_data(
            "openInterestHist",
            {"sumOpenInterest": "open_interest", "sumOpenInterestValue": "open_interest_value"},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[derivatives] open interest failed: {exc}", flush=True)
        oi = pd.DataFrame()
    try:
        lsr = _fetch_futures_data(
            "globalLongShortAccountRatio",
            {"longAccount": "long_account", "shortAccount": "short_account", "longShortRatio": "long_short_ratio"},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[derivatives] long/short failed: {exc}", flush=True)
        lsr = pd.DataFrame()

    frames = [f for f in (funding, oi, lsr) if not f.empty]
    if not frames:
        return pd.DataFrame()
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="date", how="outer")
    out = out.sort_values("date").reset_index(drop=True)
    _save(out, "derivatives.csv")
    return out


POSITIVE_TERMS: dict[str, float] = {
    "surge": 1.2, "surges": 1.2, "soar": 1.4, "soars": 1.4, "rally": 1.2, "rallies": 1.2,
    "bullish": 1.3, "breakout": 1.1, "record high": 1.5, "all-time high": 1.5, "ath": 1.2,
    "etf inflow": 1.5, "inflows": 1.0, "adoption": 1.1, "approval": 1.2, "approved": 1.1,
    "institutional": 0.8, "accumulation": 0.9, "accumulate": 0.9, "buy": 0.7, "buying": 0.8,
    "partnership": 0.8, "launch": 0.6, "upgrade": 0.8, "halving": 0.7, "support": 0.5,
    "optimism": 0.9, "optimistic": 0.9, "recovery": 0.8, "rebound": 0.9, "gain": 0.7,
    "gains": 0.7, "rise": 0.7, "rises": 0.7, "higher": 0.5, "strong": 0.6,
    "demand": 0.6, "treasury": 0.5, "reserve": 0.5, "whale": 0.4, "inflow": 1.0,
}
NEGATIVE_TERMS: dict[str, float] = {
    "crash": 1.5, "crashes": 1.5, "plunge": 1.4, "plunges": 1.4, "dump": 1.3, "dumps": 1.3,
    "bearish": 1.3, "sell-off": 1.2, "selloff": 1.2, "liquidation": 1.2, "liquidations": 1.2,
    "hack": 1.6, "hacked": 1.6, "exploit": 1.5, "fraud": 1.4, "lawsuit": 1.1, "sue": 1.0,
    "sec sues": 1.5, "ban": 1.3, "banned": 1.3, "outflow": 1.1, "outflows": 1.1,
    "recession": 1.2, "inflation": 0.7, "rate hike": 1.0, "default": 1.1, "bankruptcy": 1.4,
    "fear": 0.8, "warning": 0.9, "risk": 0.4, "resistance": 0.5, "weak": 0.6,
    "decline": 0.7, "declines": 0.7, "fall": 0.7, "falls": 0.7, "lower": 0.5,
    "drop": 0.8, "drops": 0.8, "loss": 0.7, "losses": 0.7, "pressure": 0.5,
}


def score_headline(text: str) -> tuple[float, float, float]:
    low = (text or "").lower()
    pos = sum(weight for term, weight in POSITIVE_TERMS.items() if term in low)
    neg = sum(weight for term, weight in NEGATIVE_TERMS.items() if term in low)
    score = (pos - neg) / math.sqrt(pos + neg + 1.0)
    return pos, neg, score


def _parse_pub_date(value: str | None, fallback: date | None = None) -> pd.Timestamp | None:
    if value:
        try:
            dt = email.utils.parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return _utc_date(dt)
        except Exception:
            pass
    if fallback is not None:
        return pd.Timestamp(fallback)
    return None


def parse_rss(xml_text: str | bytes, source: str, fallback_date: date | None = None) -> list[dict[str, object]]:
    if isinstance(xml_text, str):
        xml_text = xml_text.encode("utf-8", errors="ignore")
    root = ET.fromstring(xml_text)
    rows = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        published = _parse_pub_date(item.findtext("pubDate"), fallback_date)
        if published is None:
            continue
        pos, neg, score = score_headline(title)
        rows.append(
            {
                "date": published,
                "source": source,
                "title": title,
                "link": link,
                "positive": pos,
                "negative": neg,
                "score": score,
            }
        )
    return rows


def fetch_current_news() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source, url in RSS_FEEDS.items():
        try:
            response = get(url, timeout=30)
            rows.extend(parse_rss(response.content, source))
            print(f"[news] {source}: {len(rows)} cumulative", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[news] {source} failed: {exc}", flush=True)
    return _merge_news(rows)


def _merge_news(rows: Iterable[dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])
    df["title_key"] = df["title"].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    df = df.drop_duplicates(["date", "title_key"]).drop(columns=["title_key"])
    return df.sort_values(["date", "source", "title"]).reset_index(drop=True)


def fetch_google_news_day(day: pd.Timestamp) -> list[dict[str, object]]:
    day = pd.Timestamp(day).normalize()
    nxt = day + pd.Timedelta(days=1)
    q = f"bitcoin after:{day.date().isoformat()} before:{nxt.date().isoformat()}"
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    response = get(url, timeout=30)
    rows = parse_rss(response.content, "google_news", fallback_date=day.date())
    filtered = []
    for row in rows:
        if pd.Timestamp(row["date"]).normalize() == day:
            filtered.append(row)
    return filtered[:NEWS_MAX_PER_DAY]


def backfill_news(days: int = NEWS_BACKFILL_DAYS, end: date | None = None) -> pd.DataFrame:
    """Backfill Google News headlines for recent days. Existing rows are kept."""
    end_date = end or datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=max(1, days) - 1)
    existing = _load("news_raw.csv")
    rows: list[dict[str, object]] = existing.to_dict("records") if not existing.empty else []
    known_dates = set(existing["date"].dt.date) if not existing.empty else set()
    current = start_date
    fetched = 0
    while current <= end_date:
        ts = pd.Timestamp(current)
        if current not in known_dates:
            for attempt in range(3):
                try:
                    day_rows = fetch_google_news_day(ts)
                    rows.extend(day_rows)
                    fetched += 1
                    known_dates.add(current)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        print(f"[news] {current} skipped: {exc}", flush=True)
                    time.sleep(0.8 * (attempt + 1))
            time.sleep(NEWS_SLEEP_SECONDS)
        if fetched and fetched % 20 == 0:
            _merge_news(rows)
            print(f"[news] backfilled {fetched} days through {current}", flush=True)
        current += timedelta(days=1)
    df = _merge_news(rows)
    _save(df, "news_raw.csv")
    return df


def aggregate_news(df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None:
        df = _load("news_raw.csv")
    if df.empty:
        return pd.DataFrame(columns=["date", "news_sentiment", "news_pos_ratio", "news_neg_ratio", "news_count", "news_count_log", "news_sentiment_weighted", "news_available"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    grouped = df.groupby("date", as_index=False).agg(
        news_sentiment=("score", "mean"),
        news_pos=("positive", "sum"),
        news_neg=("negative", "sum"),
        news_count=("title", "count"),
    )
    denom = grouped["news_pos"] + grouped["news_neg"] + 1.0
    grouped["news_pos_ratio"] = grouped["news_pos"] / denom
    grouped["news_neg_ratio"] = grouped["news_neg"] / denom
    grouped["news_count_log"] = np.log1p(grouped["news_count"])
    grouped["news_sentiment_weighted"] = grouped["news_sentiment"] * grouped["news_count_log"]
    grouped["news_available"] = 1.0
    out = grouped[["date", "news_sentiment", "news_pos_ratio", "news_neg_ratio", "news_count", "news_count_log", "news_sentiment_weighted", "news_available"]]
    _save(out, "news_daily.csv")
    return out


def build_dataset() -> pd.DataFrame:
    btc = _load("btc_daily.csv")
    if btc.empty:
        btc = fetch_binance_klines()
    btc = btc[_as_bool(btc["complete"])].copy()
    btc = btc.sort_values("date").drop_duplicates("date")

    fng = _load("fear_greed.csv")
    if not fng.empty:
        btc = btc.merge(fng[["date", "fng_value"]], on="date", how="left")

    for name in YAHOO_SYMBOLS:
        macro = _load(f"macro_{name}.csv")
        if not macro.empty:
            macro = macro.rename(columns={"close": f"{name}_close"})
            btc = btc.merge(macro[["date", f"{name}_close"]], on="date", how="left")

    onchain = _load("onchain.csv")
    if not onchain.empty:
        onchain = onchain.sort_values("date").copy()
        # On-chain daily values are finalized after the UTC day; lag one day.
        for col in [c for c in onchain.columns if c != "date"]:
            onchain[col] = onchain[col].shift(1)
        btc = btc.merge(onchain, on="date", how="left")

    derivatives = _load("derivatives.csv")
    if not derivatives.empty:
        btc = btc.merge(derivatives, on="date", how="left")

    news_daily = _load("news_daily.csv")
    if news_daily.empty:
        news_daily = aggregate_news()
    if not news_daily.empty:
        btc = btc.merge(news_daily.drop(columns=["news_count"], errors="ignore"), on="date", how="left")
        btc["news_available"] = btc["news_available"].where(btc["news_available"] > 0)

    btc = btc.sort_values("date").reset_index(drop=True)
    _save(btc, "dataset_raw.csv")
    return btc


def refresh_all(include_news: bool = True, news_days: int = NEWS_BACKFILL_DAYS) -> None:
    print("[1/7] BTC daily candles", flush=True)
    fetch_binance_klines()
    print("[2/7] Fear & Greed", flush=True)
    fetch_fear_greed()
    print("[3/7] Macro (Yahoo)", flush=True)
    fetch_all_macro()
    print("[4/7] On-chain (Blockchain.com)", flush=True)
    fetch_onchain()
    print("[5/7] Derivatives (Binance futures)", flush=True)
    fetch_derivatives()
    if include_news:
        print("[6/7] News RSS + Google News backfill", flush=True)
        current = fetch_current_news()
        existing = _load("news_raw.csv")
        if not existing.empty:
            current = _merge_news(list(existing.to_dict("records")) + list(current.to_dict("records")))
        _save(current, "news_raw.csv")
        backfill_news(news_days)
        aggregate_news()
    else:
        print("[6/7] News skipped", flush=True)
    print("[7/7] Build merged dataset", flush=True)
    build_dataset()


if __name__ == "__main__":
    refresh_all()
