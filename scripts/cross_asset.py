from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.cross_asset import run_cross_asset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC/ETH/SOL 跨资产泛化检验")
    parser.add_argument("--refresh", action="store_true", help="先抓取 ETH/SOL 的日线数据")
    args = parser.parse_args()
    if args.refresh:
        from config import ASSET_SYMBOLS
        from src.data_pipeline import fetch_binance_klines

        for name, symbol in ASSET_SYMBOLS.items():
            fetch_binance_klines(symbol=symbol, name=f"{name}_daily")
    summary = run_cross_asset()
    print("\n跨资产结果：")
    for name, info in summary.items():
        all_metrics = (info.get("metrics") or {}).get("all") or {}
        print(
            f"- {name.upper()}: 胜率 {float(all_metrics.get('accuracy', 0)) * 100:.2f}% "
            f"（n={all_metrics.get('samples', 0)}）, AUC {all_metrics.get('auc')}, "
            f"扣费后收益 {float(all_metrics.get('strategy_return', 0)) * 100:+.2f}%"
        )


if __name__ == "__main__":
    main()
