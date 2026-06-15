#!/usr/bin/env python3
"""
TVKit Web Dashboard - 一站式测试 tvkit 所有接口的 Web 应用。

启动方式:
    cd tvkit && uv run python -m tvkit.web_app
    或者:
    cd tvkit && uv run uvicorn tvkit.web_app:app --host 0.0.0.0 --port 8080 --reload

访问: http://localhost:8080
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tvkit import OHLCV, DataExporter
from tvkit.quickstart import compare_stocks, get_crypto_prices, get_stock_price
from tvkit.symbols import normalize_symbol

# --- 可选依赖 ---
try:
    from tvkit.api.scanner import Market, ScannerService

    _has_scanner = True
except ImportError:
    _has_scanner = False
    Market = None  # type: ignore
    ScannerService = None  # type: ignore

try:
    from tvkit.batch.downloader import batch_download
    from tvkit.batch.models import BatchDownloadRequest

    _has_batch = True
except ImportError:
    _has_batch = False
    batch_download = None  # type: ignore
    BatchDownloadRequest = None  # type: ignore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="TVKit Dashboard", version="0.11.1")

# --- 预定义数据 ---
POPULAR_STOCKS = [
    "NASDAQ:AAPL", "NASDAQ:GOOGL", "NASDAQ:MSFT", "NASDAQ:AMZN",
    "NASDAQ:TSLA", "NASDAQ:NVDA", "NASDAQ:META", "NYSE:JPM",
    "NYSE:JNJ", "NYSE:V", "NYSE:BRK.B", "NASDAQ:NFLX",
]

COMMON_INTERVALS = ["1", "5", "15", "60", "1D", "1W", "1M"]

SCANNER_PRESETS = {
    "all_stocks": "全部股票",
    "large_cap": "大盘股",
    "top_gainers": "涨幅最大",
    "top_losers": "跌幅最大",
    "most_volatile": "最活跃",
    "overbought": "超买",
    "oversold": "超卖",
    "unusual_volume": "异常成交量",
    "small_cap": "小盘股",
}

MARKET_LIST = {
    "america": "🇺🇸 美国",
    "china": "🇨🇳 中国",
    "japan": "🇯🇵 日本",
    "united_kingdom": "🇬🇧 英国",
    "germany": "🇩🇪 德国",
    "france": "🇫🇷 法国",
    "hongkong": "🇭🇰 香港",
    "canada": "🇨🇦 加拿大",
    "australia": "🇦🇺 澳大利亚",
    "india": "🇮🇳 印度",
    "south_korea": "🇰🇷 韩国",
    "taiwan": "🇹🇼 台湾",
    "brazil": "🇧🇷 巴西",
    "global": "🌍 全球",
}

# ============================================================
# HTML 模板
# ============================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TVKit Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon@3.4.0/build/global/luxon.min.js"></script>
<style>
  :root { --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0;
          --muted: #94a3b8; --accent: #38bdf8; --green: #34d399; --red: #f87171;
          --yellow: #fbbf24; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh; }
  header { background: var(--card); border-bottom: 1px solid var(--border);
           padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.25rem; font-weight: 700; }
  header h1 span { color: var(--accent); }
  .tabs { display: flex; gap: 2px; background: var(--card); padding: 4px;
          border-bottom: 1px solid var(--border); overflow-x: auto; }
  .tab { padding: 10px 18px; border: none; background: transparent; color: var(--muted);
          cursor: pointer; font-size: 0.875rem; white-space: nowrap; border-radius: 6px 6px 0 0;
          transition: all 0.15s; font-weight: 500; }
  .tab:hover { color: var(--text); background: rgba(255,255,255,0.05); }
  .tab.active { color: var(--accent); background: var(--bg); }
  main { max-width: 1400px; margin: 0 auto; padding: 24px; }
  .panel { display: none; }
  .panel.active { display: block; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 20px; margin-bottom: 20px; }
  .card h3 { font-size: 1rem; margin-bottom: 16px; color: var(--accent); }
  .form-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 16px; }
  .form-group { display: flex; flex-direction: column; gap: 4px; }
  .form-group label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
                      letter-spacing: 0.05em; }
  input, select, textarea { background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 0.875rem;
    outline: none; transition: border-color 0.15s; }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); }
  textarea { font-family: monospace; resize: vertical; }
  button { background: var(--accent); color: #0f172a; border: none; padding: 8px 20px;
    border-radius: 6px; font-size: 0.875rem; font-weight: 600; cursor: pointer;
    transition: opacity 0.15s; }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  button.secondary { background: var(--border); color: var(--text); }
  .result-box { background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px; max-height: 500px; overflow-y: auto; font-family: 'SF Mono', monospace;
    font-size: 0.8rem; white-space: pre-wrap; }
  .result-box table { width: 100%; border-collapse: collapse; font-family: -apple-system, sans-serif; }
  .result-box th { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
    color: var(--muted); font-size: 0.75rem; text-transform: uppercase; position: sticky;
    top: 0; background: var(--bg); }
  .result-box td { padding: 6px 10px; border-bottom: 1px solid rgba(51,65,85,0.5); font-size: 0.85rem; }
  .positive { color: var(--green); }
  .negative { color: var(--red); }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border);
    border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status { padding: 8px 16px; border-radius: 6px; font-size: 0.875rem; margin-bottom: 12px; }
  .status.info { background: rgba(56,189,248,0.15); color: var(--accent); }
  .status.error { background: rgba(248,113,113,0.15); color: var(--red); }
  .status.success { background: rgba(52,211,153,0.15); color: var(--green); }
  .chart-container { width: 100%; height: 400px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem;
         font-weight: 600; }
  .tag-up { background: rgba(52,211,153,0.2); color: var(--green); }
  .tag-down { background: rgba(248,113,113,0.2); color: var(--red); }
  @media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } main { padding: 12px; } }
  .live-bar { padding: 8px 12px; margin: 4px 0; background: var(--bg); border-radius: 4px;
    border-left: 3px solid var(--accent); font-size: 0.8rem; }
</style>
</head>
<body>

<header>
  <h1>📈 <span>TVKit</span> Dashboard</h1>
  <div style="font-size:0.75rem;color:var(--muted)">v0.11.1 · TradingView API</div>
</header>

<nav class="tabs">
  <button class="tab active" onclick="switchTab('price')">📈 股票价格</button>
  <button class="tab" onclick="switchTab('history')">📊 历史K线</button>
  <button class="tab" onclick="switchTab('compare')">⚖️ 多股对比</button>
  <button class="tab" onclick="switchTab('crypto')">💰 加密货币</button>
  <button class="tab" onclick="switchTab('scanner')">🔍 市场扫描</button>
  <button class="tab" onclick="switchTab('batch')">📋 批量下载</button>
  <button class="tab" onclick="switchTab('stream')">🔄 实时行情</button>
  <button class="tab" onclick="switchTab('export')">📦 导出</button>
</nav>

<main>

<!-- ========== 股票价格 ========== -->
<section id="panel-price" class="panel active">
  <div class="card">
    <h3>📈 单股实时价格查询</h3>
    <div class="form-row">
      <div class="form-group">
        <label>股票代码</label>
        <input id="price-symbol" value="NASDAQ:AAPL" placeholder="NASDAQ:AAPL" style="width:200px">
      </div>
      <button onclick="fetchPrice()">查询价格</button>
    </div>
    <div class="form-row" style="margin-top:8px">
      <span style="font-size:0.75rem;color:var(--muted)">快捷选择:</span>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NASDAQ:AAPL')">AAPL</button>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NASDAQ:GOOGL')">GOOGL</button>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NASDAQ:MSFT')">MSFT</button>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NASDAQ:TSLA')">TSLA</button>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NASDAQ:NVDA')">NVDA</button>
      <button class="secondary" style="padding:4px 10px;font-size:0.7rem" onclick="setSymbol('NYSE:BRK.B')">BRK.B</button>
    </div>
    <div id="price-status"></div>
    <div id="price-result" class="result-box" style="display:none"></div>
  </div>
</section>

<!-- ========== 历史K线 ========== -->
<section id="panel-history" class="panel">
  <div class="card">
    <h3>📊 历史K线数据</h3>
    <div class="form-row">
      <div class="form-group"><label>股票代码</label>
        <input id="hist-symbol" value="NASDAQ:AAPL" style="width:180px">
      </div>
      <div class="form-group"><label>周期</label>
        <select id="hist-interval">
          <option value="1">1分钟</option><option value="5">5分钟</option>
          <option value="15">15分钟</option><option value="60">1小时</option>
          <option value="1D" selected>日线</option><option value="1W">周线</option>
          <option value="1M">月线</option>
        </select>
      </div>
      <div class="form-group">
        <label>查询模式</label>
        <select id="hist-mode" onchange="toggleHistMode()">
          <option value="count" selected>最近N条</option>
          <option value="range">日期范围</option>
        </select>
      </div>
      <div class="form-group" id="hist-count-group"><label>K线数量</label>
        <input id="hist-count" type="number" value="30" min="1" max="5000" style="width:100px">
      </div>
      <div class="form-group" id="hist-start-group" style="display:none"><label>开始日期</label>
        <input id="hist-start" type="date">
      </div>
      <div class="form-group" id="hist-end-group" style="display:none"><label>结束日期</label>
        <input id="hist-end" type="date">
      </div>
      <button onclick="fetchHistory()">获取数据</button>
    </div>
    <div id="hist-status"></div>
    <div class="grid-2">
      <div class="chart-container"><canvas id="hist-chart"></canvas></div>
      <div id="hist-table" class="result-box" style="max-height:400px;display:none"></div>
    </div>
  </div>
</section>

<!-- ========== 多股对比 ========== -->
<section id="panel-compare" class="panel">
  <div class="card">
    <h3>⚖️ 多股收益对比</h3>
    <div class="form-row">
      <div class="form-group"><label>股票列表（逗号或空格分隔）</label>
        <input id="compare-symbols" value="NASDAQ:AAPL, NASDAQ:GOOGL, NASDAQ:MSFT, NASDAQ:TSLA, NASDAQ:NVDA" style="width:500px">
      </div>
      <div class="form-group"><label>天数</label>
        <input id="compare-days" type="number" value="30" min="1" max="365" style="width:80px">
      </div>
      <button onclick="fetchCompare()">开始对比</button>
    </div>
    <div id="compare-status"></div>
    <div id="compare-result" class="result-box" style="display:none"></div>
  </div>
</section>

<!-- ========== 加密货币 ========== -->
<section id="panel-crypto" class="panel">
  <div class="card">
    <h3>💰 主流加密货币价格</h3>
    <div class="form-row">
      <div class="form-group"><label>数量</label>
        <input id="crypto-limit" type="number" value="8" min="1" max="8" style="width:80px">
      </div>
      <button onclick="fetchCrypto()">获取价格</button>
    </div>
    <div id="crypto-status"></div>
    <div id="crypto-result" class="result-box" style="display:none"></div>
  </div>
</section>

<!-- ========== 市场扫描 ========== -->
<section id="panel-scanner" class="panel">
  <div class="card">
    <h3>🔍 市场扫描器</h3>
    <div class="form-row">
      <div class="form-group"><label>市场</label>
        <select id="scan-market">$MARKET_OPTIONS</select>
      </div>
      <div class="form-group"><label>预设扫描</label>
        <select id="scan-preset">
          <option value="all_stocks">全部股票</option>
          <option value="top_gainers">涨幅最大</option>
          <option value="top_losers">跌幅最大</option>
          <option value="most_volatile">最活跃</option>
          <option value="unusual_volume">异常成交量</option>
        </select>
      </div>
      <div class="form-group"><label>返回条数</label>
        <input id="scan-limit" type="number" value="20" min="1" max="500" style="width:80px">
      </div>
      <button onclick="fetchScanner()">开始扫描</button>
    </div>
    <div id="scanner-status"></div>
    <div id="scanner-result" class="result-box" style="display:none"></div>
  </div>
</section>

<!-- ========== 批量下载 ========== -->
<section id="panel-batch" class="panel">
  <div class="card">
    <h3>📋 批量历史数据下载</h3>
    <div class="form-row">
      <div class="form-group"><label>股票列表（每行一个或逗号分隔）</label>
        <textarea id="batch-symbols" rows="4" style="width:400px">NASDAQ:AAPL
NASDAQ:GOOGL
NASDAQ:MSFT
NASDAQ:TSLA</textarea>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <div class="form-group"><label>周期</label>
          <select id="batch-interval">
            <option value="1D" selected>日线</option><option value="1W">周线</option>
            <option value="60">1小时</option><option value="15">15分钟</option>
          </select>
        </div>
        <div class="form-group"><label>天数</label>
          <input id="batch-days" type="number" value="90" min="1" max="3650" style="width:100px">
        </div>
        <button onclick="fetchBatch()">开始下载</button>
      </div>
    </div>
    <div id="batch-status"></div>
    <div id="batch-result" class="result-box" style="display:none"></div>
  </div>
</section>

<!-- ========== 实时行情 ========== -->
<section id="panel-stream" class="panel">
  <div class="card">
    <h3>🔄 实时行情推送 (WebSocket Stream)</h3>
    <div class="form-row">
      <div class="form-group"><label>股票代码</label>
        <input id="stream-symbol" value="NASDAQ:AAPL" style="width:200px">
      </div>
      <div class="form-group"><label>周期</label>
        <select id="stream-interval">
          <option value="1" selected>1分钟</option><option value="5">5分钟</option>
          <option value="15">15分钟</option>
        </select>
      </div>
      <button id="stream-start-btn" onclick="startStream()">▶ 开始推送</button>
      <button id="stream-stop-btn" class="secondary" onclick="stopStream()" style="display:none">⏹ 停止</button>
    </div>
    <div id="stream-status"></div>
    <div id="stream-result" class="result-box" style="max-height:300px">
      <div style="color:var(--muted)">点击 "开始推送" 接收实时报价...</div>
    </div>
  </div>
</section>

<!-- ========== 导出 ========== -->
<section id="panel-export" class="panel">
  <div class="card">
    <h3>📦 数据导出</h3>
    <div class="form-row">
      <div class="form-group"><label>股票代码</label>
        <input id="export-symbol" value="NASDAQ:AAPL" style="width:200px">
      </div>
      <div class="form-group"><label>周期</label>
        <select id="export-interval">
          <option value="1D" selected>日线</option><option value="1W">周线</option>
          <option value="60">1小时</option>
        </select>
      </div>
      <div class="form-group"><label>K线数量</label>
        <input id="export-count" type="number" value="100" min="1" max="5000" style="width:100px">
      </div>
      <div class="form-group"><label>导出格式</label>
        <select id="export-format">
          <option value="csv">CSV</option><option value="json">JSON</option>
        </select>
      </div>
      <button onclick="fetchExport()">导出数据</button>
    </div>
    <div id="export-status"></div>
    <div id="export-result" class="result-box" style="display:none"></div>
  </div>
</section>

</main>

<script>
// ===== 全局工具函数 =====
let histChart = null;
let streamController = null;

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`[onclick="switchTab('${name}')"]`).classList.add('active');
  document.getElementById(`panel-${name}`).classList.add('active');
  if (name === 'history') setTimeout(renderChart, 100);
}

function setSymbol(sym) { document.getElementById('price-symbol').value = sym; }

function formatNum(n, decimals=2) {
  if (n == null) return '--';
  return Number(n).toLocaleString('en-US', {minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}

function formatLargeNum(n) {
  if (n == null) return '--';
  if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n/1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
  return n.toFixed(0);
}

function showStatus(id, msg, cls='info') {
  const el = document.getElementById(id);
  el.innerHTML = `<div class="status ${cls}">${msg}</div>`;
}

function showResult(id, html) {
  const el = document.getElementById(id);
  el.innerHTML = html;
  el.style.display = 'block';
}

async function apiGet(url) {
  const resp = await fetch(url);
  if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || resp.statusText); }
  return resp.json();
}

// ===== 1. 股票价格 =====
async function fetchPrice() {
  const sym = document.getElementById('price-symbol').value.trim();
  if (!sym) return;
  showStatus('price-status', '<span class="spinner"></span> 查询中...', 'info');
  try {
    const data = await apiGet(`/api/price?symbol=${encodeURIComponent(sym)}`);
    showStatus('price-status', '✓ 查询成功', 'success');
    showResult('price-result',
      `<div style="display:flex;gap:30px;flex-wrap:wrap">
        <div><span style="color:var(--muted)">股票</span> <strong>${data.symbol}</strong></div>
        <div><span style="color:var(--muted)">价格</span> <strong style="font-size:1.4rem">$${formatNum(data.price)}</strong></div>
        <div><span style="color:var(--muted)">开盘</span> $${formatNum(data.open)}</div>
        <div><span style="color:var(--muted)">最高</span> $${formatNum(data.high)}</div>
        <div><span style="color:var(--muted)">最低</span> $${formatNum(data.low)}</div>
        <div><span style="color:var(--muted)">成交量</span> ${formatLargeNum(data.volume)}</div>
        <div><span style="color:var(--muted)">日期</span> ${data.date}</div>
      </div>`);
  } catch(e) {
    showStatus('price-status', '✗ ' + e.message, 'error');
  }
}

// ===== 2. 历史K线 =====
function toggleHistMode() {
  const mode = document.getElementById('hist-mode').value;
  document.getElementById('hist-count-group').style.display = mode==='count'?'':'none';
  document.getElementById('hist-start-group').style.display = mode==='range'?'':'none';
  document.getElementById('hist-end-group').style.display = mode==='range'?'':'none';
}

async function fetchHistory() {
  const sym = document.getElementById('hist-symbol').value.trim();
  const interval = document.getElementById('hist-interval').value;
  const mode = document.getElementById('hist-mode').value;
  showStatus('hist-status', '<span class="spinner"></span> 获取数据中...', 'info');
  try {
    let url = `/api/history?symbol=${encodeURIComponent(sym)}&interval=${interval}`;
    if (mode === 'count') {
      url += `&bars_count=${document.getElementById('hist-count').value}`;
    } else {
      url += `&start=${document.getElementById('hist-start').value}&end=${document.getElementById('hist-end').value}`;
    }
    const data = await apiGet(url);
    showStatus('hist-status', `✓ 获取成功，共 ${data.count} 条K线`, 'success');
    window._histData = data.bars;
    renderChart();
    renderHistTable(data.bars);
  } catch(e) {
    showStatus('hist-status', '✗ ' + e.message, 'error');
  }
}

function renderChart() {
  const bars = window._histData || [];
  if (!bars.length) return;
  const ctx = document.getElementById('hist-chart').getContext('2d');
  if (histChart) histChart.destroy();

  // Use candlestick chart if available, otherwise line
  if (typeof Chart !== 'undefined' && Chart.controllers && Chart.controllers.candlestick) {
    const ohlcData = bars.map(b => ({
      x: b.timestamp * 1000,
      o: b.open, h: b.high, l: b.low, c: b.close
    }));
    histChart = new Chart(ctx, {
      type: 'candlestick',
      data: { datasets: [{ label: 'OHLCV', data: ohlcData,
        color: { up: '#34d399', down: '#f87171', unchanged: '#94a3b8' } }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                  y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } } } }
    });
  } else {
    // Fallback to line chart
    const labels = bars.map(b => new Date(b.timestamp*1000).toLocaleDateString('zh-CN'));
    histChart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets: [
        { label: 'Close', data: bars.map(b=>b.close), borderColor: '#38bdf8', tension: 0.1 },
        { label: 'Volume', data: bars.map(b=>b.volume), borderColor: '#94a3b8',
          yAxisID: 'y1', tension: 0.1, borderWidth: 0.5 }
      ]},
      options: { responsive: true, maintainAspectRatio: false,
        scales: { x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                  y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                  y1: { position: 'right', ticks: { color: '#94a3b8' }, grid: { display: false } } } }
    });
  }
}

function renderHistTable(bars) {
  if (!bars.length) return;
  const rows = bars.slice(-20).reverse().map(b => {
    const dt = new Date(b.timestamp*1000);
    const cls = b.close >= b.open ? 'positive' : 'negative';
    return `<tr><td>${dt.toLocaleDateString('zh-CN')} ${dt.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</td>
      <td class="${cls}">$${formatNum(b.open)}</td><td class="${cls}">$${formatNum(b.high)}</td>
      <td class="${cls}">$${formatNum(b.low)}</td><td class="${cls}">$${formatNum(b.close)}</td>
      <td>${formatLargeNum(b.volume)}</td></tr>`;
  }).join('');
  showResult('hist-table', `<table><thead><tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th></tr></thead><tbody>${rows}</tbody></table>`);
}

// ===== 3. 多股对比 =====
async function fetchCompare() {
  const syms = document.getElementById('compare-symbols').value.split(/[,，\s]+/).filter(Boolean);
  const days = document.getElementById('compare-days').value;
  if (!syms.length) return;
  showStatus('compare-status', '<span class="spinner"></span> 对比中...', 'info');
  try {
    const data = await apiGet(`/api/compare?symbols=${syms.join(',')}&days=${days}`);
    showStatus('compare-status', `✓ 对比完成`, 'success');
    const rows = syms.map(s => {
      const m = data[s];
      if (!m || m.error) return `<tr><td>${s}</td><td colspan="3">❌ ${(m||{}).error||'无数据'}</td></tr>`;
      const cls = m.change_percent >= 0 ? 'positive' : 'negative';
      const emoji = m.change_percent >= 0 ? '📈' : '📉';
      return `<tr><td><strong>${s}</strong></td>
        <td>$${formatNum(m.current_price)}</td>
        <td class="${cls}">${m.change_percent>=0?'+':''}${formatNum(m.change_percent)}% ${emoji}</td>
        <td>$${formatNum(m.high)} / $${formatNum(m.low)}</td>
        <td>${formatLargeNum(m.average_volume)}</td></tr>`;
    }).join('');
    showResult('compare-result', `<table><thead><tr><th>股票</th><th>当前价</th><th>涨跌幅</th><th>区间高低</th><th>均量</th></tr></thead><tbody>${rows}</tbody></table>`);
  } catch(e) {
    showStatus('compare-status', '✗ ' + e.message, 'error');
  }
}

// ===== 4. 加密货币 =====
async function fetchCrypto() {
  const limit = document.getElementById('crypto-limit').value;
  showStatus('crypto-status', '<span class="spinner"></span> 获取中...', 'info');
  try {
    const data = await apiGet(`/api/crypto?limit=${limit}`);
    showStatus('crypto-status', '✓ 获取成功', 'success');
    const rows = Object.entries(data).map(([k,v]) =>
      `<tr><td><strong>${k}</strong></td><td style="font-size:1.1rem">$${formatNum(v, 2)}</td></tr>`
    ).join('');
    showResult('crypto-result', `<table><thead><tr><th>币种</th><th>价格 (USD)</th></tr></thead><tbody>${rows}</tbody></table>`);
  } catch(e) {
    showStatus('crypto-status', '✗ ' + e.message, 'error');
  }
}

// ===== 5. 市场扫描 =====
async function fetchScanner() {
  const market = document.getElementById('scan-market').value;
  const preset = document.getElementById('scan-preset').value;
  const limit = document.getElementById('scan-limit').value;
  showStatus('scanner-status', '<span class="spinner"></span> 扫描中...', 'info');
  try {
    const data = await apiGet(`/api/scanner?market=${market}&preset=${preset}&limit=${limit}`);
    showStatus('scanner-status', `✓ 扫描完成，返回 ${data.length} 条结果`, 'success');
    if (!data.length) { showResult('scanner-result', '<div style="color:var(--muted)">无结果</div>'); return; }
    const keys = Object.keys(data[0]).filter(k => !['d','description','typespecs','logoid','update_mode','type'].includes(k));
    const header = keys.map(k => `<th>${k}</th>`).join('');
    const rows = data.map(row => {
      return '<tr>' + keys.map(k => {
        let v = row[k];
        if (k === 'change' || (k.includes('Perf')||k.includes('perf'))) {
          if (v == null) return '<td>--</td>';
          const cls = Number(v) >= 0 ? 'positive' : 'negative';
          return `<td class="${cls}">${Number(v)>=0?'+':''}${typeof v==='number'?formatNum(v,2):v}${k.includes('Perf')||k.includes('perf')?'%':''}</td>`;
        }
        if (k === 'name' || k === 'symbol') return `<td><strong>${v||'--'}</strong></td>`;
        if (k === 'market_cap_basic' || k === 'volume') return `<td>${formatLargeNum(v)}</td>`;
        if (typeof v === 'number' && (k.includes('price')||k==='close')) return `<td>$${formatNum(v)}</td>`;
        return `<td>${v!=null?v:'--'}</td>`;
      }).join('') + '</tr>';
    }).join('');
    showResult('scanner-result', `<table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`);
  } catch(e) {
    showStatus('scanner-status', '✗ ' + e.message, 'error');
  }
}

// ===== 6. 批量下载 =====
async function fetchBatch() {
  const syms = document.getElementById('batch-symbols').value.split(/[\n,，\s]+/).filter(Boolean);
  if (!syms.length) return;
  const interval = document.getElementById('batch-interval').value;
  const days = document.getElementById('batch-days').value;
  showStatus('batch-status', '<span class="spinner"></span> 下载中...（可能需要几分钟）', 'info');
  try {
    const data = await apiGet(`/api/batch?symbols=${syms.join(',')}&interval=${interval}&days=${days}`);
    showStatus('batch-status', `✓ 下载完成`, 'success');
    const rows = Object.entries(data).map(([s, info]) => {
      if (info.error) return `<tr><td>${s}</td><td colspan="2">❌ ${info.error}</td></tr>`;
      return `<tr><td>${s}</td><td>✓ ${info.bar_count} bars</td><td>${info.date_range||''}</td></tr>`;
    }).join('');
    showResult('batch-result', `<table><thead><tr><th>股票</th><th>状态</th><th>日期范围</th></tr></thead><tbody>${rows}</tbody></table>`);
  } catch(e) {
    showStatus('batch-status', '✗ ' + e.message, 'error');
  }
}

// ===== 7. 实时行情 =====
function startStream() {
  const sym = document.getElementById('stream-symbol').value.trim();
  const interval = document.getElementById('stream-interval').value;
  if (!sym) return;
  document.getElementById('stream-start-btn').style.display = 'none';
  document.getElementById('stream-stop-btn').style.display = '';
  const resultEl = document.getElementById('stream-result');
  resultEl.innerHTML = '<div style="color:var(--accent)">⏳ 连接中...</div>';
  showStatus('stream-status', '🟢 实时推送中...', 'info');

  const evtSource = new EventSource(`/api/stream?symbol=${encodeURIComponent(sym)}&interval=${interval}`);
  window._streamSource = evtSource;
  let count = 0;

  evtSource.onmessage = (e) => {
    count++;
    try {
      const bar = JSON.parse(e.data);
      if (bar.type === 'error') {
        resultEl.innerHTML = `<div style="color:var(--red)">❌ ${bar.message}</div>`;
        return;
      }
      if (bar.type === 'status') {
        const firstLine = resultEl.querySelector('div:first-child');
        if (firstLine) firstLine.textContent = bar.message;
        return;
      }
      const cls = bar.close >= bar.open ? 'positive' : 'negative';
      const dt = new Date(bar.timestamp * 1000);
      const barHtml = `<div class="live-bar">
        <span style="color:var(--muted)">${dt.toLocaleTimeString('zh-CN')}</span>
        O:<span class="${cls}">${formatNum(bar.open)}</span>
        H:<span class="${cls}">${formatNum(bar.high)}</span>
        L:<span class="${cls}">${formatNum(bar.low)}</span>
        C:<span class="${cls}">${formatNum(bar.close)}</span>
        V:${formatLargeNum(bar.volume)}
      </div>`;
      resultEl.insertAdjacentHTML('afterbegin', barHtml);
    } catch(err) {}
  };

  evtSource.onerror = () => {
    showStatus('stream-status', '🔴 连接断开，正在重连...', 'error');
    if (count === 0) resultEl.innerHTML = '<div style="color:var(--red)">❌ 无法连接实时行情服务</div>';
  };
}

function stopStream() {
  if (window._streamSource) { window._streamSource.close(); window._streamSource = null; }
  document.getElementById('stream-start-btn').style.display = '';
  document.getElementById('stream-stop-btn').style.display = 'none';
  showStatus('stream-status', '⏹ 已停止', 'info');
}

// ===== 8. 导出 =====
async function fetchExport() {
  const sym = document.getElementById('export-symbol').value.trim();
  const interval = document.getElementById('export-interval').value;
  const count = document.getElementById('export-count').value;
  const fmt = document.getElementById('export-format').value;
  if (!sym) return;
  showStatus('export-status', '<span class="spinner"></span> 导出中...', 'info');
  try {
    const data = await apiGet(`/api/export?symbol=${encodeURIComponent(sym)}&interval=${interval}&bars_count=${count}&format=${fmt}`);
    showStatus('export-status', `✓ 导出成功，共 ${data.count} 条`, 'success');
    if (fmt === 'csv') {
      showResult('export-result', `<div style="color:var(--green);margin-bottom:8px">✓ CSV 数据 (前1000字符预览):</div><div style="white-space:pre-wrap;font-family:monospace;font-size:0.75rem">${escapeHtml(data.data.substring(0, 2000))}</div>`);
    } else {
      showResult('export-result', `<div style="color:var(--green);margin-bottom:8px">✓ JSON 数据:</div><div style="white-space:pre-wrap;font-family:monospace;font-size:0.75rem">${escapeHtml(JSON.stringify(JSON.parse(data.data).slice(0,5), null, 2))}</div>
        <div style="color:var(--muted);margin-top:8px">... 共 ${data.count} 条记录</div>`);
    }
  } catch(e) {
    showStatus('export-status', '✗ ' + e.message, 'error');
  }
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// 页面加载时初始化日期
document.addEventListener('DOMContentLoaded', () => {
  const today = new Date();
  const thirtyDaysAgo = new Date(today - 30*86400000);
  document.getElementById('hist-start').value = thirtyDaysAgo.toISOString().slice(0,10);
  document.getElementById('hist-end').value = today.toISOString().slice(0,10);
});
</script>
</body>
</html>
"""


# ============================================================
# API 路由
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """返回主页面"""
    market_opts = "".join(
        f'<option value="{k}">{v}</option>' for k, v in MARKET_LIST.items()
    )
    return HTMLResponse(INDEX_HTML.replace("$MARKET_OPTIONS", market_opts))


# --- 1. 股票价格 ---
@app.get("/api/price")
async def api_price(symbol: str = Query(..., description="股票代码，如 NASDAQ:AAPL")):
    """获取单股实时价格"""
    result = await get_stock_price(symbol)
    return result


# --- 2. 历史K线 ---
@app.get("/api/history")
async def api_history(
    symbol: str = Query(..., description="股票代码"),
    interval: str = Query("1D", description="K线周期"),
    bars_count: int | None = Query(None, description="K线数量"),
    start: str | None = Query(None, description="开始日期 YYYY-MM-DD"),
    end: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
):
    """获取历史K线数据"""
    async with OHLCV() as client:
        if start and end:
            bars = await client.get_historical_ohlcv(
                symbol, interval, start=start, end=end
            )
        elif bars_count:
            bars = await client.get_historical_ohlcv(
                symbol, interval, bars_count=bars_count
            )
        else:
            bars = await client.get_historical_ohlcv(
                symbol, interval, bars_count=30
            )

    return {
        "symbol": symbol,
        "interval": interval,
        "count": len(bars),
        "bars": [
            {
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ],
    }


# --- 3. 多股对比 ---
@app.get("/api/compare")
async def api_compare(
    symbols: str = Query(..., description="逗号分隔的股票列表"),
    days: int = Query(30, description="对比天数"),
):
    """多股收益对比"""
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    result = await compare_stocks(sym_list, days)
    return result


# --- 4. 加密货币 ---
@app.get("/api/crypto")
async def api_crypto(limit: int = Query(8, ge=1, le=8)):
    """获取加密货币价格"""
    return await get_crypto_prices(limit)


# --- 5. 市场扫描 ---
@app.get("/api/scanner")
async def api_scanner(
    market: str = Query("america", description="市场代码"),
    preset: str = Query("all_stocks", description="扫描预设"),
    limit: int = Query(20, ge=1, le=500),
):
    """市场扫描"""
    if not _has_scanner:
        return {"error": "Scanner 模块未安装"}

    try:
        market_enum = Market(market)
    except ValueError:
        return {"error": f"不支持的市场: {market}，可用: {list(MARKET_LIST.keys())}"}

    async with ScannerService() as scanner:
        result = await scanner.scan_market(
            market=market_enum,
            preset=preset,
            range=(0, limit),
        )
        return [r.model_dump() for r in result.stocks] if result else []


# --- 6. 批量下载 ---
@app.get("/api/batch")
async def api_batch(
    symbols: str = Query(..., description="逗号分隔的股票列表"),
    interval: str = Query("1D"),
    days: int = Query(90, ge=1, le=3650),
):
    """批量下载历史数据"""
    if not _has_batch:
        # Fallback: manual batch
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        results = {}
        end_dt = datetime.now(UTC)
        start_dt = end_dt - timedelta(days=days)
        async with OHLCV() as client:
            for sym in sym_list:
                try:
                    bars = await client.get_historical_ohlcv(
                        sym, interval, start=start_dt, end=end_dt
                    )
                    results[sym] = {
                        "bar_count": len(bars),
                        "date_range": f"{bars[0].timestamp} - {bars[-1].timestamp}" if bars else "empty",
                    }
                except Exception as e:
                    results[sym] = {"error": str(e)}
        return results

    # Use native batch_download
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=days)

    request = BatchDownloadRequest(
        symbols=sym_list,
        interval=interval,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
    )
    summary = await batch_download(request)
    return {
        r.symbol: {
            "bar_count": r.bar_count if r.success else None,
            "error": r.error.message if r.error else None,
            "date_range": f"{r.first_bar_timestamp} - {r.last_bar_timestamp}" if r.success and r.first_bar_timestamp else None,
        }
        for r in summary.results
    }


# --- 7. 实时行情流 ---
@app.get("/api/stream")
async def api_stream(
    symbol: str = Query(..., description="股票代码"),
    interval: str = Query("1", description="周期"),
):
    """实时行情 SSE 推送"""
    async def generate():
        try:
            async with OHLCV() as client:
                yield f"data: {json.dumps({'type': 'status', 'message': '已连接到 TradingView...'})}\n\n"
                async for bar in client.get_ohlcv(symbol, interval=interval, bars_count=10):
                    yield f"data: {json.dumps({'type': 'bar', 'timestamp': bar.timestamp, 'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close, 'volume': bar.volume})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- 8. 数据导出 ---
@app.get("/api/export")
async def api_export(
    symbol: str = Query(..., description="股票代码"),
    interval: str = Query("1D"),
    bars_count: int = Query(100, ge=1, le=5000),
    format: str = Query("csv", description="导出格式: csv 或 json"),
):
    """导出数据为 CSV 或 JSON"""
    async with OHLCV() as client:
        bars = await client.get_historical_ohlcv(
            symbol, interval, bars_count=bars_count
        )

    exporter = DataExporter()
    if format == "csv":
        data = await exporter.to_csv(bars, f"/tmp/tvkit_export_{symbol.replace(':', '_')}.csv")
        # Read back the CSV content
        import os
        if os.path.exists(data):
            with open(data) as f:
                content = f.read()
        else:
            content = str(data)
    else:
        json_data = await exporter.to_json(bars, f"/tmp/tvkit_export_{symbol.replace(':', '_')}.json")
        import os
        if os.path.exists(json_data):
            with open(json_data) as f:
                content = f.read()
        else:
            content = str(json_data)

    return {"count": len(bars), "format": format, "data": content}


# ============================================================
# 启动入口
# ============================================================
if __name__ == "__main__":
    import uvicorn

    print("=" * 54)
    print("  📈 TVKit Dashboard")
    print("  访问: http://localhost:8080")
    print("=" * 54)
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
