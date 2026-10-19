# BTC 次日预测台

一个本地运行的 BTC 次日方向 / 收盘价预测系统。包含：

- Binance 现货日线（2017-08 至今）
- 技术指标、宏观、恐慌贪婪、链上、合约、新闻情绪等多因子
- Walk-forward 回测，严格避免未来函数
- 每日预测记录与次日自动验证
- Flask + 本地 ECharts 可视化界面
- 失败复盘、滚动胜率、置信度分层、特征贡献、数据源状态、自动日报

> 仅用于研究和学习，不构成投资建议。BTC 日线方向预测非常困难，第一版胜率只略高于基线，请勿据此实盘。

## 快速开始

```powershell
git clone https://github.com/ufo1898/btc-predictor.git
cd btc-predictor
python -m pip install -r requirements.txt

# 首次初始化。仓库不含 data/、models/、reports/，首次运行自动生成。
# 新闻回填较慢，先用 30 天快速跑通：
python scripts\bootstrap.py --news-days 30

# 启动界面
python app.py
```

浏览器打开：<http://127.0.0.1:5055>

首次全量新闻回填可用 `--news-days 180`，大约需要 5–8 分钟。也可以先不跑全量，界面右上角“更新数据并重训”会继续补齐。

## 每日更新

```powershell
cd C:\btc-predictor
python scripts\update.py
```

或在界面点击“更新数据并重训”。更新会：

1. 抓取最新 BTC 日线、宏观、链上、合约、新闻
2. 重建特征
3. 评估上一日预测
4. 重新做 walk-forward 回测
5. 重训最终模型并写入 `data/latest_prediction.json`
6. 生成 `reports/latest.md` 和当日日报

预测目标日按 **UTC 日收盘** 口径。建议在 UTC 00:00 之后、拿到完整日线后再更新。

## 目录

```text
C:\btc-predictor
├─ app.py                  Flask 入口
├─ config.py               路径、代理、特征列、模型参数
├─ requirements.txt
├─ data/
│  ├─ btc_daily.csv
│  ├─ dataset_raw.csv
│  ├─ dataset_features.csv
│  ├─ backtest.csv
│  ├─ predictions.csv      实盘预测记录（待验证/已验证）
│  ├─ latest_prediction.json
│  └─ ...
├─ models/
│  ├─ latest_model.joblib
│  └─ metadata.json
├─ reports/
│  ├─ latest.md
│  └─ daily/YYYY-MM-DD.md
├─ scripts/
│  ├─ bootstrap.py
│  └─ update.py
├─ src/
│  ├─ http.py              代理与重试
│  ├─ data_pipeline.py     数据抓取与合并
│  ├─ features.py          特征工程
│  ├─ modeling.py          回测、模型、评估
│  ├─ analysis.py          失败归因与日报
│  ├─ tracking.py          实盘预测记录与验证
│  └─ pipeline.py          编排
├─ static/
│  ├─ app.js
│  ├─ style.css
│  └─ echarts.min.js
└─ templates/
   └─ index.html
```

## 模型口径

- **目标**：用已收盘日 D 的特征预测 D+1 的收盘方向（涨/跌）和收盘价。
- **方向模型**：`HistGradientBoostingClassifier`
- **幅度模型**：`HistGradientBoostingRegressor`
- **基线**：逻辑回归、始终看涨、7 日动量。
- **回测**：从 500 天开始，每 30 天滚动训练/测试，所有预测均为样本外。
- **预测收盘**：方向模型符号 + 幅度模型绝对值，幅度截断在 ±15%，最小 0.1%。
- **误差带**：最近 180 天回测残差的标准差（约 1σ）。
- **每日优化**：每日重训 + 重新评估 + 失败归因；不做每日超参搜索，避免过拟合。
- **置信度**：`max(prob_up, 1 - prob_up)`；界面中 ≥65% 标为强信号，55%–65% 为中信号，低于 55% 为弱信号。

## 当前第一版结果

截至 2026-10-19，walk-forward 结果：

| 指标 | 结果 |
|---|---|
| 样本 | 2849 天 |
| 全样本方向胜率 | 53.0% |
| 近 90 天 | 62.2% |
| ≥65% 置信度胜率 / 覆盖 | 54.7% / 47.8% |
| 始终看涨基线 | 51.0% |
| 7 日动量基线 | 47.9% |
| 逻辑回归基线 | 52.7% |
| 收盘价 MAPE | 2.34% |
| 理论多空收益（未计费用） | +44.1% |

这些数字会随每日数据更新而变化。优势很小，且未计手续费、滑点、资金费率和极端行情冲击。

## 数据源

已验证可用：

- Binance Spot Klines
- Binance Futures：资金费率、持仓量、多空账户比
- alternative.me Fear & Greed
- Yahoo Finance：DXY、S&P 500、黄金、VIX、US10Y、QQQ
- Blockchain.com Charts：活跃地址、算力、手续费、内存池、矿工收入
- CoinDesk / Cointelegraph / Bitcoin Magazine / Decrypt RSS
- Google News 历史日期查询

当前不使用：

- FRED（超时）
- Stooq（返回 JS/拦截页）
- GDELT（429 限流）
- CryptoCompare（需要 API key）

## 环境注意事项

- 本机通过 `socks5h://127.0.0.1:10020` 访问海外 API。可在环境变量中覆盖：
  ```powershell
  $env:BTC_PRED_PROXY="socks5h://127.0.0.1:10020"
  ```
  设为空字符串可直连。
- `C:\requests.py` 会遮蔽真正的 `requests`，所以必须在 `C:\btc-predictor` 目录下运行 Python，或显式设置 `PYTHONPATH`。
- Yahoo `^GSPC` 偶尔 SSL 失败，`src/http.py` 会重试；仍失败时该日宏观特征会缺失，模型会按缺失值处理。
- 新闻回填是逐日请求，180 天大约 5–8 分钟；中断后重跑会跳过已有日期。
- 周末/节假日没有新的美股/宏观数据，相关特征会缺失；这是正常现象，不要用未来数据填补。

## 失败复盘

`data/backtest.csv` 记录每次样本外预测；`reports/latest.md` 会自动列出最近失败，并尝试从以下角度解释：

- 方向反转
- 幅度偏差过大
- RSI 超买/超卖
- 成交量异常
- 美元、标普、VIX 单日大变动
- 当日新闻情绪与价格相反

它只是归因提示，不是严格的因果解释。

## 后续可做

- 置信度阈值策略（只在强信号日输出方向）
- 更强的新闻 NLP / 事件抽取
- 加入 ETF 资金流、稳定币供应、期权 skew 等数据
- 模型集成与概率校准
- 每日自动更新（Windows 计划任务）
- 预测漂移监控与自动告警
