from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"
REPORT_DIR = BASE_DIR / "reports"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

for _d in (DATA_DIR, MODEL_DIR, REPORT_DIR, STATIC_DIR, TEMPLATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SYMBOL = "BTCUSDT"
HISTORY_START = "2017-08-01"
TIMEZONE = "UTC"

# The machine reaches overseas APIs through the local SOCKS5 proxy.
# Set BTC_PRED_PROXY="" to go direct, or override it in the environment.
PROXY = os.getenv("BTC_PRED_PROXY", "socks5h://127.0.0.1:10020").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 4

NEWS_BACKFILL_DAYS = int(os.getenv("BTC_PRED_NEWS_DAYS", "180"))
NEWS_MAX_PER_DAY = 100
NEWS_SLEEP_SECONDS = 0.35

MIN_TRAIN_DAYS = 500
TEST_BLOCK_DAYS = 30
RANDOM_STATE = 42
TARGET_HORIZON = 1
WEEKLY_HORIZON = 7

# Execution assumptions for the long/short strategy (100% notional, no leverage).
# Fees and slippage are charged on every unit of notional traded; a long->short
# flip therefore pays both legs. Funding is paid/received every 8h.
TAKER_FEE_RATE = float(os.getenv("BTC_PRED_FEE", "0.0004"))
SLIPPAGE_RATE = float(os.getenv("BTC_PRED_SLIPPAGE", "0.0002"))
FUNDING_SETTLEMENTS_PER_DAY = 3
DEFAULT_FUNDING_RATE_8H = 0.0001

# Probability calibration. "sigmoid" is Platt scaling, "isotonic" is
# non-parametric; calibration is fitted inside each walk-forward training slice
# via cross-validation, so the test block is never used.
CALIBRATION_METHOD = os.getenv("BTC_PRED_CALIBRATION", "sigmoid").strip().lower()
CALIBRATION_CV = 3

# Significance tests.
BOOTSTRAP_ROUNDS = 2000
BLOCK_BOOTSTRAP_BLOCK = 10

# Cross-asset generalisation check targets.
ASSET_SYMBOLS = {
    "btc": "BTCUSDT",
    "eth": "ETHUSDT",
    "sol": "SOLUSDT",
}

YAHOO_SYMBOLS = {
    "dxy": "DX-Y.NYB",
    "spx": "^GSPC",
    "gold": "GC=F",
    "vix": "^VIX",
    "us10y": "^TNX",
    "qqq": "QQQ",
}

ONCHAIN_METRICS = {
    "active_addresses": "n-unique-addresses",
    "hash_rate": "hash-rate",
    "tx_fees": "transaction-fees",
    "mempool_size": "mempool-size",
    "miners_revenue": "miners-revenue",
}

RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
    "decrypt": "https://decrypt.co/feed",
    "google_news": "https://news.google.com/rss/search?q=bitcoin&hl=en-US&gl=US&ceid=US:en",
}

# Features are deliberately conservative: every external series is aligned to
# the BTC candle date and only information available by that daily close is used.
FEATURE_COLUMNS = [
    "ret_1", "ret_3", "ret_7", "ret_14", "ret_30", "ret_90",
    "vol_7", "vol_14", "vol_30", "vol_ratio_7_30",
    "sma_7_ratio", "sma_20_ratio", "sma_50_ratio", "sma_200_ratio",
    "ema_12_26_ratio", "macd_hist_norm",
    "rsi_14", "rsi_7", "bb_percent_b", "bb_width", "atr_14_pct",
    "range_pct", "close_location", "volume_z_20", "volume_change_1",
    "drawdown_30", "drawdown_90", "off_low_30", "off_low_90",
    "up_streak", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "above_sma200", "sma50_sma200_ratio", "vol_regime", "days_since_halving",
    "fng_value", "fng_change_1", "fng_change_7",
    "news_sentiment", "news_pos_ratio", "news_neg_ratio", "news_count_log",
    "news_sentiment_weighted", "news_available",
    "dxy_ret_1", "dxy_ret_5", "dxy_ret_20", "dxy_z_20",
    "spx_ret_1", "spx_ret_5", "spx_ret_20",
    "gold_ret_1", "gold_ret_5", "gold_ret_20",
    "vix_level", "vix_change_1", "vix_z_20",
    "us10y_level", "us10y_change_1", "us10y_change_5",
    "qqq_ret_1", "qqq_ret_5", "qqq_ret_20",
    "funding_rate_last", "funding_rate_mean_3", "funding_rate_mean_7",
    "oi_change_1", "oi_change_7", "long_short_ratio", "long_short_ratio_change_1",
    "addr_change_1", "addr_z_30", "hashrate_change_7",
    "fees_z_30", "mempool_z_30", "miner_rev_change_7",
]

# The cross-asset model deliberately drops BTC-only on-chain/derivatives
# features so BTC/ETH/SOL are compared on an identical common feature set.
CROSS_ASSET_FEATURES = [
    col
    for col in FEATURE_COLUMNS
    if col != "days_since_halving"
    and not col.startswith(("addr_", "hashrate_", "fees_", "mempool_", "miner_", "funding_", "oi_", "long_short_"))
] + ["btc_ret_1", "btc_ret_7", "btc_ret_30", "btc_vol_14"]
