# BTC 次日预测台

一个本地运行的 BTC 次日方向 / 收盘价预测系统。包含：

- Binance 现货日线（2017-08 至今）
- 技术指标、宏观、恐慌贪婪、链上、合约、新闻情绪等多因子
- Walk-forward 回测，严格避免未来函数
- 交易成本模型：手续费 + 滑点 + 资金费率，给出真实的扣费后收益
- 胜率显著性检验：二项检验 + bootstrap + 块 bootstrap 置信区间
- 概率校准（Platt / isotonic），让"70% 上涨概率"真的接近 70%
- 周线（7 天）方向与价格预测，含非重叠样本评估
- BTC / ETH / SOL 跨资产泛化检验（同一特征集与流程）
- 每日预测记录与次日自动验证
- Flask + 本地 ECharts 可视化界面
- 失败复盘、滚动胜率、置信度分层、特征贡献、数据源状态、自动日报

> 仅用于研究和学习，不构成投资建议。BTC 日线方向预测非常困难，请特别关注显著性检验与扣费后收益的结论，不要只看名义胜率。

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

完整 bootstrap（含日线 + 周线 walk-forward、概率校准、跨资产检验）在普通机器上约需 25–40 分钟。只更新预测、不重跑跨资产检验时，运行 `python scripts\update.py` 大约 8–12 分钟。单独跑跨资产检验：`python scripts\cross_asset.py`。

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
│  ├─ btc_daily.csv / eth_daily.csv / sol_daily.csv
│  ├─ dataset_raw.csv
│  ├─ dataset_features.csv
│  ├─ dataset_raw_cross_*.csv    跨资产合并数据（BTC/ETH/SOL）
│  ├─ backtest.csv
│  ├─ backtest_weekly.csv        周线回测
│  ├─ backtest_cross_*.csv       跨资产回测
│  ├─ cross_asset.json / cross_asset.csv
│  ├─ predictions.csv            实盘预测记录（当日）
│  ├─ weekly_predictions.csv     实盘预测记录（周线）
│  ├─ latest_prediction.json     含 daily + weekly 预测
│  └─ ...
├─ models/
│  ├─ latest_model.joblib
│  └─ metadata.json
├─ reports/
│  ├─ latest.md
│  └─ daily/YYYY-MM-DD.md
├─ scripts/
│  ├─ bootstrap.py
│  ├─ update.py
│  └─ cross_asset.py
├─ src/
│  ├─ http.py              代理与重试
│  ├─ data_pipeline.py     数据抓取与合并（多资产）
│  ├─ features.py          特征工程
│  ├─ modeling.py          回测、模型、评估、成本、显著性、校准
│  ├─ cross_asset.py       BTC/ETH/SOL 跨资产检验
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

- **目标**：用已收盘日 D 的特征预测 D+1（日线）与 D+7（周线）的收盘方向（涨/跌）和收盘价。
- **方向模型**：`HistGradientBoostingClassifier`
- **幅度模型**：`HistGradientBoostingRegressor`
- **基线**：逻辑回归、始终看涨、7 日动量。
- **回测**：从 500 天开始，每 30 天滚动训练/测试，所有预测均为样本外。
- **预测收盘**：方向模型符号 + 幅度模型绝对值，幅度截断在 ±15%，最小 0.1%。
- **误差带**：最近回测残差的标准差（日线取 180 天，周线取 120 次，约 1σ）。
- **每日优化**：每日重训 + 重新评估 + 失败归因；不做每日超参搜索，避免过拟合。
- **置信度**：`max(prob_up, 1 - prob_up)`；界面中 ≥65% 标为强信号，55%–65% 为中信号，低于 55% 为弱信号。

### 概率校准

- 默认 Platt/sigmoid（可用环境变量 `BTC_PRED_CALIBRATION=isotonic` 切换）。
- 校准器用**扩展窗口时间序列交叉验证**拟合：只用训练窗口内更早的数据训练子模型、预测更晚的块，再把这些样本外概率与标签拟合校准曲线。测试段从不参与，避免泄漏。
- 不使用 sklearn 默认的随机洗牌 CV：金融时间序列被打乱后，校准器会学出接近零甚至负的斜率，把概率压平、并让方向决策退化到 50%。
- 默认 sigmoid 校准不带截距：曲线单调且以 p=0.5 为不动点，因此**方向决策与原始概率完全一致**，校准只修正置信度的含义（说 70% 更接近真的 70%）；isotonic 仅作为实验选项。
- HGB 使用原生 NaN 处理；每个训练折内只丢弃全 NaN/常量列（不做中位数插补），避免插补损失信号。
- 输出 ECE / Brier / log loss 和置信度可靠性表，用于检查"说 70% 是否真的是 70%"；同时保留原始概率决策胜率作为对照。

### 交易成本模型（多空策略）

- 按 100% 名义本金、无杠杆、每天调仓计算。
- 手续费 `0.04%`/边（`BTC_PRED_FEE` 可覆盖）、滑点 `0.02%`/边（`BTC_PRED_SLIPPAGE`）。
- 换手按仓位变化计：开仓/平仓 1 倍名义，多空翻转 2 倍名义。
- 资金费按真实 `funding_rate_mean` 结算（每天 3 次），缺失时回退到 `0.01%/8h` 保守估计。
- 报告同时给出未计成本收益、成本拖累、最大回撤、Sharpe 和始终做多基准。

### 统计显著性

- 对全样本胜率做双侧二项检验（对 50% 随机基线）。
- bootstrap（2000 轮）与块 bootstrap（block=10，保留自相关结构）给出 95% 置信区间。
- 若 p ≥ 0.05 或置信区间覆盖 50%，结论一律标注为"不显著"。

### 周线预测

- 目标为 7 天后的 UTC 收盘价与方向，与日线共用特征集，独立 walk-forward。
- 由于相邻周线样本重叠，另做"每 7 天取 1"的非重叠评估与显著性检验，报表以非重叠为准。

### 跨资产泛化检验

- BTC / ETH / SOL 使用同一套通用特征（去掉 BTC 专属的链上、合约、减半特征，加入 BTC 收益率上下文）与同一训练流程。
- 用于检验模型是否只是 BTC 历史上的特例；如果只有 BTC 有效，需视为过拟合风险信号。

## 当前结果（2026-10-19，第二版）

截至 2026-10-19，walk-forward 结果：

| 指标 | 结果 |
|---|---|
| 日线样本 | 2849 天 |
| 日线方向胜率 | 52.8%（二项检验 p=0.003；块 bootstrap 95% CI 51.0%–54.6%） |
| 近 90 天 | 58.9% |
| ≥65% 置信度胜率 / 覆盖 | 57.4% / 8.8% |
| 始终看涨 / 逻辑回归 / 7 日动量 | 51.0% / 52.8% / 48.0% |
| 收盘价 MAPE | 2.34% |
| 多空收益（未计成本） | +41.2% |
| 多空收益（计成本后） | **-57.2%**（手续费 45.1%、滑点 22.6%、资金费 51.4%） |
| 最大回撤 / Sharpe | -83.8% / 0.14 |
| 周线胜率（全样本 / 非重叠） | 50.8% / 52.3%（n=407，p=0.37，不显著） |
| 跨资产日线胜率 | BTC 52.0%（p=0.033） · ETH 52.9%（p=0.002） · SOL 52.2%（p=0.063） |

- 校准后 ECE 2.54%（Brier 0.254 vs 原始 0.275），置信度基本可信，但概率整体被压缩到 0.50–0.55 附近——模型真实置信度本来就很低。
- 方向优势在统计上显著，但幅度极小；按"每天调仓、100% 名义本金"的口径，手续费、滑点和资金费会吃掉全部收益，**当前策略不具备直接实盘价值**。
- 周线没有可检出的优势；跨资产（ETH/SOL）胜率与 BTC 接近，说明信号不是纯 BTC 过拟合，但同样微弱。
- 这些数字会随每日数据更新而变化。

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
- 模型集成（多模型投票 / stacking）
- 每日自动更新（Windows 计划任务）
- 预测漂移监控与自动告警
