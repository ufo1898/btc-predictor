from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.pipeline import bootstrap  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="首次初始化 BTC 预测项目")
    parser.add_argument("--news-days", type=int, default=180, help="Google News 历史回填天数，默认 180")
    args = parser.parse_args()
    result = bootstrap(news_days=max(1, args.news_days))
    prediction = result.get("prediction", {})
    print("\n完成。")
    print(f"目标日: {prediction.get('target_date')}")
    print(f"方向: {prediction.get('direction_cn')} / 概率: {float(prediction.get('prob_up', 0)) * 100:.1f}%")
    print(f"预测收盘: {prediction.get('predicted_close'):,.2f}")
    print("启动界面: python app.py")


if __name__ == "__main__":
    main()
