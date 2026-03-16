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
        """ダッシュボードHTML - Cyberpunk aesthetic"""
        return '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>POLY AI TRADER</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700;900&family=JetBrains+Mono:wght@300;400;500&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-void: #000000;
            --bg-deep: #0a0a0f;
            --bg-surface: #12121a;
            --bg-elevated: #1a1a24;
            --bg-hover: #22222e;
            
            --neon-cyan: #00ffff;
            --neon-magenta: #ff00ff;
            --neon-green: #00ff88;
            --neon-red: #ff3366;
            --neon-yellow: #ffcc00;
            --neon-blue: #0088ff;
            
            --text-primary: #ffffff;
            --text-secondary: #888899;
            --text-dim: #555566;
            
            --glow-cyan: 0 0 20px rgba(0, 255, 255, 0.5), 0 0 40px rgba(0, 255, 255, 0.2);
            --glow-green: 0 0 20px rgba(0, 255, 136, 0.5), 0 0 40px rgba(0, 255, 136, 0.2);
            --glow-red: 0 0 20px rgba(255, 51, 102, 0.5), 0 0 40px rgba(255, 51, 102, 0.2);
            
            --font-display: 'Orbitron', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --font-body: 'Inter', sans-serif;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: var(--font-body);
            background: var(--bg-void);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        /* Animated grid background */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: 
                linear-gradient(90deg, rgba(0, 255, 255, 0.03) 1px, transparent 1px),
                linear-gradient(rgba(0, 255, 255, 0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            pointer-events: none;
            z-index: 0;
        }
        
        /* Scanline effect */
        body::after {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: repeating-linear-gradient(
                0deg,
                transparent,
                transparent 2px,
                rgba(0, 0, 0, 0.1) 2px,
                rgba(0, 0, 0, 0.1) 4px
            );
            pointer-events: none;
            z-index: 1000;
            opacity: 0.3;
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 1;
        }
        
        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 0;
            margin-bottom: 24px;
            border-bottom: 1px solid rgba(0, 255, 255, 0.2);
        }
        
        .logo {
            font-family: var(--font-display);
            font-size: 1.8em;
            font-weight: 900;
            letter-spacing: 0.15em;
            text-transform: uppercase;
            background: linear-gradient(135deg, var(--neon-cyan), var(--neon-magenta));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: var(--glow-cyan);
            animation: glow-pulse 2s ease-in-out infinite;
        }
        
        @keyframes glow-pulse {
            0%, 100% { filter: brightness(1); }
            50% { filter: brightness(1.2); }
        }
        
        .header-right {
            display: flex;
            align-items: center;
            gap: 24px;
        }
        
        .price-ticker {
            display: flex;
            gap: 20px;
            font-family: var(--font-mono);
        }
        
        .price-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: var(--bg-surface);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 4px;
        }
        
        .price-symbol {
            color: var(--neon-yellow);
            font-weight: 500;
            font-size: 0.85em;
        }
        
        .price-value {
            color: var(--text-primary);
            font-weight: 500;
        }
        
        .status-container {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .connection-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--neon-red);
            box-shadow: var(--glow-red);
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        .connection-dot.connected {
            background: var(--neon-green);
            box-shadow: var(--glow-green);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.1); }
        }
        
        .status-badge {
            font-family: var(--font-display);
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        
        .status-running {
            background: linear-gradient(135deg, rgba(0, 255, 136, 0.2), rgba(0, 255, 136, 0.1));
            border: 1px solid var(--neon-green);
            color: var(--neon-green);
        }
        
        .status-idle {
            background: rgba(136, 136, 153, 0.1);
            border: 1px solid var(--text-dim);
            color: var(--text-secondary);
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }
        
        @media (max-width: 1200px) {
            .stats-grid { grid-template-columns: repeat(3, 1fr); }
        }
        @media (max-width: 800px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
        
        .stat-card {
            background: linear-gradient(135deg, var(--bg-surface), var(--bg-deep));
            border: 1px solid rgba(0, 255, 255, 0.15);
            border-radius: 8px;
            padding: 24px;
            position: relative;
            overflow: hidden;
        }
        
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, var(--neon-cyan), var(--neon-magenta));
        }
        
        .stat-label {
            font-family: var(--font-mono);
            color: var(--text-secondary);
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.15em;
            margin-bottom: 12px;
        }
        
        .stat-value {
            font-family: var(--font-display);
            font-size: 2em;
            font-weight: 700;
            color: var(--neon-cyan);
        }
        
        .stat-value.positive {
            color: var(--neon-green);
            text-shadow: var(--glow-green);
        }
        
        .stat-value.negative {
            color: var(--neon-red);
            text-shadow: var(--glow-red);
        }
        
        /* Main Grid */
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            grid-template-rows: auto auto;
            gap: 20px;
        }
        
        @media (max-width: 1000px) {
            .main-grid { grid-template-columns: 1fr; }
        }
        
        .panel {
            background: linear-gradient(180deg, var(--bg-surface), var(--bg-deep));
            border: 1px solid rgba(0, 255, 255, 0.1);
            border-radius: 8px;
            overflow: hidden;
        }
        
        .panel.full-width {
            grid-column: span 2;
        }
        
        @media (max-width: 1000px) {
            .panel.full-width { grid-column: span 1; }
        }
        
        .panel-header {
            padding: 16px 20px;
            border-bottom: 1px solid rgba(0, 255, 255, 0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 255, 255, 0.02);
        }
        
        .panel-title {
            font-family: var(--font-display);
            font-size: 0.85em;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: var(--neon-cyan);
        }
        
        .panel-badge {
            font-family: var(--font-mono);
            font-size: 0.7em;
            padding: 4px 8px;
            background: rgba(0, 255, 255, 0.1);
            border-radius: 4px;
            color: var(--text-secondary);
        }
        
        .panel-body {
            padding: 16px 20px;
            max-height: 350px;
            overflow-y: auto;
        }
        
        .panel-body::-webkit-scrollbar {
            width: 4px;
        }
        
        .panel-body::-webkit-scrollbar-track {
            background: var(--bg-deep);
        }
        
        .panel-body::-webkit-scrollbar-thumb {
            background: var(--neon-cyan);
            border-radius: 2px;
        }
        
        /* Position Items */
        .position-item {
            position: relative;
            background: var(--bg-elevated);
            border-radius: 6px;
            margin-bottom: 8px;
            overflow: hidden;
            transition: transform 0.15s ease, background 0.15s ease;
        }
        .position-item:last-child { margin-bottom: 0; }
        .position-item:hover { background: var(--bg-hover); transform: translateX(3px); }
        .position-item.pos-winning { border-left: 3px solid var(--neon-green); box-shadow: inset 0 0 40px rgba(0,255,136,0.04); }
        .position-item.pos-losing  { border-left: 3px solid var(--neon-red);   box-shadow: inset 0 0 40px rgba(255,51,102,0.04); }
        .position-item.pos-neutral { border-left: 3px solid var(--neon-blue); }

        .position-inner {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: 20px;
            padding: 14px 18px 18px 16px;
        }
        .position-question {
            font-size: 12px;
            color: var(--text-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 9px;
            letter-spacing: 0.01em;
        }
        .position-details {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .pos-side-badge {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 3px;
            letter-spacing: 0.06em;
        }
        .pos-side-yes {
            background: rgba(0,255,255,0.12);
            border: 1px solid rgba(0,255,255,0.35);
            color: var(--neon-cyan);
        }
        .pos-side-no {
            background: rgba(255,0,255,0.12);
            border: 1px solid rgba(255,0,255,0.35);
            color: var(--neon-magenta);
        }
        .pos-price-flow {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-secondary);
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .pos-arrow-up   { color: var(--neon-green); font-size: 9px; }
        .pos-arrow-down { color: var(--neon-red);   font-size: 9px; }
        .pos-arrow-flat { color: var(--text-dim);   font-size: 9px; }
        .pos-size     { font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); }
        .pos-duration { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }

        .position-pnl-display { text-align: right; white-space: nowrap; }
        .pos-pnl-amount {
            font-family: var(--font-mono);
            font-size: 17px;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 3px;
        }
        .pos-pnl-pct {
            font-family: var(--font-mono);
            font-size: 11px;
        }
        .pnl-win  { color: var(--neon-green); text-shadow: 0 0 12px rgba(0,255,136,0.45); }
        .pnl-loss { color: var(--neon-red);   text-shadow: 0 0 12px rgba(255,51,102,0.45); }
        .pnl-flat { color: var(--text-secondary); }

        /* PnL progress bar at bottom of card */
        .pos-bar {
            position: absolute;
            bottom: 0; left: 0;
            height: 2px;
            transition: width 0.6s cubic-bezier(.22,1,.36,1);
        }
        .pos-bar.winning { background: linear-gradient(90deg, var(--neon-green), rgba(0,255,136,0.2)); }
        .pos-bar.losing  { background: linear-gradient(90deg, var(--neon-red),   rgba(255,51,102,0.2)); left: auto; right: 0; }

        /* Signal Items */
        .signal-item {
            padding: 16px;
            background: var(--bg-elevated);
            border-radius: 6px;
            margin-bottom: 12px;
            border-left: 3px solid var(--neon-cyan);
            transition: all 0.2s ease;
        }
        
        .signal-item:hover {
            background: var(--bg-hover);
            border-left-color: var(--neon-magenta);
        }
        
        .signal-item:last-child {
            margin-bottom: 0;
        }
        
        .signal-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
            gap: 12px;
        }
        
        .signal-question {
            font-weight: 500;
            color: var(--text-primary);
            line-height: 1.4;
            flex: 1;
        }
        
        .signal-action {
            font-family: var(--font-mono);
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 0.7em;
            font-weight: 600;
            letter-spacing: 0.05em;
            white-space: nowrap;
        }
        
        .action-buy_yes, .action-buy_no, .action-buy {
            background: linear-gradient(135deg, rgba(0, 255, 136, 0.3), rgba(0, 255, 136, 0.1));
            border: 1px solid var(--neon-green);
            color: var(--neon-green);
        }
        
        .action-sell_yes, .action-sell_no, .action-sell {
            background: linear-gradient(135deg, rgba(255, 51, 102, 0.3), rgba(255, 51, 102, 0.1));
            border: 1px solid var(--neon-red);
            color: var(--neon-red);
        }
        
        .action-hold {
            background: rgba(136, 136, 153, 0.2);
            border: 1px solid var(--text-dim);
            color: var(--text-secondary);
        }
        
        .signal-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            font-family: var(--font-mono);
            font-size: 0.8em;
        }
        
        .signal-meta span {
            color: var(--text-secondary);
        }
        
        .edge-positive { color: var(--neon-green) !important; }
        .edge-negative { color: var(--neon-red) !important; }
        
        /* Trigger Items */
        .trigger-item {
            padding: 16px;
            background: var(--bg-elevated);
            border-radius: 6px;
            margin-bottom: 12px;
            border-left: 3px solid var(--neon-yellow);
            position: relative;
        }
        
        .trigger-item::after {
            content: '';
            position: absolute;
            right: 16px;
            top: 50%;
            transform: translateY(-50%);
            width: 8px;
            height: 8px;
            background: var(--neon-yellow);
            border-radius: 50%;
            animation: pulse 1s ease-in-out infinite;
        }
        
        .trigger-price {
            font-family: var(--font-mono);
            font-size: 1.1em;
            color: var(--neon-yellow);
        }
        
        /* Trade Items */
        .trade-item {
            padding: 16px;
            background: var(--bg-elevated);
            border-radius: 6px;
            margin-bottom: 12px;
        }
        
        .trade-item.trade-success {
            border-left: 3px solid var(--neon-green);
        }
        
        .trade-item.trade-fail {
            border-left: 3px solid var(--neon-red);
        }
        
        .timestamp {
            font-family: var(--font-mono);
            font-size: 0.7em;
            color: var(--text-dim);
        }
        
        /* Charts */
        .chart-container {
            padding: 20px;
            height: 250px;
        }
        
        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 48px 24px;
            color: var(--text-dim);
            font-family: var(--font-mono);
            font-size: 0.85em;
        }
        
        .empty-state::before {
            content: '◇';
            display: block;
            font-size: 2em;
            margin-bottom: 12px;
            color: var(--text-dim);
            animation: spin 4s linear infinite;
        }
        
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        /* Edge Bar Visualization */
        .edge-bar {
            height: 4px;
            background: var(--bg-deep);
            border-radius: 2px;
            margin-top: 8px;
            overflow: hidden;
        }
        
        .edge-bar-fill {
            height: 100%;
            border-radius: 2px;
            transition: width 0.3s ease;
        }
        
        .edge-bar-fill.positive {
            background: linear-gradient(90deg, var(--neon-green), rgba(0, 255, 136, 0.5));
        }
        
        .edge-bar-fill.negative {
            background: linear-gradient(90deg, var(--neon-red), rgba(255, 51, 102, 0.5));
        }
        
        /* Confidence Ring */
        .confidence-ring {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: conic-gradient(
                var(--neon-cyan) calc(var(--conf) * 100%),
                var(--bg-deep) 0
            );
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-mono);
            font-size: 0.65em;
            position: relative;
        }
        
        .confidence-ring::before {
            content: '';
            position: absolute;
            inset: 3px;
            background: var(--bg-elevated);
            border-radius: 50%;
        }
        
        .confidence-ring span {
            position: relative;
            z-index: 1;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">POLY AI TRADER</div>
            <div class="header-right">
                <div class="price-ticker">
                    <div class="price-item">
                        <span class="price-symbol">BTC</span>
                        <span class="price-value" id="btc-price">$0</span>
                    </div>
                    <div class="price-item">
                        <span class="price-symbol">ETH</span>
                        <span class="price-value" id="eth-price">$0</span>
                    </div>
                </div>
                <div class="status-container">
                    <span class="connection-dot" id="conn-status"></span>
                    <span class="status-badge status-idle" id="status-badge">IDLE</span>
                </div>
            </div>
        </header>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Balance</div>
                <div class="stat-value" id="balance">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Today's PnL</div>
                <div class="stat-value" id="pnl">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Trades</div>
                <div class="stat-value" id="trades-count">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Triggers</div>
                <div class="stat-value" id="triggers-count">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Open Positions</div>
                <div class="stat-value" id="positions-count">0</div>
            </div>
        </div>
        
        <div class="main-grid">
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">◈ Live Signals</span>
                    <span class="panel-badge" id="signals-count">0 signals</span>
                </div>
                <div class="panel-body" id="signals-list">
                    <div class="empty-state">Awaiting market data...</div>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">◈ Active Triggers</span>
                </div>
                <div class="panel-body" id="triggers-list">
                    <div class="empty-state">No active triggers</div>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">◈ Edge Distribution</span>
                </div>
                <div class="chart-container">
                    <canvas id="edge-chart"></canvas>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-header">
                    <span class="panel-title">◈ Balance & PnL</span>
                </div>
                <div class="chart-container">
                    <canvas id="balance-chart"></canvas>
                </div>
            </div>
            
            <div class="panel full-width">
                <div class="panel-header">
                    <span class="panel-title">◈ Open Positions</span>
                    <span class="panel-badge" id="positions-badge">0 positions</span>
                </div>
                <div class="panel-body" id="positions-list">
                    <div class="empty-state">No open positions</div>
                </div>
            </div>

            <div class="panel full-width">
                <div class="panel-header">
                    <span class="panel-title">◈ Trade History</span>
                </div>
                <div class="panel-body" id="trades-list">
                    <div class="empty-state">No trades executed</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let ws;
        let reconnectInterval;
        let edgeChart;
        let balanceChart;
        let edgeData = [];
        let balanceData = [];
        
        // Initialize Charts
        function initChart() {
            const ctx = document.getElementById('edge-chart').getContext('2d');
            edgeChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Edge %',
                        data: [],
                        borderColor: '#00ffff',
                        backgroundColor: 'rgba(0, 255, 255, 0.1)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: '#00ffff',
                        pointHoverBorderColor: '#fff',
                        borderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                    },
                    scales: {
                        x: {
                            display: true,
                            grid: { color: 'rgba(0, 255, 255, 0.05)' },
                            ticks: { color: '#555566', maxTicksLimit: 8 },
                        },
                        y: {
                            display: true,
                            grid: { color: 'rgba(0, 255, 255, 0.05)' },
                            ticks: {
                                color: '#555566',
                                callback: v => v.toFixed(0) + '%'
                            },
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index',
                    },
                }
            });
            
            // Balance Chart
            const ctx2 = document.getElementById('balance-chart').getContext('2d');
            balanceChart = new Chart(ctx2, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Balance',
                            data: [],
                            borderColor: '#00ff88',
                            backgroundColor: 'rgba(0, 255, 136, 0.1)',
                            fill: true,
                            tension: 0.4,
                            pointRadius: 0,
                            borderWidth: 2,
                            yAxisID: 'y',
                        },
                        {
                            label: 'PnL',
                            data: [],
                            borderColor: '#ff00ff',
                            backgroundColor: 'rgba(255, 0, 255, 0.05)',
                            fill: false,
                            tension: 0.4,
                            pointRadius: 0,
                            borderWidth: 2,
                            yAxisID: 'y1',
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { 
                            display: true,
                            position: 'top',
                            labels: { color: '#888899', font: { size: 10 } }
                        },
                    },
                    scales: {
                        x: {
                            display: true,
                            grid: { color: 'rgba(0, 255, 136, 0.05)' },
                            ticks: { color: '#555566', maxTicksLimit: 6 },
                        },
                        y: {
                            type: 'linear',
                            display: true,
                            position: 'left',
                            grid: { color: 'rgba(0, 255, 136, 0.05)' },
                            ticks: {
                                color: '#00ff88',
                                callback: v => '$' + v.toFixed(0)
                            },
                        },
                        y1: {
                            type: 'linear',
                            display: true,
                            position: 'right',
                            grid: { display: false },
                            ticks: {
                                color: '#ff00ff',
                                callback: v => (v >= 0 ? '+' : '') + '$' + v.toFixed(0)
                            },
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index',
                    },
                }
            });
        }
        
        function addBalancePoint(balance, pnl) {
            const now = new Date().toLocaleTimeString();
            balanceData.push({ time: now, balance: balance, pnl: pnl });
            if (balanceData.length > 50) balanceData.shift();
            
            balanceChart.data.labels = balanceData.map(d => d.time);
            balanceChart.data.datasets[0].data = balanceData.map(d => d.balance);
            balanceChart.data.datasets[1].data = balanceData.map(d => d.pnl);
            balanceChart.update('none');
        }
        
        function addEdgePoint(edge) {
            const now = new Date().toLocaleTimeString();
            edgeData.push({ time: now, edge: edge * 100 });
            if (edgeData.length > 30) edgeData.shift();
            
            edgeChart.data.labels = edgeData.map(d => d.time);
            edgeChart.data.datasets[0].data = edgeData.map(d => d.edge);
            edgeChart.update('none');
        }
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                console.log('Connected');
                document.getElementById('conn-status').classList.add('connected');
                clearInterval(reconnectInterval);
            };
            
            ws.onclose = () => {
                console.log('Disconnected');
                document.getElementById('conn-status').classList.remove('connected');
                reconnectInterval = setInterval(connect, 3000);
            };
            
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            };
        }
        
        function handleMessage(msg) {
            switch (msg.type) {
                case 'init':
                    updateAll(msg.data);
                    break;
                case 'update':
                    updateField(msg.key, msg.value);
                    break;
                case 'signal':
                    addSignal(msg.data);
                    break;
                case 'trade':
                    addTrade(msg.data);
                    break;
                case 'trigger':
                    updateTrigger(msg.data);
                    break;
                case 'trigger_removed':
                    removeTrigger(msg.token_id);
                    break;
                case 'price':
                    updatePrice(msg.symbol, msg.price);
                    break;
                case 'positions':
                    renderPositions(msg.data || []);
                    break;
            }
        }
        
        function updateAll(state) {
            document.getElementById('balance').textContent = `$${state.balance.toFixed(2)}`;
            updatePnL(state.pnl);
            document.getElementById('trades-count').textContent = state.trades_today;
            document.getElementById('triggers-count').textContent = state.active_triggers.length;
            
            if (state.prices.BTC) updatePrice('BTC', state.prices.BTC);
            if (state.prices.ETH) updatePrice('ETH', state.prices.ETH);
            
            const badge = document.getElementById('status-badge');
            badge.textContent = state.status.toUpperCase();
            badge.className = `status-badge status-${state.status}`;
            
            renderSignals(state.recent_signals);
            renderTriggers(state.active_triggers);
            renderPositions(state.open_positions || []);
            renderTrades(state.recent_trades);
            
            // Load edge history
            if (state.edge_history) {
                state.edge_history.forEach(e => addEdgePoint(e.edge));
            }
            
            // Load balance history
            if (state.balance_history) {
                state.balance_history.forEach(b => addBalancePoint(b.balance, b.pnl));
            }
            
            // Initial balance point
            if (state.balance > 0) {
                addBalancePoint(state.balance, state.pnl);
            }
        }
        
        function updateField(key, value) {
            switch (key) {
                case 'balance':
                    document.getElementById('balance').textContent = `$${value.toFixed(2)}`;
                    // Update balance chart
                    const currentPnl = parseFloat(document.getElementById('pnl').textContent.replace(/[^-0-9.]/g, '')) || 0;
                    addBalancePoint(value, currentPnl);
                    break;
                case 'pnl':
                    updatePnL(value);
                    // Update balance chart
                    const currentBalance = parseFloat(document.getElementById('balance').textContent.replace(/[^0-9.]/g, '')) || 0;
                    addBalancePoint(currentBalance, value);
                    break;
                case 'trades_today':
                    document.getElementById('trades-count').textContent = value;
                    break;
                case 'status':
                    const badge = document.getElementById('status-badge');
                    badge.textContent = value.toUpperCase();
                    badge.className = `status-badge status-${value}`;
                    break;
            }
        }
        
        function updatePnL(value) {
            const el = document.getElementById('pnl');
            el.textContent = `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;
            el.className = `stat-value ${value >= 0 ? 'positive' : 'negative'}`;
        }
        
        function updatePrice(symbol, price) {
            const el = document.getElementById(symbol.toLowerCase() + '-price');
            if (el) el.textContent = `$${price.toLocaleString()}`;
        }
        
        function addSignal(signal) {
            const list = document.getElementById('signals-list');
            if (list.querySelector('.empty-state')) list.innerHTML = '';
            
            const el = createSignalElement(signal);
            list.insertBefore(el, list.firstChild);
            
            // Keep max 15
            while (list.children.length > 15) {
                list.removeChild(list.lastChild);
            }
            
            document.getElementById('signals-count').textContent = list.children.length + ' signals';
            
            // Add to chart
            if (signal.edge !== undefined) {
                addEdgePoint(signal.edge);
            }
        }
        
        function renderSignals(signals) {
            const list = document.getElementById('signals-list');
            if (!signals.length) {
                list.innerHTML = '<div class="empty-state">Awaiting market data...</div>';
                document.getElementById('signals-count').textContent = '0 signals';
                return;
            }
            
            list.innerHTML = '';
            signals.slice(0, 15).forEach(s => list.appendChild(createSignalElement(s)));
            document.getElementById('signals-count').textContent = signals.length + ' signals';
        }
        
        function createSignalElement(signal) {
            const div = document.createElement('div');
            div.className = 'signal-item';
            
            const action = (signal.action || 'hold').toLowerCase().replace(/_/g, '_');
            const actionClass = action.includes('buy') ? 'action-buy' : 
                               action.includes('sell') ? 'action-sell' : 'action-hold';
            const edge = signal.edge || 0;
            const edgeClass = edge >= 0 ? 'edge-positive' : 'edge-negative';
            const edgeWidth = Math.min(Math.abs(edge) * 100 * 5, 100); // Scale for visibility
            
            div.innerHTML = `
                <div class="signal-header">
                    <span class="signal-question">${signal.question || 'Unknown'}</span>
                    <span class="signal-action ${actionClass}">${(signal.action || 'HOLD').toUpperCase()}</span>
                </div>
                <div class="signal-meta">
                    <span>MKT ${((signal.market_price || 0) * 100).toFixed(1)}%</span>
                    <span>PRED ${((signal.predicted_prob || 0) * 100).toFixed(1)}%</span>
                    <span class="${edgeClass}">EDGE ${edge >= 0 ? '+' : ''}${(edge * 100).toFixed(1)}%</span>
                    <span>CONF ${((signal.confidence || 0) * 100).toFixed(0)}%</span>
                </div>
                <div class="edge-bar">
                    <div class="edge-bar-fill ${edge >= 0 ? 'positive' : 'negative'}" style="width: ${edgeWidth}%"></div>
                </div>
            `;
            
            return div;
        }
        
        function updateTrigger(trigger) {
            const list = document.getElementById('triggers-list');
            if (list.querySelector('.empty-state')) list.innerHTML = '';
            
            let el = list.querySelector(`[data-token="${trigger.token_id}"]`);
            if (!el) {
                el = document.createElement('div');
                el.className = 'trigger-item';
                el.dataset.token = trigger.token_id;
                list.appendChild(el);
            }
            
            el.innerHTML = `
                <div class="signal-header">
                    <span class="signal-question">${trigger.question || 'Unknown'}</span>
                    <span class="signal-action action-${(trigger.side || 'buy').toLowerCase()}">${trigger.side || 'BUY'}</span>
                </div>
                <div class="signal-meta">
                    <span class="trigger-price">@ ${trigger.target_price?.toFixed(4) || '0'}</span>
                    <span>SIZE $${trigger.size?.toFixed(2) || '0'}</span>
                </div>
            `;
            
            document.getElementById('triggers-count').textContent = list.querySelectorAll('.trigger-item').length;
        }
        
        function removeTrigger(tokenId) {
            const el = document.querySelector(`[data-token="${tokenId}"]`);
            if (el) el.remove();
            
            const list = document.getElementById('triggers-list');
            if (!list.querySelectorAll('.trigger-item').length) {
                list.innerHTML = '<div class="empty-state">No active triggers</div>';
            }
            document.getElementById('triggers-count').textContent = list.querySelectorAll('.trigger-item').length;
        }
        
        function renderTriggers(triggers) {
            const list = document.getElementById('triggers-list');
            if (!triggers.length) {
                list.innerHTML = '<div class="empty-state">No active triggers</div>';
                return;
            }
            
            list.innerHTML = '';
            triggers.forEach(t => updateTrigger(t));
        }
        
        function addTrade(trade) {
            const list = document.getElementById('trades-list');
            if (list.querySelector('.empty-state')) list.innerHTML = '';
            
            const el = createTradeElement(trade);
            list.insertBefore(el, list.firstChild);
            
            const count = parseInt(document.getElementById('trades-count').textContent);
            document.getElementById('trades-count').textContent = count + 1;
        }
        
        function renderTrades(trades) {
            const list = document.getElementById('trades-list');
            if (!trades.length) {
                list.innerHTML = '<div class="empty-state">No trades executed</div>';
                return;
            }
            
            list.innerHTML = '';
            trades.forEach(t => list.appendChild(createTradeElement(t)));
        }
        
        function renderPositions(positions) {
            const list = document.getElementById('positions-list');
            const count = positions.length;
            document.getElementById('positions-count').textContent = count;

            // バッジにトータル含み損益も表示
            const totalPnl = positions.reduce((s, p) => s + (p.unrealized_pnl || 0), 0);
            const pnlStr = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2);
            document.getElementById('positions-badge').textContent =
                count + ' position' + (count !== 1 ? 's' : '') +
                (count > 0 ? '  ·  ' + pnlStr : '');

            if (!count) {
                list.innerHTML = '<div class="empty-state">No open positions</div>';
                return;
            }
            list.innerHTML = '';
            positions.forEach(p => list.appendChild(createPositionElement(p)));
        }

        function createPositionElement(pos) {
            const div = document.createElement('div');

            const pnl    = pos.unrealized_pnl     || 0;
            const pnlPct = pos.unrealized_pnl_pct || 0;
            const isWin  = pnl >  0.005;
            const isLoss = pnl < -0.005;
            div.className = 'position-item ' + (isWin ? 'pos-winning' : isLoss ? 'pos-losing' : 'pos-neutral');

            const pnlClass = isWin ? 'pnl-win' : isLoss ? 'pnl-loss' : 'pnl-flat';
            const pnlSign  = pnl >= 0 ? '+' : '';

            const sideUpper  = (pos.side || '').toUpperCase();
            const isBuyYes   = sideUpper.includes('YES');
            const sideClass  = isBuyYes ? 'pos-side-yes' : 'pos-side-no';
            const sideLabel  = isBuyYes ? 'BUY YES' : 'BUY NO';

            // Entry → Current 方向矢印
            const diff = (pos.current_price || 0) - (pos.entry_price || 0);
            const arrowClass = diff >  0.002 ? 'pos-arrow-up'
                             : diff < -0.002 ? 'pos-arrow-down'
                             : 'pos-arrow-flat';
            const arrowChar  = diff >  0.002 ? '▲' : diff < -0.002 ? '▼' : '→';

            // 保有時間
            let duration = '';
            if (pos.created_at) {
                const ms = Date.now() - new Date(pos.created_at).getTime();
                const h  = Math.floor(ms / 3600000);
                const m  = Math.floor((ms % 3600000) / 60000);
                duration = h > 0 ? `${h}h ${m}m` : `${m}m`;
            }

            // PnL バー幅 (10% = 100%)
            const barW = Math.min(Math.abs(pnlPct) * 500, 100).toFixed(1);

            div.innerHTML = `
                <div class="position-inner">
                    <div class="position-info">
                        <div class="position-question">${pos.question || 'Unknown'}</div>
                        <div class="position-details">
                            <span class="pos-side-badge ${sideClass}">${sideLabel}</span>
                            <span class="pos-price-flow">
                                <span>${((pos.entry_price || 0) * 100).toFixed(1)}%</span>
                                <span class="${arrowClass}">${arrowChar}</span>
                                <span>${((pos.current_price || 0) * 100).toFixed(1)}%</span>
                            </span>
                            <span class="pos-size">$${(pos.size || 0).toFixed(2)}</span>
                            ${duration ? `<span class="pos-duration">${duration}</span>` : ''}
                        </div>
                    </div>
                    <div class="position-pnl-display">
                        <div class="pos-pnl-amount ${pnlClass}">${pnlSign}$${Math.abs(pnl).toFixed(2)}</div>
                        <div class="pos-pnl-pct   ${pnlClass}">${pnlSign}${(pnlPct * 100).toFixed(1)}%</div>
                    </div>
                </div>
                ${(isWin || isLoss) ? `<div class="pos-bar ${isWin ? 'winning' : 'losing'}" style="width:${barW}%"></div>` : ''}
            `;
            return div;
        }

        function createTradeElement(trade) {
            const div = document.createElement('div');
            div.className = `trade-item ${trade.success ? 'trade-success' : 'trade-fail'}`;
            
            div.innerHTML = `
                <div class="signal-header">
                    <span class="signal-question">${trade.question || 'Unknown'}</span>
                    <span class="timestamp">${trade.timestamp ? new Date(trade.timestamp).toLocaleTimeString() : ''}</span>
                </div>
                <div class="signal-meta">
                    <span>${trade.side || 'BUY'} @ ${trade.price?.toFixed(4) || '0'}</span>
                    <span>SIZE $${trade.size?.toFixed(2) || '0'}</span>
                    <span>${trade.success ? '✓ FILLED' : '✗ REJECTED'}</span>
                </div>
            `;
            
            return div;
        }
        
        // Init
        initChart();
        connect();
        
        // Ping every 30s
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 30000);
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
