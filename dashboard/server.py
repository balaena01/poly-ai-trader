"""
Dashboard Server
- FastAPI + WebSocket
- リアルタイム取引可視化
- Cyberpunk × Bloomberg Terminal aesthetic
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Set
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("Warning: fastapi/uvicorn not installed. Run: pip install fastapi uvicorn")


class ConnectionManager:
    """WebSocket接続管理"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """全クライアントにブロードキャスト"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass


class DashboardServer:
    """ダッシュボードサーバー"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        if not FASTAPI_AVAILABLE:
            raise RuntimeError("fastapi/uvicorn not installed")
        
        self.host = host
        self.port = port
        self.app = FastAPI(title="Poly AI Trader Dashboard")
        self.manager = ConnectionManager()
        
        # 状態
        self.state = {
            "status": "idle",
            "balance": 0,
            "pnl": 0,
            "trades_today": 0,
            "active_triggers": [],
            "recent_signals": [],
            "recent_trades": [],
            "open_positions": [],
            "markets": [],
            "prices": {"BTC": 0, "ETH": 0},
            "price_history": [],  # For charts
            "edge_history": [],   # Edge over time
            "balance_history": [],  # Balance over time
        }
        
        self._setup_routes()
    
    def _setup_routes(self):
        """ルート設定"""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            return self._get_dashboard_html()
        
        @self.app.get("/api/state")
        async def get_state():
            return self.state
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self.manager.connect(websocket)
            try:
                # 初期状態送信
                await websocket.send_json({
                    "type": "init",
                    "data": self.state,
                })
                
                while True:
                    # クライアントからのメッセージ待機
                    data = await websocket.receive_text()
                    # エコーバック (ping/pong)
                    if data == "ping":
                        await websocket.send_text("pong")
            except WebSocketDisconnect:
                self.manager.disconnect(websocket)
    
    async def update_state(self, key: str, value):
        """状態更新 + ブロードキャスト"""
        self.state[key] = value
        
        # Balance/PnL変更時に履歴記録
        if key in ("balance", "pnl"):
            self.state["balance_history"].append({
                "time": datetime.now().isoformat(),
                "balance": self.state["balance"],
                "pnl": self.state["pnl"],
            })
            # 最新100件のみ保持
            self.state["balance_history"] = self.state["balance_history"][-100:]
        
        await self.manager.broadcast({
            "type": "update",
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def push_signal(self, signal: dict):
        """シグナル追加"""
        signal_data = {
            **signal,
            "timestamp": datetime.now().isoformat(),
        }
        self.state["recent_signals"].insert(0, signal_data)
        self.state["recent_signals"] = self.state["recent_signals"][:20]
        
        # Edge history for chart
        self.state["edge_history"].append({
            "time": datetime.now().isoformat(),
            "edge": signal.get("edge", 0),
        })
        self.state["edge_history"] = self.state["edge_history"][-50:]
        
        await self.manager.broadcast({
            "type": "signal",
            "data": signal_data,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def push_trade(self, trade: dict):
        """取引追加"""
        self.state["recent_trades"].insert(0, {
            **trade,
            "timestamp": datetime.now().isoformat(),
        })
        self.state["recent_trades"] = self.state["recent_trades"][:50]
        self.state["trades_today"] += 1
        
        await self.manager.broadcast({
            "type": "trade",
            "data": trade,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def push_trigger(self, trigger: dict):
        """トリガー追加/更新"""
        triggers = self.state["active_triggers"]
        found = False
        for i, t in enumerate(triggers):
            if t.get("token_id") == trigger.get("token_id"):
                triggers[i] = trigger
                found = True
                break
        
        if not found:
            triggers.append(trigger)
        
        self.state["active_triggers"] = triggers
        
        await self.manager.broadcast({
            "type": "trigger",
            "data": trigger,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def remove_trigger(self, token_id: str):
        """トリガー削除"""
        self.state["active_triggers"] = [
            t for t in self.state["active_triggers"]
            if t.get("token_id") != token_id
        ]
        
        await self.manager.broadcast({
            "type": "trigger_removed",
            "token_id": token_id,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def push_positions(self, positions: list):
        """オープンポジション一覧を更新"""
        self.state["open_positions"] = positions
        await self.manager.broadcast({
            "type": "positions",
            "data": positions,
            "timestamp": datetime.now().isoformat(),
        })

    async def push_price(self, symbol: str, price: float):
        """価格更新"""
        self.state["prices"][symbol] = price
        
        # Price history for chart
        self.state["price_history"].append({
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "price": price,
        })
        self.state["price_history"] = self.state["price_history"][-100:]
        
        await self.manager.broadcast({
            "type": "price",
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now().isoformat(),
        })
    
    def _get_dashboard_html(self) -> str:
        """ダッシュボードHTML - Operator Terminal aesthetic"""
        return '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>POLY AI TRADER</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #0d1117;
            --bg-surface: #161b22;
            --bg-elevated: #1c2230;
            --bg-hover: #222d3d;
            --border: #2a3548;
            --border-bright: #3a4d65;

            --amber: #f0a030;
            --amber-dim: rgba(240,160,48,0.15);
            --amber-border: rgba(240,160,48,0.4);
            --emerald: #2dc88a;
            --emerald-dim: rgba(45,200,138,0.12);
            --emerald-border: rgba(45,200,138,0.4);
            --red: #e84060;
            --red-dim: rgba(232,64,96,0.12);
            --blue: #4a9eff;
            --blue-dim: rgba(74,158,255,0.12);

            --text: #cdd9e5;
            --text-secondary: #768a9e;
            --text-dim: #4a5a6e;

            --font-mono: 'IBM Plex Mono', monospace;
            --font-sans: 'IBM Plex Sans', sans-serif;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: var(--font-sans);
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            font-size: 13px;
        }

        /* ── Layout ─────────────────────────────── */
        .shell {
            max-width: 1560px;
            margin: 0 auto;
            padding: 0 20px 32px;
        }

        /* ── Top Bar ─────────────────────────────── */
        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 14px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
            gap: 16px;
        }

        .wordmark {
            font-family: var(--font-mono);
            font-size: 14px;
            font-weight: 600;
            letter-spacing: 0.18em;
            color: var(--text);
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .wordmark-dot {
            width: 7px; height: 7px;
            border-radius: 50%;
            background: var(--text-dim);
            transition: background 0.3s;
        }
        .wordmark-dot.live { background: var(--emerald); box-shadow: 0 0 6px rgba(45,200,138,0.6); }

        .topbar-right {
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .price-pair {
            font-family: var(--font-mono);
            font-size: 11px;
            display: flex;
            gap: 16px;
        }
        .price-pair-item { color: var(--text-secondary); }
        .price-pair-item .sym { color: var(--text-dim); margin-right: 5px; }

        .sys-status {
            font-family: var(--font-mono);
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 3px;
            letter-spacing: 0.08em;
            border: 1px solid var(--border);
            color: var(--text-dim);
            background: var(--bg-surface);
        }
        .sys-status.running {
            border-color: var(--emerald-border);
            color: var(--emerald);
            background: var(--emerald-dim);
        }
        .sys-status.idle {
            border-color: var(--border);
            color: var(--text-dim);
        }

        /* ── Stats Bar ───────────────────────────── */
        .stats-bar {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            margin-bottom: 18px;
        }
        @media (max-width: 1100px) { .stats-bar { grid-template-columns: repeat(3,1fr); } }
        @media (max-width: 700px)  { .stats-bar { grid-template-columns: repeat(2,1fr); } }

        .stat-tile {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 14px 16px;
        }
        .stat-tile-label {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 8px;
        }
        .stat-tile-value {
            font-family: var(--font-mono);
            font-size: 22px;
            font-weight: 600;
            color: var(--text);
            line-height: 1;
        }
        .stat-tile-value.up   { color: var(--emerald); }
        .stat-tile-value.down { color: var(--red); }
        .stat-tile-value.amber { color: var(--amber); }

        /* ── Grid ────────────────────────────────── */
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }
        @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

        .col-full { grid-column: span 2; }
        @media (max-width: 900px) { .col-full { grid-column: span 1; } }

        /* ── Card ────────────────────────────────── */
        .card {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 6px;
            overflow: hidden;
        }

        .card-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
            background: rgba(255,255,255,0.01);
        }
        .card-title {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--text-secondary);
        }
        .card-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-dim);
        }

        .card-body {
            padding: 12px 14px;
            max-height: 340px;
            overflow-y: auto;
        }
        .card-body::-webkit-scrollbar { width: 3px; }
        .card-body::-webkit-scrollbar-track { background: transparent; }
        .card-body::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 2px; }

        /* ── Positions ───────────────────────────── */
        .pos-section-head {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 14px 6px;
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }
        .pos-section-head.pending-head {
            color: var(--amber);
            border-bottom: 1px solid rgba(240,160,48,0.12);
        }
        .pos-section-head.active-head {
            color: var(--emerald);
            border-bottom: 1px solid rgba(45,200,138,0.12);
            margin-top: 4px;
        }
        .section-count {
            background: var(--bg-elevated);
            border-radius: 10px;
            padding: 1px 7px;
            font-size: 9px;
        }

        .pos-row {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: 16px;
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
            position: relative;
            transition: background 0.12s;
        }
        .pos-row:last-child { border-bottom: none; }
        .pos-row:hover { background: var(--bg-hover); }

        .pos-row.pending {
            border-left: 2px solid var(--amber);
            padding-left: 12px;
        }
        .pos-row.active {
            border-left: 2px solid var(--emerald);
            padding-left: 12px;
        }
        .pos-row.active.losing {
            border-left-color: var(--red);
        }

        .pos-question {
            font-size: 12px;
            color: var(--text);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            margin-bottom: 6px;
        }
        .pos-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .pos-side {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 2px;
            letter-spacing: 0.08em;
        }
        .pos-side.yes {
            background: var(--blue-dim);
            border: 1px solid rgba(74,158,255,0.3);
            color: var(--blue);
        }
        .pos-side.no {
            background: rgba(180,100,255,0.1);
            border: 1px solid rgba(180,100,255,0.3);
            color: #b464ff;
        }
        .pos-prices {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 3px;
        }
        .pos-arrow { font-size: 8px; }
        .pos-arrow.up { color: var(--emerald); }
        .pos-arrow.dn { color: var(--red); }
        .pos-arrow.flat { color: var(--text-dim); }
        .pos-size { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
        .pos-age  { font-family: var(--font-mono); font-size: 9px;  color: var(--text-dim); }

        /* pending badge with pulse */
        .pending-tag {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 2px 7px;
            border-radius: 2px;
            letter-spacing: 0.1em;
            background: var(--amber-dim);
            border: 1px solid var(--amber-border);
            color: var(--amber);
            animation: fade-pulse 2s ease-in-out infinite;
        }
        @keyframes fade-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.45; }
        }

        .pos-pnl { text-align: right; white-space: nowrap; }
        .pos-pnl-amt {
            font-family: var(--font-mono);
            font-size: 15px;
            font-weight: 600;
            line-height: 1;
        }
        .pos-pnl-pct {
            font-family: var(--font-mono);
            font-size: 10px;
            margin-top: 2px;
        }
        .pnl-up   { color: var(--emerald); }
        .pnl-down { color: var(--red); }
        .pnl-flat { color: var(--text-dim); }
        .pnl-pending { color: var(--amber); font-style: italic; }

        /* ── Signals ─────────────────────────────── */
        .sig-row {
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
        }
        .sig-row:last-child { border-bottom: none; }
        .sig-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
            margin-bottom: 6px;
        }
        .sig-question {
            font-size: 12px;
            color: var(--text);
            line-height: 1.4;
            flex: 1;
        }
        .sig-action {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 2px;
            letter-spacing: 0.08em;
            white-space: nowrap;
        }
        .sig-action.buy  { background: var(--emerald-dim); border: 1px solid var(--emerald-border); color: var(--emerald); }
        .sig-action.sell { background: var(--red-dim); border: 1px solid rgba(232,64,96,0.4); color: var(--red); }
        .sig-action.hold { background: var(--bg-elevated); border: 1px solid var(--border); color: var(--text-dim); }
        .sig-meta {
            display: flex;
            gap: 14px;
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-dim);
        }
        .sig-meta .edge-up   { color: var(--emerald); }
        .sig-meta .edge-down { color: var(--red); }
        .edge-strip {
            height: 2px;
            background: var(--border);
            border-radius: 1px;
            margin-top: 6px;
            overflow: hidden;
        }
        .edge-strip-fill {
            height: 100%;
            border-radius: 1px;
            transition: width 0.3s ease;
        }
        .edge-strip-fill.up   { background: var(--emerald); }
        .edge-strip-fill.down { background: var(--red); }

        /* ── Triggers ────────────────────────────── */
        .trig-row {
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
        }
        .trig-row:last-child { border-bottom: none; }
        .trig-left { flex: 1; min-width: 0; }
        .trig-question { font-size: 12px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 4px; }
        .trig-meta { display: flex; gap: 10px; align-items: center; }
        .trig-side {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 2px;
        }
        .trig-side.buy  { background: var(--emerald-dim); border: 1px solid var(--emerald-border); color: var(--emerald); }
        .trig-side.sell { background: var(--red-dim); border: 1px solid rgba(232,64,96,0.4); color: var(--red); }
        .trig-price { font-family: var(--font-mono); font-size: 10px; color: var(--amber); }
        .trig-size  { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
        .trig-pulse {
            width: 6px; height: 6px;
            border-radius: 50%;
            background: var(--amber);
            box-shadow: 0 0 5px rgba(240,160,48,0.6);
            animation: fade-pulse 1.2s ease-in-out infinite;
            flex-shrink: 0;
        }

        /* ── Trades ──────────────────────────────── */
        .trade-row {
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: 12px;
        }
        .trade-row:last-child { border-bottom: none; }
        .trade-question { font-size: 12px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 4px; }
        .trade-meta { display: flex; gap: 10px; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
        .trade-status {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 600;
            white-space: nowrap;
        }
        .trade-status.ok  { color: var(--emerald); }
        .trade-status.err { color: var(--red); }
        .trade-time { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); }

        /* ── Charts ──────────────────────────────── */
        .chart-wrap { padding: 14px; height: 220px; }

        /* ── Empty ───────────────────────────────── */
        .empty {
            padding: 32px 16px;
            text-align: center;
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
        }
    </style>
</head>
<body>
<div class="shell">

    <!-- Top Bar -->
    <div class="topbar">
        <div class="wordmark">
            <span class="wordmark-dot" id="conn-dot"></span>
            POLY AI TRADER
        </div>
        <div class="topbar-right">
            <div class="price-pair">
                <span class="price-pair-item"><span class="sym">BTC</span><span id="btc-price">—</span></span>
                <span class="price-pair-item"><span class="sym">ETH</span><span id="eth-price">—</span></span>
            </div>
            <span class="sys-status idle" id="status-badge">IDLE</span>
        </div>
    </div>

    <!-- Stats Bar -->
    <div class="stats-bar">
        <div class="stat-tile">
            <div class="stat-tile-label">Balance</div>
            <div class="stat-tile-value" id="balance">$0.00</div>
        </div>
        <div class="stat-tile">
            <div class="stat-tile-label">PnL</div>
            <div class="stat-tile-value" id="pnl">+$0.00</div>
        </div>
        <div class="stat-tile">
            <div class="stat-tile-label">Trades</div>
            <div class="stat-tile-value" id="trades-count">0</div>
        </div>
        <div class="stat-tile">
            <div class="stat-tile-label">Triggers</div>
            <div class="stat-tile-value amber" id="triggers-count">0</div>
        </div>
        <div class="stat-tile">
            <div class="stat-tile-label">Positions</div>
            <div class="stat-tile-value" id="positions-count">0</div>
        </div>
    </div>

    <!-- Main Grid -->
    <div class="grid">

        <!-- Open Positions (full width, top priority) -->
        <div class="card col-full">
            <div class="card-head">
                <span class="card-title">Open Positions</span>
                <span class="card-badge" id="positions-badge">—</span>
            </div>
            <div id="positions-list"><div class="empty">No open positions</div></div>
        </div>

        <!-- Signals -->
        <div class="card">
            <div class="card-head">
                <span class="card-title">Live Signals</span>
                <span class="card-badge" id="signals-count">0</span>
            </div>
            <div class="card-body" id="signals-list">
                <div class="empty">Awaiting market data…</div>
            </div>
        </div>

        <!-- Triggers -->
        <div class="card">
            <div class="card-head">
                <span class="card-title">Active Triggers</span>
            </div>
            <div class="card-body" id="triggers-list">
                <div class="empty">No active triggers</div>
            </div>
        </div>

        <!-- Edge Chart -->
        <div class="card">
            <div class="card-head"><span class="card-title">Edge Distribution</span></div>
            <div class="chart-wrap"><canvas id="edge-chart"></canvas></div>
        </div>

        <!-- Balance Chart -->
        <div class="card">
            <div class="card-head"><span class="card-title">Balance & PnL</span></div>
            <div class="chart-wrap"><canvas id="balance-chart"></canvas></div>
        </div>

        <!-- Trade History -->
        <div class="card col-full">
            <div class="card-head"><span class="card-title">Trade History</span></div>
            <div class="card-body" id="trades-list">
                <div class="empty">No trades executed</div>
            </div>
        </div>

    </div>
</div>

<script>
    let ws, reconnectInterval, edgeChart, balanceChart;
    let edgeData = [], balanceData = [];

    // ── Charts ───────────────────────────────────
    function initCharts() {
        const gridColor = 'rgba(42,53,72,0.8)';
        const tickColor = '#4a5a6e';

        edgeChart = new Chart(document.getElementById('edge-chart').getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{
                data: [], borderColor: '#4a9eff',
                backgroundColor: 'rgba(74,158,255,0.08)',
                fill: true, tension: 0.4, pointRadius: 0, borderWidth: 1.5,
            }]},
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: tickColor, maxTicksLimit: 6, font: { family: 'IBM Plex Mono', size: 9 } } },
                    y: { grid: { color: gridColor }, ticks: { color: tickColor, callback: v => v.toFixed(0)+'%', font: { family: 'IBM Plex Mono', size: 9 } } },
                },
                interaction: { intersect: false, mode: 'index' },
            }
        });

        balanceChart = new Chart(document.getElementById('balance-chart').getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'Balance', data: [], borderColor: '#2dc88a', backgroundColor: 'rgba(45,200,138,0.07)',
                  fill: true, tension: 0.4, pointRadius: 0, borderWidth: 1.5, yAxisID: 'y' },
                { label: 'PnL', data: [], borderColor: '#f0a030', fill: false,
                  tension: 0.4, pointRadius: 0, borderWidth: 1.5, yAxisID: 'y1' },
            ]},
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: true, position: 'top', labels: { color: '#768a9e', font: { family: 'IBM Plex Mono', size: 9 }, boxWidth: 10 } } },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: tickColor, maxTicksLimit: 5, font: { family: 'IBM Plex Mono', size: 9 } } },
                    y:  { position: 'left',  grid: { color: gridColor }, ticks: { color: '#2dc88a', callback: v => '$'+v.toFixed(0), font: { family: 'IBM Plex Mono', size: 9 } } },
                    y1: { position: 'right', grid: { display: false },  ticks: { color: '#f0a030', callback: v => (v>=0?'+':'')+v.toFixed(1), font: { family: 'IBM Plex Mono', size: 9 } } },
                },
                interaction: { intersect: false, mode: 'index' },
            }
        });
    }

    function addEdgePoint(edge) {
        const t = new Date().toLocaleTimeString('ja-JP', { hour:'2-digit', minute:'2-digit' });
        edgeData.push({ t, v: edge * 100 });
        if (edgeData.length > 40) edgeData.shift();
        edgeChart.data.labels = edgeData.map(d => d.t);
        edgeChart.data.datasets[0].data = edgeData.map(d => d.v);
        edgeChart.update('none');
    }

    function addBalancePoint(bal, pnl) {
        const t = new Date().toLocaleTimeString('ja-JP', { hour:'2-digit', minute:'2-digit' });
        balanceData.push({ t, bal, pnl });
        if (balanceData.length > 60) balanceData.shift();
        balanceChart.data.labels = balanceData.map(d => d.t);
        balanceChart.data.datasets[0].data = balanceData.map(d => d.bal);
        balanceChart.data.datasets[1].data = balanceData.map(d => d.pnl);
        balanceChart.update('none');
    }

    // ── WebSocket ────────────────────────────────
    function connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws`);
        ws.onopen = () => {
            document.getElementById('conn-dot').classList.add('live');
            clearInterval(reconnectInterval);
        };
        ws.onclose = () => {
            document.getElementById('conn-dot').classList.remove('live');
            reconnectInterval = setInterval(connect, 3000);
        };
        ws.onmessage = e => handleMessage(JSON.parse(e.data));
    }

    function handleMessage(msg) {
        switch (msg.type) {
            case 'init':     initAll(msg.data); break;
            case 'update':   onUpdate(msg.key, msg.value); break;
            case 'signal':   prependSignal(msg.data); break;
            case 'trade':    prependTrade(msg.data); break;
            case 'trigger':  upsertTrigger(msg.data); break;
            case 'trigger_removed': removeTrigger(msg.token_id); break;
            case 'price':    updatePrice(msg.symbol, msg.price); break;
            case 'positions': renderPositions(msg.data || []); break;
        }
    }

    function initAll(s) {
        setBalance(s.balance);
        setPnl(s.pnl);
        document.getElementById('trades-count').textContent = s.trades_today;
        document.getElementById('triggers-count').textContent = s.active_triggers.length;
        if (s.prices.BTC) updatePrice('BTC', s.prices.BTC);
        if (s.prices.ETH) updatePrice('ETH', s.prices.ETH);
        const b = document.getElementById('status-badge');
        b.textContent = s.status.toUpperCase();
        b.className = 'sys-status ' + s.status;
        renderSignals(s.recent_signals || []);
        renderTriggers(s.active_triggers || []);
        renderPositions(s.open_positions || []);
        renderTrades(s.recent_trades || []);
        (s.edge_history || []).forEach(e => addEdgePoint(e.edge));
        (s.balance_history || []).forEach(b => addBalancePoint(b.balance, b.pnl));
        if (s.balance > 0) addBalancePoint(s.balance, s.pnl);
    }

    function onUpdate(key, val) {
        if (key === 'balance') { setBalance(val); addBalancePoint(val, currentPnlNum()); }
        else if (key === 'pnl') { setPnl(val); addBalancePoint(currentBalNum(), val); }
        else if (key === 'trades_today') document.getElementById('trades-count').textContent = val;
        else if (key === 'status') {
            const b = document.getElementById('status-badge');
            b.textContent = val.toUpperCase(); b.className = 'sys-status ' + val;
        }
    }

    function currentPnlNum() {
        return parseFloat(document.getElementById('pnl').dataset.raw || '0');
    }
    function currentBalNum() {
        return parseFloat(document.getElementById('balance').textContent.replace(/[^\\d.]/g,'')) || 0;
    }

    function setBalance(v) {
        document.getElementById('balance').textContent = '$' + v.toFixed(2);
    }
    function setPnl(v) {
        const el = document.getElementById('pnl');
        el.dataset.raw = v;
        el.textContent = (v >= 0 ? '+' : '') + '$' + v.toFixed(2);
        el.className = 'stat-tile-value ' + (v > 0 ? 'up' : v < 0 ? 'down' : '');
    }
    function updatePrice(sym, price) {
        const el = document.getElementById(sym.toLowerCase() + '-price');
        if (el) el.textContent = '$' + price.toLocaleString();
    }

    // ── Positions ────────────────────────────────
    function renderPositions(positions) {
        const wrap = document.getElementById('positions-list');
        const count = positions.length;
        document.getElementById('positions-count').textContent = count;

        const pending = positions.filter(p => p.order_filled === false);
        const active  = positions.filter(p => p.order_filled !== false);
        const totalPnl = active.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
        const pnlStr = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2);

        document.getElementById('positions-badge').textContent =
            count + ' position' + (count !== 1 ? 's' : '') +
            (active.length > 0 ? '  ·  pnl ' + pnlStr : '');

        if (!count) { wrap.innerHTML = '<div class="empty">No open positions</div>'; return; }

        let html = '';
        if (pending.length > 0) {
            html += `<div class="pos-section-head pending-head">⏳ GTC Pending <span class="section-count">${pending.length}</span></div>`;
            pending.forEach(p => { html += buildPosRow(p, true); });
        }
        if (active.length > 0) {
            html += `<div class="pos-section-head active-head">✓ Active <span class="section-count">${active.length}</span></div>`;
            active.forEach(p => { html += buildPosRow(p, false); });
        }
        wrap.innerHTML = html;
    }

    function buildPosRow(pos, isPending) {
        const pnl    = pos.unrealized_pnl     || 0;
        const pnlPct = pos.unrealized_pnl_pct || 0;
        const isUp   = pnl >  0.005;
        const isDn   = pnl < -0.005;

        const rowClass = isPending ? 'pos-row pending'
                       : isDn     ? 'pos-row active losing'
                       : 'pos-row active';

        const sideUpper = (pos.side || '').toUpperCase();
        const isYes = sideUpper.includes('YES');
        const sideClass = isYes ? 'yes' : 'no';
        const sideLabel = isYes ? 'BUY YES' : 'BUY NO';

        // BUY_NO は entry/current を NO価格で表示 (1 - YES価格)
        const dispEntry   = isYes ? (pos.entry_price   || 0) : (1 - (pos.entry_price   || 0));
        const dispCurrent = isYes ? (pos.current_price || 0) : (1 - (pos.current_price || 0));

        // BUY_NO: NO価格が上がれば有利なので矢印方向もNO基準
        const diff = dispCurrent - dispEntry;
        const arrowCls  = diff >  0.002 ? 'up' : diff < -0.002 ? 'dn' : 'flat';
        const arrowChar = diff >  0.002 ? '▲' : diff < -0.002 ? '▼' : '▶';

        let age = '';
        if (pos.created_at) {
            const ms = Date.now() - new Date(pos.created_at).getTime();
            const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000);
            age = h > 0 ? `${h}h${m}m` : `${m}m`;
        }

        let pnlHtml = '';
        if (isPending) {
            pnlHtml = `<div class="pos-pnl">
                <div class="pos-pnl-amt pnl-pending">GTC</div>
                <div class="pos-pnl-pct pnl-flat">awaiting fill</div>
            </div>`;
        } else {
            const cls = isUp ? 'pnl-up' : isDn ? 'pnl-down' : 'pnl-flat';
            const sign = pnl >= 0 ? '+' : '';
            pnlHtml = `<div class="pos-pnl">
                <div class="pos-pnl-amt ${cls}">${sign}$${Math.abs(pnl).toFixed(2)}</div>
                <div class="pos-pnl-pct ${cls}">${sign}${(pnlPct*100).toFixed(1)}%</div>
            </div>`;
        }

        const pendingBadge = isPending ? '<span class="pending-tag">PENDING</span>' : '';

        return `<div class="${rowClass}">
            <div>
                <div class="pos-question">${pos.question || 'Unknown'}</div>
                <div class="pos-meta">
                    <span class="pos-side ${sideClass}">${sideLabel}</span>
                    <span class="pos-prices">
                        <span>${(dispEntry*100).toFixed(1)}¢</span>
                        <span class="pos-arrow ${arrowCls}">${arrowChar}</span>
                        <span>${(dispCurrent*100).toFixed(1)}¢</span>
                    </span>
                    <span class="pos-size">$${(pos.size||0).toFixed(2)}</span>
                    ${age ? `<span class="pos-age">${age}</span>` : ''}
                    ${pendingBadge}
                </div>
            </div>
            ${pnlHtml}
        </div>`;
    }

    // ── Signals ──────────────────────────────────
    function renderSignals(signals) {
        const el = document.getElementById('signals-list');
        document.getElementById('signals-count').textContent = signals.length;
        if (!signals.length) { el.innerHTML = '<div class="empty">Awaiting market data…</div>'; return; }
        el.innerHTML = '';
        signals.slice(0, 15).forEach(s => el.appendChild(buildSignalEl(s)));
    }
    function prependSignal(s) {
        const el = document.getElementById('signals-list');
        if (el.querySelector('.empty')) el.innerHTML = '';
        el.insertBefore(buildSignalEl(s), el.firstChild);
        while (el.children.length > 15) el.removeChild(el.lastChild);
        document.getElementById('signals-count').textContent = el.children.length;
        if (s.edge !== undefined) addEdgePoint(s.edge);
    }
    function buildSignalEl(s) {
        const div = document.createElement('div');
        div.className = 'sig-row';
        const action = (s.action || 'hold').toLowerCase();
        const aCls = action.includes('buy') ? 'buy' : action.includes('sell') ? 'sell' : 'hold';
        const edge = s.edge || 0;
        const eCls = edge >= 0 ? 'edge-up' : 'edge-down';
        const edgeW = Math.min(Math.abs(edge) * 500, 100).toFixed(1);
        div.innerHTML = `
            <div class="sig-top">
                <span class="sig-question">${s.question || 'Unknown'}</span>
                <span class="sig-action ${aCls}">${(s.action||'HOLD').toUpperCase()}</span>
            </div>
            <div class="sig-meta">
                <span>MKT ${((s.market_price||0)*100).toFixed(1)}%</span>
                <span>PRED ${((s.predicted_prob||0)*100).toFixed(1)}%</span>
                <span class="${eCls}">EDGE ${edge>=0?'+':''}${(edge*100).toFixed(1)}%</span>
                <span>CONF ${((s.confidence||0)*100).toFixed(0)}%</span>
            </div>
            <div class="edge-strip">
                <div class="edge-strip-fill ${edge>=0?'up':'down'}" style="width:${edgeW}%"></div>
            </div>`;
        return div;
    }

    // ── Triggers ─────────────────────────────────
    function renderTriggers(triggers) {
        const el = document.getElementById('triggers-list');
        if (!triggers.length) { el.innerHTML = '<div class="empty">No active triggers</div>'; return; }
        el.innerHTML = '';
        triggers.forEach(t => upsertTrigger(t));
    }
    function upsertTrigger(t) {
        const list = document.getElementById('triggers-list');
        if (list.querySelector('.empty')) list.innerHTML = '';
        let el = list.querySelector(`[data-token="${t.token_id}"]`);
        if (!el) { el = document.createElement('div'); el.className = 'trig-row'; el.dataset.token = t.token_id; list.appendChild(el); }
        const side = (t.side||'buy').toLowerCase();
        const sCls = side.includes('sell') ? 'sell' : 'buy';
        el.innerHTML = `
            <div class="trig-left">
                <div class="trig-question">${t.question||'Unknown'}</div>
                <div class="trig-meta">
                    <span class="trig-side ${sCls}">${t.side||'BUY'}</span>
                    <span class="trig-price">@ ${(t.target_price||0).toFixed(4)}</span>
                    <span class="trig-size">$${(t.size||0).toFixed(2)}</span>
                </div>
            </div>
            <div class="trig-pulse"></div>`;
        document.getElementById('triggers-count').textContent = list.querySelectorAll('.trig-row').length;
    }
    function removeTrigger(tokenId) {
        const el = document.querySelector(`[data-token="${tokenId}"]`);
        if (el) el.remove();
        const list = document.getElementById('triggers-list');
        if (!list.querySelectorAll('.trig-row').length) list.innerHTML = '<div class="empty">No active triggers</div>';
        document.getElementById('triggers-count').textContent = list.querySelectorAll('.trig-row').length;
    }

    // ── Trades ───────────────────────────────────
    function renderTrades(trades) {
        const el = document.getElementById('trades-list');
        if (!trades.length) { el.innerHTML = '<div class="empty">No trades executed</div>'; return; }
        el.innerHTML = '';
        trades.forEach(t => el.appendChild(buildTradeEl(t)));
    }
    function prependTrade(t) {
        const el = document.getElementById('trades-list');
        if (el.querySelector('.empty')) el.innerHTML = '';
        el.insertBefore(buildTradeEl(t), el.firstChild);
        document.getElementById('trades-count').textContent =
            parseInt(document.getElementById('trades-count').textContent || '0') + 1;
    }
    function buildTradeEl(t) {
        const div = document.createElement('div');
        div.className = 'trade-row';
        const ts = t.timestamp ? new Date(t.timestamp).toLocaleTimeString('ja-JP') : '';
        const ok = t.success !== false;
        div.innerHTML = `
            <div>
                <div class="trade-question">${t.question||'Unknown'}</div>
                <div class="trade-meta">
                    <span>${t.side||'BUY'} @ ${(t.price||0).toFixed(4)}</span>
                    <span>$${(t.size||0).toFixed(2)}</span>
                    ${ts ? `<span class="trade-time">${ts}</span>` : ''}
                </div>
            </div>
            <span class="trade-status ${ok?'ok':'err'}">${ok ? '✓ PLACED' : '✗ FAILED'}</span>`;
        return div;
    }

    // ── Boot ─────────────────────────────────────
    initCharts();
    connect();
    setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping'); }, 30000);
</script>
</body>
</html>'''
    
    def run(self):
        """サーバー起動"""
        print(f"🌐 Dashboard: http://{self.host}:{self.port}")
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning")
    
    async def run_async(self):
        """非同期サーバー起動"""
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()


# テスト
if __name__ == "__main__":
    server = DashboardServer()
    server.run()
