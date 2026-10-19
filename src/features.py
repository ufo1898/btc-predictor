from __future__ import annotations

import numpy as np
import pandas as pd

from config import DATA_DIR, FEATURE_COLUMNS


def _load(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(5, window // 3)).mean()
    std = series.rolling(window, min_periods=max(5, window // 3)).std()
    return (series - mean) / std.replace(0, np.nan)


def _ret(series: pd.Series, days: int) -> pd.Series:
    return series.pct_change(days, fill_method=None)


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    log_ret = np.log(close / close.shift(1))

    for n in (1, 3, 7, 14, 30, 90):
        df[f"ret_{n}"] = _ret(close, n)

    for n in (7, 14, 30):
        df[f"vol_{n}"] = log_ret.rolling(n, min_periods=max(3, n // 2)).std()
    df["vol_ratio_7_30"] = df["vol_7"] / df["vol_30"].replace(0, np.nan)

    for n in (7, 20, 50, 200):
        sma = close.rolling(n, min_periods=max(3, n // 2)).mean()
        df[f"sma_{n}_ratio"] = close / sma - 1

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    df["ema_12_26_ratio"] = (ema12 - ema26) / close
    df["macd_hist_norm"] = (macd - macd_signal) / close

    df["rsi_14"] = _rsi(close, 14)
    df["rsi_7"] = _rsi(close, 7)

    mid = close.rolling(20, min_periods=10).mean()
    std = close.rolling(20, min_periods=10).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    df["bb_percent_b"] = (close - lower) / (upper - lower).replace(0, np.nan)
    df["bb_width"] = (upper - lower) / mid.replace(0, np.nan)

    atr = _atr(df, 14)
    df["atr_14_pct"] = atr / close
    df["range_pct"] = (high - low) / close.replace(0, np.nan)
    df["close_location"] = (close - low) / (high - low).replace(0, np.nan)
    vol_mean = volume.rolling(20, min_periods=10).mean()
    vol_std = volume.rolling(20, min_periods=10).std()
    df["volume_z_20"] = (volume - vol_mean) / vol_std.replace(0, np.nan)
    df["volume_change_1"] = volume.pct_change(fill_method=None)

    df["drawdown_30"] = close / close.rolling(30, min_periods=15).max() - 1
    df["drawdown_90"] = close / close.rolling(90, min_periods=30).max() - 1
    df["off_low_30"] = close / close.rolling(30, min_periods=15).min() - 1
    df["off_low_90"] = close / close.rolling(90, min_periods=30).min() - 1

    direction = np.sign(close.diff()).fillna(0)
    streak = direction.copy()
    for i in range(1, len(streak)):
        if direction.iloc[i] != 0 and direction.iloc[i] == direction.iloc[i - 1]:
            streak.iloc[i] = streak.iloc[i - 1] + direction.iloc[i]
        else:
            streak.iloc[i] = direction.iloc[i]
    df["up_streak"] = streak.clip(-10, 10)

    dow = df["date"].dt.dayofweek.astype(float)
    month = df["date"].dt.month.astype(float)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)

    sma200 = close.rolling(200, min_periods=100).mean()
    sma50 = close.rolling(50, min_periods=30).mean()
    df["above_sma200"] = (close > sma200).astype(float)
    df["sma50_sma200_ratio"] = sma50 / sma200 - 1
    vol_median = df["vol_14"].rolling(90, min_periods=30).median()
    df["vol_regime"] = (df["vol_14"] > vol_median).astype(float)

    halvings = [pd.Timestamp("2012-11-28"), pd.Timestamp("2016-07-09"), pd.Timestamp("2020-05-11"), pd.Timestamp("2024-04-20")]
    since = []
    for d in df["date"]:
        prior = [h for h in halvings if h <= d]
        since.append((d - prior[-1]).days / 365.25 if prior else np.nan)
    df["days_since_halving"] = since
    return df


def _ensure_column(df: pd.DataFrame, name: str, value: object = np.nan) -> None:
    if name not in df.columns:
        df[name] = value


def add_external_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    _ensure_column(df, "fng_value")
    df["fng_change_1"] = df["fng_value"].diff(1)
    df["fng_change_7"] = df["fng_value"].diff(7)

    for name in ("dxy", "spx", "gold", "vix", "us10y", "qqq"):
        col = f"{name}_close"
        _ensure_column(df, col)
        close = pd.to_numeric(df[col], errors="coerce")
        if name == "us10y":
            close = close / 10.0
            df["us10y_level"] = close
            df["us10y_change_1"] = close.diff(1)
            df["us10y_change_5"] = close.diff(5)
        elif name == "vix":
            df["vix_level"] = close
            df["vix_change_1"] = close.pct_change(fill_method=None)
            df["vix_z_20"] = _zscore(close, 20)
        else:
            df[f"{name}_ret_1"] = close.pct_change(fill_method=None)
            df[f"{name}_ret_5"] = _ret(close, 5)
            df[f"{name}_ret_20"] = _ret(close, 20)
            if name == "dxy":
                df["dxy_z_20"] = _zscore(close, 20)

    for col in ("funding_rate_last", "funding_rate_mean", "open_interest", "long_short_ratio"):
        _ensure_column(df, col)
    df["funding_rate_mean_3"] = df["funding_rate_mean"].rolling(3, min_periods=1).mean()
    df["funding_rate_mean_7"] = df["funding_rate_mean"].rolling(7, min_periods=2).mean()
    df["oi_change_1"] = df["open_interest"].pct_change(fill_method=None)
    df["oi_change_7"] = _ret(df["open_interest"], 7)
    df["long_short_ratio_change_1"] = df["long_short_ratio"].pct_change(fill_method=None)

    for col in ("active_addresses", "hash_rate", "tx_fees", "mempool_size", "miners_revenue"):
        _ensure_column(df, col)
    df["addr_change_1"] = df["active_addresses"].pct_change(fill_method=None)
    df["addr_z_30"] = _zscore(df["active_addresses"], 30)
    df["hashrate_change_7"] = _ret(df["hash_rate"], 7)
    df["fees_z_30"] = _zscore(df["tx_fees"], 30)
    df["mempool_z_30"] = _zscore(df["mempool_size"], 30)
    df["miner_rev_change_7"] = _ret(df["miners_revenue"], 7)

    for col in ("news_sentiment", "news_pos_ratio", "news_neg_ratio", "news_count_log", "news_sentiment_weighted", "news_available"):
        _ensure_column(df, col)
    return df


def add_target(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["target_close"] = df["close"].shift(-1)
    df["target_return"] = df["target_close"] / df["close"] - 1
    df["target_direction"] = np.where(df["target_return"].notna(), (df["target_return"] > 0).astype(float), np.nan)
    df["target_close_7"] = df["close"].shift(-7)
    df["target_return_7"] = df["target_close_7"] / df["close"] - 1
    df["target_direction_7"] = np.where(df["target_return_7"].notna(), (df["target_return_7"] > 0).astype(float), np.nan)
    return df


def build_features(
    raw_name: str = "dataset_raw.csv",
    out_name: str = "dataset_features.csv",
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    feature_columns = feature_columns or FEATURE_COLUMNS
    raw = _load(raw_name)
    if raw.empty:
        raise RuntimeError(f"{raw_name} is empty; run data refresh first")
    df = add_technical_features(raw)
    df = add_external_features(df)
    df = add_target(df)
    for col in feature_columns:
        _ensure_column(df, col)
    df[feature_columns] = df[feature_columns].replace([np.inf, -np.inf], np.nan)
    out = df.sort_values("date").reset_index(drop=True)
    out.to_csv(DATA_DIR / out_name, index=False, encoding="utf-8-sig")
    return out


def load_features(name: str = "dataset_features.csv") -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    return df


if __name__ == "__main__":
    print(build_features().tail())
