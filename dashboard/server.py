"""
Dashboard Server
- FastAPI + WebSocket
- リアルタイム取引可視化
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
            "markets": [],
            "prices": {"BTC": 0, "ETH": 0},
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
        await self.manager.broadcast({
            "type": "update",
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
        })
    
    async def push_signal(self, signal: dict):
        """シグナル追加"""
        self.state["recent_signals"].insert(0, {
            **signal,
            "timestamp": datetime.now().isoformat(),
        })
        self.state["recent_signals"] = self.state["recent_signals"][:20]
        
        await self.manager.broadcast({
            "type": "signal",
            "data": signal,
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
        # 既存を更新または追加
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
    
    def _get_dashboard_html(self) -> str:
        """ダッシュボードHTML"""
        return '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Poly AI Trader Dashboard</title>
    <style>
        :root {
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-blue: #58a6ff;
            --accent-yellow: #d29922;
            --border: #30363d;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
        }
        
        .logo {
            font-size: 1.5em;
            font-weight: 700;
        }
        
        .logo span {
            color: var(--accent-blue);
        }
        
        .status-badge {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
        }
        
        .status-running { background: var(--accent-green); color: #000; }
        .status-idle { background: var(--bg-tertiary); }
        .status-error { background: var(--accent-red); }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .stat-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        
        .stat-label {
            color: var(--text-secondary);
            font-size: 0.85em;
            margin-bottom: 8px;
        }
        
        .stat-value {
            font-size: 1.8em;
            font-weight: 700;
        }
        
        .stat-value.positive { color: var(--accent-green); }
        .stat-value.negative { color: var(--accent-red); }
        
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        @media (max-width: 900px) {
            .main-grid { grid-template-columns: 1fr; }
        }
        
        .panel {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }
        
        .panel-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .panel-body {
            padding: 16px 20px;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .signal-item, .trade-item, .trigger-item {
            padding: 12px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            margin-bottom: 8px;
        }
        
        .signal-item:last-child, .trade-item:last-child {
            margin-bottom: 0;
        }
        
        .signal-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        
        .signal-question {
            font-weight: 500;
            color: var(--text-primary);
        }
        
        .signal-action {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
        }
        
        .action-buy { background: var(--accent-green); color: #000; }
        .action-sell { background: var(--accent-red); }
        .action-hold { background: var(--bg-secondary); }
        
        .signal-meta {
            display: flex;
            gap: 16px;
            font-size: 0.85em;
            color: var(--text-secondary);
        }
        
        .edge-positive { color: var(--accent-green); }
        .edge-negative { color: var(--accent-red); }
        
        .trigger-item {
            border-left: 3px solid var(--accent-yellow);
        }
        
        .trigger-price {
            font-family: monospace;
            font-size: 1.1em;
        }
        
        .trade-success { border-left: 3px solid var(--accent-green); }
        .trade-fail { border-left: 3px solid var(--accent-red); }
        
        .price-ticker {
            display: flex;
            gap: 20px;
        }
        
        .price-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .price-symbol {
            color: var(--text-secondary);
        }
        
        .price-value {
            font-family: monospace;
            font-weight: 600;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
        }
        
        .connection-status {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        
        .connected { background: var(--accent-green); }
        .disconnected { background: var(--accent-red); }
        
        .timestamp {
            font-size: 0.75em;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">Poly <span>AI</span> Trader</div>
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
            <div>
                <span class="connection-status disconnected" id="conn-status"></span>
                <span class="status-badge status-idle" id="status-badge">Idle</span>
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
                <div class="stat-label">Trades Today</div>
                <div class="stat-value" id="trades-count">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Triggers</div>
                <div class="stat-value" id="triggers-count">0</div>
            </div>
        </div>
        
        <div class="main-grid">
            <div class="panel">
                <div class="panel-header">
                    <span>📡 Live Signals</span>
                    <span class="timestamp" id="signals-updated"></span>
                </div>
                <div class="panel-body" id="signals-list">
                    <div class="empty-state">Waiting for signals...</div>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-header">
                    <span>⏰ Active Triggers</span>
                </div>
                <div class="panel-body" id="triggers-list">
                    <div class="empty-state">No active triggers</div>
                </div>
            </div>
            
            <div class="panel" style="grid-column: span 2;">
                <div class="panel-header">
                    <span>💰 Trade History</span>
                </div>
                <div class="panel-body" id="trades-list">
                    <div class="empty-state">No trades yet</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let ws;
        let reconnectInterval;
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                console.log('Connected');
                document.getElementById('conn-status').className = 'connection-status connected';
                clearInterval(reconnectInterval);
            };
            
            ws.onclose = () => {
                console.log('Disconnected');
                document.getElementById('conn-status').className = 'connection-status disconnected';
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
            }
        }
        
        function updateAll(state) {
            document.getElementById('balance').textContent = `$${state.balance.toFixed(2)}`;
            updatePnL(state.pnl);
            document.getElementById('trades-count').textContent = state.trades_today;
            document.getElementById('triggers-count').textContent = state.active_triggers.length;
            
            if (state.prices.BTC) {
                document.getElementById('btc-price').textContent = `$${state.prices.BTC.toLocaleString()}`;
            }
            if (state.prices.ETH) {
                document.getElementById('eth-price').textContent = `$${state.prices.ETH.toLocaleString()}`;
            }
            
            // Update status
            const badge = document.getElementById('status-badge');
            badge.textContent = state.status.charAt(0).toUpperCase() + state.status.slice(1);
            badge.className = `status-badge status-${state.status}`;
            
            // Render lists
            renderSignals(state.recent_signals);
            renderTriggers(state.active_triggers);
            renderTrades(state.recent_trades);
        }
        
        function updateField(key, value) {
            switch (key) {
                case 'balance':
                    document.getElementById('balance').textContent = `$${value.toFixed(2)}`;
                    break;
                case 'pnl':
                    updatePnL(value);
                    break;
                case 'trades_today':
                    document.getElementById('trades-count').textContent = value;
                    break;
                case 'status':
                    const badge = document.getElementById('status-badge');
                    badge.textContent = value.charAt(0).toUpperCase() + value.slice(1);
                    badge.className = `status-badge status-${value}`;
                    break;
                case 'prices':
                    if (value.BTC) document.getElementById('btc-price').textContent = `$${value.BTC.toLocaleString()}`;
                    if (value.ETH) document.getElementById('eth-price').textContent = `$${value.ETH.toLocaleString()}`;
                    break;
            }
        }
        
        function updatePnL(value) {
            const el = document.getElementById('pnl');
            el.textContent = `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;
            el.className = `stat-value ${value >= 0 ? 'positive' : 'negative'}`;
        }
        
        function addSignal(signal) {
            const list = document.getElementById('signals-list');
            if (list.querySelector('.empty-state')) {
                list.innerHTML = '';
            }
            
            const el = createSignalElement(signal);
            list.insertBefore(el, list.firstChild);
            
            document.getElementById('signals-updated').textContent = new Date().toLocaleTimeString();
        }
        
        function renderSignals(signals) {
            const list = document.getElementById('signals-list');
            if (!signals.length) {
                list.innerHTML = '<div class="empty-state">Waiting for signals...</div>';
                return;
            }
            
            list.innerHTML = signals.map(s => createSignalElement(s).outerHTML).join('');
        }
        
        function createSignalElement(signal) {
            const div = document.createElement('div');
            div.className = 'signal-item';
            
            const actionClass = signal.action?.includes('buy') ? 'action-buy' : 
                               signal.action?.includes('sell') ? 'action-sell' : 'action-hold';
            const edgeClass = (signal.edge || 0) >= 0 ? 'edge-positive' : 'edge-negative';
            
            div.innerHTML = `
                <div class="signal-header">
                    <span class="signal-question">${signal.question || 'Unknown'}</span>
                    <span class="signal-action ${actionClass}">${signal.action || 'HOLD'}</span>
                </div>
                <div class="signal-meta">
                    <span>Market: ${((signal.market_price || 0) * 100).toFixed(1)}%</span>
                    <span>Pred: ${((signal.predicted_prob || 0) * 100).toFixed(1)}%</span>
                    <span class="${edgeClass}">Edge: ${signal.edge >= 0 ? '+' : ''}${((signal.edge || 0) * 100).toFixed(1)}%</span>
                    <span>Conf: ${((signal.confidence || 0) * 100).toFixed(0)}%</span>
                </div>
            `;
            
            return div;
        }
        
        function updateTrigger(trigger) {
            const list = document.getElementById('triggers-list');
            if (list.querySelector('.empty-state')) {
                list.innerHTML = '';
            }
            
            // Update or add
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
                    <span class="signal-action action-${trigger.side?.toLowerCase() || 'buy'}">${trigger.side || 'BUY'}</span>
                </div>
                <div class="signal-meta">
                    <span class="trigger-price">Target: ${trigger.target_price?.toFixed(4) || '0'}</span>
                    <span>Size: $${trigger.size?.toFixed(2) || '0'}</span>
                </div>
            `;
            
            document.getElementById('triggers-count').textContent = list.children.length;
        }
        
        function removeTrigger(tokenId) {
            const el = document.querySelector(`[data-token="${tokenId}"]`);
            if (el) el.remove();
            
            const list = document.getElementById('triggers-list');
            if (!list.children.length) {
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
            if (list.querySelector('.empty-state')) {
                list.innerHTML = '';
            }
            
            const el = createTradeElement(trade);
            list.insertBefore(el, list.firstChild);
            
            // Update count
            const count = parseInt(document.getElementById('trades-count').textContent);
            document.getElementById('trades-count').textContent = count + 1;
        }
        
        function renderTrades(trades) {
            const list = document.getElementById('trades-list');
            if (!trades.length) {
                list.innerHTML = '<div class="empty-state">No trades yet</div>';
                return;
            }
            
            list.innerHTML = trades.map(t => createTradeElement(t).outerHTML).join('');
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
                    <span>Size: $${trade.size?.toFixed(2) || '0'}</span>
                    <span>${trade.success ? '✅ Success' : '❌ Failed'}</span>
                </div>
            `;
            
            return div;
        }
        
        // Start connection
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
