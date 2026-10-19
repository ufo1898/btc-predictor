from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.pipeline import update  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取最新数据、重训并生成预测")
    parser.add_argument("--news-days", type=int, default=2, help="最近新闻回填天数，默认 2")
    args = parser.parse_args()
    result = update(news_days=max(1, args.news_days))
    prediction = result.get("prediction", {})
    print("\n完成。")
    print(f"目标日: {prediction.get('target_date')}")
    print(f"方向: {prediction.get('direction_cn')} / 概率: {float(prediction.get('prob_up', 0)) * 100:.1f}%")
    print(f"预测收盘: {prediction.get('predicted_close'):,.2f}")


if __name__ == "__main__":
    main()
