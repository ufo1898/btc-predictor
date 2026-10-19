const $ = (id) => document.getElementById(id);
const qsa = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  data: null,
  range: 180,
  tab: 'backtest',
  charts: {},
  busy: false,
};

const FEATURE_LABELS = {
  ret_1: '1日收益',
  ret_3: '3日收益',
  ret_7: '7日收益',
  ret_14: '14日收益',
  ret_30: '30日收益',
  ret_90: '90日收益',
  vol_7: '7日波动率',
  vol_14: '14日波动率',
  vol_30: '30日波动率',
  vol_ratio_7_30: '短长波动比',
  sma_7_ratio: 'SMA7 偏离',
  sma_20_ratio: 'SMA20 偏离',
  sma_50_ratio: 'SMA50 偏离',
  sma_200_ratio: 'SMA200 偏离',
  ema_12_26_ratio: 'EMA12/26',
  macd_hist_norm: 'MACD 柱',
  rsi_14: 'RSI 14',
  rsi_7: 'RSI 7',
  bb_percent_b: '布林 %B',
  bb_width: '布林宽度',
  atr_14_pct: 'ATR 14',
  range_pct: '日内振幅',
  close_location: '收盘位置',
  volume_z_20: '成交量 Z',
  volume_change_1: '成交量变化',
  drawdown_30: '30日回撤',
  drawdown_90: '90日回撤',
  off_low_30: '距30日低点',
  off_low_90: '距90日低点',
  up_streak: '连涨/连跌',
  dow_sin: '星期周期 sin',
  dow_cos: '星期周期 cos',
  month_sin: '月份周期 sin',
  month_cos: '月份周期 cos',
  above_sma200: '站上 SMA200',
  sma50_sma200_ratio: 'SMA50/200',
  vol_regime: '波动状态',
  days_since_halving: '减半天数',
  fng_value: '恐慌贪婪',
  fng_change_1: '恐慌贪婪日变',
  fng_change_7: '恐慌贪婪周变',
  dxy_ret_1: 'DXY 日收益',
  dxy_ret_5: 'DXY 5日收益',
  dxy_ret_20: 'DXY 20日收益',
  dxy_z_20: 'DXY Z',
  spx_ret_1: '标普日收益',
  spx_ret_5: '标普5日收益',
  spx_ret_20: '标普20日收益',
  gold_ret_1: '黄金日收益',
  gold_ret_5: '黄金5日收益',
  gold_ret_20: '黄金20日收益',
  vix_level: 'VIX 水平',
  vix_change_1: 'VIX 日变',
  vix_z_20: 'VIX Z',
  us10y_level: '美债10Y',
  us10y_change_1: '美债10Y日变',
  us10y_change_5: '美债10Y 5日变',
  qqq_ret_1: '纳指ETF日收益',
  qqq_ret_5: '纳指ETF 5日',
  qqq_ret_20: '纳指ETF 20日',
  funding_rate_last: '最新资金费率',
  funding_rate_mean: '资金费率均值',
  funding_rate_mean_3: '资金费率3日均',
  funding_rate_mean_7: '资金费率7日均',
  open_interest: '未平仓量',
  oi_change_1: 'OI 日变',
  oi_change_7: 'OI 7日变',
  long_short_ratio: '多空比',
  long_short_ratio_change_1: '多空比日变',
  active_addresses: '活跃地址',
  addr_change_1: '活跃地址日变',
  addr_z_30: '活跃地址 Z',
  hash_rate: '算力',
  hashrate_change_7: '算力7日变',
  tx_fees: '交易手续费',
  fees_z_30: '手续费 Z',
  mempool_size: '内存池',
  mempool_z_30: '内存池 Z',
  miners_revenue: '矿工收入',
  miner_rev_change_7: '矿工收入7日变',
  news_sentiment: '新闻情绪',
  news_pos_ratio: '新闻正面占比',
  news_neg_ratio: '新闻负面占比',
  news_count_log: '新闻数量',
  news_sentiment_weighted: '加权新闻情绪',
  news_available: '新闻可用',
};

function formatUsd(value, digits = null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  const d = digits === null ? (n >= 1000 ? 2 : n >= 1 ? 2 : 4) : digits;
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

function formatPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return (Number(value) * 100).toFixed(digits) + '%';
}

function formatSignedPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const n = Number(value) * 100;
  return (n >= 0 ? '+' : '') + n.toFixed(digits) + '%';
}

function formatTime(value) {
  if (!value) return '--';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('zh-CN', { timeZone: 'UTC', hour12: false });
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function isUp(direction) {
  return direction === 'up' || direction === '上涨' || direction === 1 || direction === '1';
}

function dirBadge(direction) {
  const up = isUp(direction);
  return `<span class="badge ${up ? 'up' : 'down'}">${up ? '上涨' : '下跌'}</span>`;
}

function resultBadge(correct) {
  if (correct === null || correct === undefined) return '<span class="badge pending">待验证</span>';
  return correct ? '<span class="badge ok">正确</span>' : '<span class="badge bad">错误</span>';
}

function pctClass(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'dim';
  return Number(value) >= 0 ? 'green' : 'red';
}

function empty(text = '暂无数据') {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

function table(headers, rows) {
  if (!rows.length) return empty();
  return `<table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function setStatus(kind, text) {
  const dot = $('status-dot');
  dot.className = 'status-dot' + (kind ? ' ' + kind : '');
  $('status-text').textContent = text;
}

function showBanner(message, isError = false) {
  const el = $('banner');
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.classList.remove('hidden');
}

function hideBanner() {
  $('banner').classList.add('hidden');
}

function renderHeader() {
  const data = state.data;
  const last = data.market && data.market.last;
  if (last) {
    $('btc-price').textContent = formatUsd(last.close);
    const change = last.change_1d;
    const changeEl = $('btc-change');
    changeEl.textContent = `${change >= 0 ? '+' : ''}${formatPct(change)} · 24h`;
    changeEl.className = 'sub ' + (change >= 0 ? 'up' : 'down');
    $('btc-date').textContent = `日线 ${last.date} · UTC`;
  }

  const p = data.prediction || {};
  if (p.target_date) {
    $('pred-target').textContent = p.target_date;
    const dir = isUp(p.direction) ? 'up' : 'down';
    const dirEl = $('pred-direction');
    dirEl.textContent = p.direction_cn || (dir === 'up' ? '上涨' : '下跌');
    dirEl.className = dir;
    const prob = dir === 'up' ? p.prob_up : 1 - p.prob_up;
    $('pred-prob').textContent = `${dir === 'up' ? '上涨' : '下跌'}概率 ${(Number(prob) * 100).toFixed(1)}%`;
    const confidence = Number(p.confidence ?? 0);
    const signal = confidence >= 0.65 ? '强信号' : confidence >= 0.55 ? '中信号' : '弱信号';
    const signalEl = $('pred-signal');
    signalEl.textContent = signal;
    signalEl.className = 'signal ' + (confidence >= 0.65 ? 'strong' : confidence >= 0.55 ? 'mid' : 'weak');
    $('pred-close').textContent = formatUsd(p.predicted_close);
    $('pred-band').textContent = `1σ ${formatUsd(p.interval_low)} – ${formatUsd(p.interval_high)} · 幅度 ${formatSignedPct(p.predicted_return)}`;
  } else {
    $('pred-target').textContent = '--';
    $('pred-direction').textContent = '--';
    $('pred-prob').textContent = '--';
    $('pred-signal').textContent = '--';
    $('pred-signal').className = 'signal';
    $('pred-close').textContent = '--';
    $('pred-band').textContent = '--';
  }

  const m = data.metrics || {};
  const all = m.all || {};
  const recent = m.recent_90 || {};
  const live = m.live || {};
  $('m-acc').textContent = formatPct(all.accuracy);
  $('m-acc-sub').textContent = `n=${all.samples ?? 0} · 始终看涨 ${formatPct(all.always_up_accuracy)}`;
  $('m-recent').textContent = formatPct(recent.accuracy);
  $('m-recent-sub').textContent = `n=${recent.samples ?? 0} · 近 90 天`;
  $('m-live').textContent = live.samples ? formatPct(live.accuracy) : '--';
  $('m-live-sub').textContent = `已评估 ${live.samples ?? 0} · 待验证 ${live.pending ?? 0}`;
  $('m-high').textContent = formatPct(all.high_conf_accuracy);
  $('m-high-sub').textContent = `≥65% · n=${all.high_conf_samples ?? 0} · 覆盖 ${formatPct(all.high_conf_coverage)}`;
  $('m-mape').textContent = formatPct(all.mape_close, 2);
  $('m-strategy').textContent = formatPct(all.strategy_return);
  $('footer-time').textContent = `页面更新 ${formatTime(data.generated_at)}`;
}

function chartTooltip(params) {
  if (!params || !params.length) return '';
  const date = params[0].axisValue;
  const candle = params.find((p) => p.seriesType === 'candlestick');
  const vol = params.find((p) => p.seriesName === '成交量');
  const p = (state.data && state.data.prediction) || {};
  let html = `<div class="tt-date">${escapeHtml(date)}</div>`;
  if (candle && Array.isArray(candle.data) && candle.data.length === 4 && candle.data[0] !== '-') {
    const [open, close, low, high] = candle.data.map(Number);
    const cls = close >= open ? 'green' : 'red';
    html += `<div class="tt-row"><span>开</span><b>${formatUsd(open)}</b></div>`;
    html += `<div class="tt-row"><span>高</span><b>${formatUsd(high)}</b></div>`;
    html += `<div class="tt-row"><span>低</span><b>${formatUsd(low)}</b></div>`;
    html += `<div class="tt-row"><span>收</span><b class="${cls}">${formatUsd(close)}</b></div>`;
  }
  if (vol && vol.data !== null && vol.data !== undefined) {
    html += `<div class="tt-row"><span>成交量</span><b>${Number(vol.data).toLocaleString('en-US', { maximumFractionDigits: 0 })}</b></div>`;
  }
  if (p.target_date && date === p.target_date) {
    html += `<div class="tt-pred">预测 ${formatUsd(p.predicted_close)} · ${formatSignedPct(p.predicted_return)}</div>`;
    html += `<div class="tt-pred-sub">区间 ${formatUsd(p.interval_low)} – ${formatUsd(p.interval_high)}</div>`;
  }
  return html;
}

function renderMainChart() {
  const el = $('chart');
  if (!el || !window.echarts) return;
  const market = state.data && state.data.market;
  const candles = market && market.candles;
  if (!candles || !candles.dates.length) {
    el.innerHTML = empty('暂无行情数据，请先初始化或更新数据');
    return;
  }
  if (!state.charts.main) state.charts.main = echarts.init(el);
  const chart = state.charts.main;

  const dates = candles.dates.slice();
  const values = candles.values.map((row) => row.map((v) => (v === null || v === undefined ? '-' : Number(v))));
  const volumes = candles.volumes.map((v) => (v === null || v === undefined ? null : Number(v)));
  const p = state.data.prediction || {};
  let targetIndex = -1;
  if (p.target_date) {
    targetIndex = dates.indexOf(p.target_date);
    if (targetIndex === -1) {
      dates.push(p.target_date);
      values.push(['-', '-', '-', '-']);
      volumes.push(null);
      targetIndex = dates.length - 1;
    }
  }
  const lastIndex = p.last_candle_date ? Math.max(0, dates.indexOf(p.last_candle_date)) : dates.length - 1;
  const predLine = new Array(dates.length).fill(null);
  const highLine = new Array(dates.length).fill(null);
  const lowLine = new Array(dates.length).fill(null);
  if (p.target_date) {
    predLine[lastIndex] = p.last_close;
    predLine[targetIndex] = p.predicted_close;
    highLine[lastIndex] = p.last_close;
    highLine[targetIndex] = p.interval_high;
    lowLine[lastIndex] = p.last_close;
    lowLine[targetIndex] = p.interval_low;
  }

  const good = [];
  const bad = [];
  const dateSet = new Set(dates);
  for (const marker of state.data.markers || []) {
    if (!dateSet.has(marker.date) || marker.price === null || marker.price === undefined) continue;
    (marker.correct ? good : bad).push([marker.date, marker.price]);
  }

  const total = dates.length;
  const n = state.range === 'all' ? total : Math.min(total, Number(state.range));
  const start = total > 1 ? Math.max(0, (1 - n / total) * 100) : 0;

  const predSeries = {
    name: '预测',
    type: 'line',
    data: predLine,
    connectNulls: false,
    showSymbol: true,
    symbol: 'circle',
    symbolSize: 5,
    lineStyle: { color: '#ff4fd8', width: 2.5, shadowBlur: 12, shadowColor: 'rgba(255,79,216,0.55)' },
    itemStyle: { color: '#ff4fd8' },
    z: 10,
    tooltip: { show: false },
  };
  if (p.target_date) {
    predSeries.markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: 'rgba(255,79,216,0.45)', type: 'dashed' },
      label: { color: '#ff9be8', formatter: '预测日', position: 'insideEndTop', fontSize: 10 },
      data: [{ xAxis: p.target_date }],
    };
    predSeries.markPoint = {
      symbol: 'pin',
      symbolSize: 42,
      itemStyle: { color: '#ff4fd8' },
      label: { color: '#180614', fontSize: 9, fontWeight: 700, formatter: () => '$' + Math.round(p.predicted_close) },
      data: [{ coord: [p.target_date, p.predicted_close], value: p.predicted_close }],
    };
  }

  chart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    textStyle: { fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif' },
    grid: [
      { left: 58, right: 76, top: 34, height: '58%' },
      { left: 58, right: 76, top: '74%', height: '13%' },
    ],
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: '#1b2942' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(12, 20, 35, 0.96)',
      borderColor: 'rgba(120, 150, 200, 0.25)',
      textStyle: { color: '#e6edf8', fontSize: 11 },
      formatter: chartTooltip,
    },
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: true,
        min: 'dataMin',
        max: 'dataMax',
        axisLine: { lineStyle: { color: '#243149' } },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        min: 'dataMin',
        max: 'dataMax',
        axisLine: { lineStyle: { color: '#243149' } },
        axisTick: { show: false },
        axisLabel: { show: true, color: '#667792', fontSize: 10, formatter: (v) => String(v).slice(5) },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        position: 'right',
        splitLine: { lineStyle: { color: 'rgba(120,150,200,0.08)' } },
        axisLabel: {
          color: '#667792',
          fontSize: 10,
          formatter: (v) => (Math.abs(v) >= 1000 ? '$' + (v / 1000).toFixed(0) + 'k' : '$' + Number(v).toFixed(0)),
        },
      },
      {
        gridIndex: 1,
        scale: true,
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        start,
        end: 100,
        bottom: 2,
        height: 16,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255,255,255,0.02)',
        fillerColor: 'rgba(88,199,255,0.12)',
        handleStyle: { color: '#58c7ff' },
        textStyle: { color: '#667792', fontSize: 9 },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        itemStyle: { color: '#2fd39a', color0: '#ff5d78', borderColor: '#2fd39a', borderColor0: '#ff5d78' },
        barMaxWidth: 8,
        z: 2,
      },
      predSeries,
      {
        name: '误差上沿',
        type: 'line',
        data: highLine,
        connectNulls: false,
        symbol: 'none',
        lineStyle: { color: 'rgba(255,79,216,0.42)', width: 1, type: 'dashed' },
        itemStyle: { color: 'rgba(255,79,216,0.42)' },
        z: 8,
        tooltip: { show: false },
      },
      {
        name: '误差下沿',
        type: 'line',
        data: lowLine,
        connectNulls: false,
        symbol: 'none',
        lineStyle: { color: 'rgba(255,79,216,0.42)', width: 1, type: 'dashed' },
        itemStyle: { color: 'rgba(255,79,216,0.42)' },
        z: 8,
        tooltip: { show: false },
      },
      {
        name: '预测正确',
        type: 'scatter',
        data: good,
        symbolSize: 5,
        itemStyle: { color: '#9ff0d2' },
        z: 6,
        tooltip: { show: false },
      },
      {
        name: '预测错误',
        type: 'scatter',
        data: bad,
        symbolSize: 5,
        itemStyle: { color: '#ff9fb0' },
        z: 6,
        tooltip: { show: false },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        barMaxWidth: 6,
        itemStyle: {
          color: (params) => {
            const item = values[params.dataIndex];
            if (!item || item[0] === '-' || item[1] === '-') return 'rgba(120,150,200,0.12)';
            return Number(item[1]) >= Number(item[0]) ? 'rgba(47,211,154,0.32)' : 'rgba(255,93,120,0.3)';
          },
        },
      },
    ],
  }, true);
}

function renderModelTable() {
  const m = (state.data.metrics || {});
  const all = m.all || {};
  const recent = m.recent_90 || {};
  if (!Object.keys(all).length) {
    $('model-table').innerHTML = empty();
    return;
  }
  const rows = [
    ['HGB 多因子', all.samples, formatPct(all.accuracy), formatPct(recent.accuracy), formatPct(all.balanced_accuracy), all.auc == null ? '--' : Number(all.auc).toFixed(3), formatPct(all.strategy_return)],
    ['逻辑回归', all.samples, formatPct(all.logistic_accuracy), formatPct(recent.logistic_accuracy), '--', '--', '--'],
    ['始终看涨', all.samples, formatPct(all.always_up_accuracy), formatPct(recent.always_up_accuracy), '--', '--', '--'],
    ['7 日动量', all.samples, formatPct(all.momentum_accuracy), formatPct(recent.momentum_accuracy), '--', '--', '--'],
  ].map((row, i) => row.map((cell, j) => {
    if (j === 0) return `<b>${cell}</b>`;
    if (typeof cell === 'string' && cell.endsWith('%') && j >= 2 && j <= 4) {
      const n = parseFloat(cell);
      return `<span class="mono ${n >= 50 ? 'green' : 'red'}">${cell}</span>`;
    }
    return `<span class="mono">${cell ?? '--'}</span>`;
  }));
  $('model-table').innerHTML = table(['模型', '样本', '全样本', '近90天', '平衡胜率', 'AUC', '策略收益'], rows);
}

function renderConfidence() {
  const all = (state.data.metrics || {}).all || {};
  const buckets = all.confidence_buckets || [];
  if (!buckets.length) {
    $('confidence-table').innerHTML = empty();
    return;
  }
  const total = all.samples || buckets.reduce((sum, b) => sum + b.count, 0) || 1;
  const rows = buckets.map((b) => [
    `<span class="mono">${b.range}</span>`,
    `<span class="mono">${b.count}</span>`,
    `<span class="mono">${formatPct(b.count / total)}</span>`,
    `<span class="mono ${b.accuracy >= 0.5 ? 'green' : 'red'}">${formatPct(b.accuracy)}</span>`,
  ]);
  $('confidence-table').innerHTML = table(['置信区间', '样本', '占比', '胜率'], rows);
}

function renderConfusion() {
  const all = (state.data.metrics || {}).all || {};
  const c = all.confusion;
  if (!c) {
    $('confusion').innerHTML = empty();
    return;
  }
  $('confusion').innerHTML = `
    <div class="cell head"></div>
    <div class="cell head">预测上涨</div>
    <div class="cell head">预测下跌</div>
    <div class="cell head">实际上涨</div>
    <div class="cell tp"><b>${c.tp}</b><small>正确</small></div>
    <div class="cell fn"><b>${c.fn}</b><small>漏涨</small></div>
    <div class="cell head">实际下跌</div>
    <div class="cell fp"><b>${c.fp}</b><small>假涨</small></div>
    <div class="cell tn"><b>${c.tn}</b><small>正确</small></div>
    <div class="cell" style="grid-column: 1 / -1">
      <small>上涨 precision ${formatPct(all.precision_up)} · recall ${formatPct(all.recall_up)} · F1 ${formatPct(all.f1_up)}</small>
    </div>
  `;
}

function renderLiveTable() {
  const rows = state.data.live_predictions || [];
  if (!rows.length) {
    $('live-table').innerHTML = empty('还没有实盘预测记录，首次更新后会自动写入');
    return;
  }
  const body = rows.map((r) => [
    `<span class="mono">${r.target_date}</span>`,
    dirBadge(r.direction),
    `<span class="mono">${formatPct(r.prob_up)}</span>`,
    `<span class="mono">${formatUsd(r.predicted_close)}</span>`,
    `<span class="mono">${r.actual_close == null ? '--' : formatUsd(r.actual_close)}</span>`,
    `<span class="mono ${r.actual_return == null ? 'dim' : pctClass(r.actual_return)}">${r.actual_return == null ? '--' : formatSignedPct(r.actual_return)}</span>`,
    resultBadge(r.correct),
  ]);
  $('live-table').innerHTML = table(['目标日', '预测', '概率', '预测收盘', '实际收盘', '实际涨跌', '结果'], body);
}

function renderValidation() {
  const rows = state.data.validation || [];
  if (!rows.length) {
    $('validation-table').innerHTML = empty();
    return;
  }
  const body = rows.map((r) => [
    `<span class="mono">${r.date}</span>`,
    dirBadge(r.predicted),
    `<span class="mono">${formatPct(r.prob_up)}</span>`,
    `<span class="mono">${formatUsd(r.predicted_close)}</span>`,
    `<span class="mono">${formatUsd(r.actual_close)}</span>`,
    `<span class="mono ${pctClass(r.predicted_return)}">${formatSignedPct(r.predicted_return)}</span>`,
    `<span class="mono ${pctClass(r.actual_return)}">${formatSignedPct(r.actual_return)}</span>`,
    resultBadge(r.correct),
  ]);
  $('validation-table').innerHTML = table(['日期', '预测', '概率', '预测收盘', '实际收盘', '预测涨跌', '实际涨跌', '结果'], body);
}

function renderFailures() {
  const rows = state.data.failures || [];
  if (!rows.length) {
    $('failure-list').innerHTML = empty('暂无失败记录');
    return;
  }
  $('failure-list').innerHTML = rows.map((item) => {
    const news = (item.news || []).map((n) => `<li>${escapeHtml(n.title)} <span class="dim">(${escapeHtml(n.source)}, ${Number(n.score).toFixed(2)})</span></li>`).join('');
    return `
      <div class="failure-item">
        <div class="failure-top">
          <div><span class="failure-date">${item.date}</span> ${dirBadge(item.predicted)} <span class="dim">→</span> ${dirBadge(item.actual)}</div>
          <div class="mono dim">预测 ${formatSignedPct(item.predicted_return)} · 实际 ${formatSignedPct(item.actual_return)}</div>
        </div>
        <div class="failure-reasons">${(item.reasons || []).map((r) => `<span class="reason">${escapeHtml(r)}</span>`).join('')}</div>
        ${news ? `<ul class="failure-news">${news}</ul>` : ''}
      </div>
    `;
  }).join('');
}

function renderRollingChart() {
  const el = $('rolling-chart');
  if (!el || !window.echarts) return;
  const rows = ((state.data.metrics || {}).rolling_30 || []).filter((r) => r.accuracy !== null && r.accuracy !== undefined);
  if (!rows.length) {
    el.innerHTML = empty();
    return;
  }
  if (!state.charts.rolling) state.charts.rolling = echarts.init(el);
  state.charts.rolling.setOption({
    backgroundColor: 'transparent',
    animation: false,
    grid: { left: 42, right: 18, top: 22, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(12, 20, 35, 0.96)',
      borderColor: 'rgba(120, 150, 200, 0.25)',
      textStyle: { color: '#e6edf8', fontSize: 11 },
      formatter: (params) => {
        const p = params[0];
        return `${p.axisValue}<br/>滚动 30 天胜率：<b>${formatPct(p.data)}</b>`;
      },
    },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.date),
      axisLine: { lineStyle: { color: '#243149' } },
      axisTick: { show: false },
      axisLabel: { color: '#667792', fontSize: 9, formatter: (v) => String(v).slice(5), hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      splitLine: { lineStyle: { color: 'rgba(120,150,200,0.08)' } },
      axisLabel: { color: '#667792', fontSize: 9, formatter: (v) => `${Math.round(v * 100)}%` },
    },
    series: [{
      type: 'line',
      data: rows.map((r) => Number(r.accuracy)),
      smooth: true,
      showSymbol: false,
      lineStyle: { color: '#58c7ff', width: 2 },
      areaStyle: { color: 'rgba(88,199,255,0.08)' },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: '#ffc857', type: 'dashed', width: 1 },
        label: { color: '#ffc857', fontSize: 9, formatter: '50%' },
        data: [{ yAxis: 0.5 }],
      },
    }],
  }, true);
}

function renderImportanceChart() {
  const el = $('importance-chart');
  if (!el || !window.echarts) return;
  const items = (state.data.importance || []).slice().reverse();
  if (!items.length) {
    el.innerHTML = empty();
    return;
  }
  if (!state.charts.importance) state.charts.importance = echarts.init(el);
  const labels = items.map((i) => FEATURE_LABELS[i.feature] || i.feature);
  const values = items.map((i) => Number(i.importance) || 0);
  state.charts.importance.setOption({
    backgroundColor: 'transparent',
    animation: false,
    grid: { left: 150, right: 28, top: 12, bottom: 20 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(12, 20, 35, 0.96)',
      borderColor: 'rgba(120, 150, 200, 0.25)',
      textStyle: { color: '#e6edf8', fontSize: 11 },
      formatter: (params) => {
        const p = params[0];
        return `${items[p.dataIndex].feature}<br/>importance：<b>${Number(p.value).toFixed(4)}</b>`;
      },
    },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(120,150,200,0.08)' } },
      axisLabel: { color: '#667792', fontSize: 9 },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#a6b4cc', fontSize: 10, width: 135, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: values,
      barMaxWidth: 12,
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: (params) => (params.value >= 0 ? 'rgba(88,199,255,0.72)' : 'rgba(255,93,120,0.72)'),
      },
    }],
  }, true);
}

function renderNews() {
  const rows = state.data.news || [];
  if (!rows.length) {
    $('news-list').innerHTML = empty('暂无新闻数据');
    return;
  }
  $('news-list').innerHTML = rows.map((n) => {
    const score = Number(n.score || 0);
    const cls = score > 0.15 ? 'pos' : score < -0.15 ? 'neg' : 'neu';
    const title = n.link
      ? `<a class="news-title" href="${escapeHtml(n.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(n.title)}</a>`
      : `<span class="news-title">${escapeHtml(n.title)}</span>`;
    return `
      <div class="news-item">
        <span class="news-date">${n.date}</span>
        ${title}
        <span class="news-source">${escapeHtml(n.source)} <span class="score ${cls}">${score.toFixed(2)}</span></span>
      </div>
    `;
  }).join('');
}

function renderSources() {
  const rows = state.data.sources || [];
  if (!rows.length) {
    $('sources-table').innerHTML = empty();
    return;
  }
  const body = rows.map((s) => [
    `<b>${escapeHtml(s.name)}</b>`,
    s.ok ? '<span class="badge ok">正常</span>' : '<span class="badge bad">缺失</span>',
    `<span class="mono">${s.rows}</span>`,
    `<span class="mono">${s.last_date || '--'}</span>`,
    `<span class="dim">${s.updated || '--'}</span>`,
  ]);
  $('sources-table').innerHTML = table(['数据源', '状态', '行数', '最新日期', '文件更新时间'], body);
}

function renderModelInfo() {
  const m = state.data.model || {};
  $('model-info').innerHTML = `
    <div class="info-row"><span>模型版本</span><b>${escapeHtml(m.version || '--')}</b></div>
    <div class="info-row"><span>训练时间</span><b>${escapeHtml(formatTime(m.trained_at))}</b></div>
    <div class="info-row"><span>训练样本</span><b>${m.training_rows ?? '--'}</b></div>
    <div class="info-row"><span>最后训练日</span><b>${escapeHtml(m.last_training_date || '--')}</b></div>
    <div class="info-row"><span>预测目标</span><b>${escapeHtml((state.data.prediction || {}).target_date || '--')}（UTC 收盘）</b></div>
    <div class="info-row"><span>模型</span><b>HGB 分类 + HGB 回归</b></div>
  `;
}

function renderReport() {
  const text = state.data.report || '';
  $('report').textContent = text || '暂无日报。运行一次更新后会自动生成。';
}

function activateTab(tab) {
  state.tab = tab;
  qsa('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  qsa('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${tab}`));
  setTimeout(() => {
    if (tab === 'backtest') renderRollingChart();
    if (tab === 'features') renderImportanceChart();
    resizeCharts();
  }, 30);
}

function resizeCharts() {
  Object.values(state.charts).forEach((chart) => {
    try { chart.resize(); } catch (e) { /* ignore */ }
  });
}

function renderAll() {
  renderHeader();
  renderMainChart();
  renderModelTable();
  renderConfidence();
  renderConfusion();
  renderLiveTable();
  renderValidation();
  renderFailures();
  renderNews();
  renderSources();
  renderModelInfo();
  renderReport();
  activateTab(state.tab);
  resizeCharts();
}

async function loadDashboard(silent = false) {
  if (!silent) setStatus('busy', '加载中');
  try {
    const res = await fetch('/api/dashboard', { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '加载失败');
    state.data = data;
    renderAll();
    if (data.ready) {
      setStatus('ok', '已就绪');
      if (!silent) hideBanner();
    } else {
      setStatus('', '尚未初始化');
      showBanner('还没有完整数据。请先运行 python scripts/bootstrap.py，或点击右上角“更新数据并重训”。');
    }
  } catch (err) {
    setStatus('err', '加载失败');
    showBanner(`加载失败：${err.message}`, true);
  }
}

async function runUpdate() {
  if (state.busy) return;
  if (!window.confirm('更新会抓取最新数据、重建特征并重新训练模型，可能需要 1–2 分钟。继续吗？')) return;
  state.busy = true;
  const btn = $('refresh-btn');
  btn.disabled = true;
  btn.textContent = '更新中…';
  setStatus('busy', '抓取与重训中');
  showBanner('正在抓取最新数据并重新训练，请保持页面打开。首次全量新闻回填会更久。');
  try {
    const res = await fetch('/api/update', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || '更新失败');
    await loadDashboard(true);
    showBanner('更新完成，预测与回测已刷新。');
    setTimeout(() => hideBanner(), 5000);
  } catch (err) {
    setStatus('err', '更新失败');
    showBanner(`更新失败：${err.message}`, true);
  } finally {
    state.busy = false;
    btn.disabled = false;
    btn.textContent = '更新数据并重训';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('tabs').addEventListener('click', (event) => {
    const btn = event.target.closest('button[data-tab]');
    if (btn) activateTab(btn.dataset.tab);
  });
  $('range-tabs').addEventListener('click', (event) => {
    const btn = event.target.closest('button[data-range]');
    if (!btn) return;
    state.range = btn.dataset.range === 'all' ? 'all' : Number(btn.dataset.range);
    qsa('#range-tabs button').forEach((b) => b.classList.toggle('active', b === btn));
    renderMainChart();
  });
  $('refresh-btn').addEventListener('click', runUpdate);
  window.addEventListener('resize', resizeCharts);
  loadDashboard();
  setInterval(() => {
    if (!state.busy) loadDashboard(true);
  }, 5 * 60 * 1000);
});
