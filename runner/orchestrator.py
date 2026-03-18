"""
Orchestrator - フル統合ランナー

3層アーキテクチャ:
- リアルタイム層: WebSocket監視 + 即時売買
- 分析層: LLM + ML + Orderflow + Bayesian (可変間隔)
- 学習層: Factor Miner + Auto-Killer (バックグラウンド)
"""
import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Set
from enum import Enum

from scanner import MarketScanner
from analyst import EnsembleAnalyst
from executor import TradeExecutor
from risk import RiskManager, Auditor
from data_fetcher import PolyWebSocket, GoogleNewsFetcher, NewsFetcher, PriceHistoryFetcher
from factor import FactorManager
from tracker import PositionTracker

# Dashboard (optional)
try:
    from dashboard import DashboardServer
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False


class RunMode(Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


def _order_status(order) -> Optional[str]:
    """py-clob-client の注文オブジェクト(dict or object)からステータス文字列を取得"""
    if order is None:
        return None
    if isinstance(order, dict):
        return order.get("status")
    return getattr(order, "status", None)


@dataclass
class TriggerCondition:
    """売買トリガー条件"""
    market_id: str
    token_id: str           # 実際に売買するトークン (BUY_NO なら NO token)
    watch_token_id: str     # 価格監視用トークン (常に YES token)
    question: str
    side: str  # "BUY_YES" / "BUY_NO" / "SELL_YES" / "SELL_NO"
    target_price: float  # この価格条件で発火 (YES価格ベース)
    size: float
    signal_confidence: float
    signal_probability: float = 0.5  # シグナル生成時のモデル確率推定 (発火時エッジ再検証用)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def should_execute(self, current_price: float) -> bool:
        if self.is_expired():
            return False
        # BUY_YES: YES価格が下がったら買い
        # BUY_NO: YES価格が上がったら買い (NO が安くなる)
        # SELL_YES: YES価格が上がったら売り
        # SELL_NO: YES価格が下がったら売り
        side = self.side.upper()
        if side == "BUY_YES":
            return current_price <= self.target_price
        elif side == "BUY_NO":
            return current_price >= self.target_price
        elif side == "SELL_YES":
            return current_price >= self.target_price
        else:  # SELL_NO
            return current_price <= self.target_price


@dataclass
class OrchestratorConfig:
    """設定"""
    # 分析
    llm_model: str = "claude-haiku-4-5-20251001"
    min_edge: float = 0.05
    min_confidence: float = 0.50
    max_markets: int = 10

    # マーケット品質フィルター
    min_liquidity: float = 5_000    # 最低流動性 $5k
    min_volume: float = 10_000      # 最低出来高 $10k
    
    # 実行
    mode: RunMode = RunMode.DRY_RUN
    max_trades_per_cycle: int = 3
    trigger_expiry_minutes: int = 30
    
    # リスク
    max_position_pct: float = 0.10
    max_drawdown_pct: float = 0.15
    
    # 利確・損切り
    enable_exit: bool = False       # 早期クローズ機能
    take_profit_pct: float = 0.50   # 50% で利確
    stop_loss_pct: float = -0.50    # -50% で損切り
    
    # ニュース
    fetch_news: bool = True
    news_limit: int = 5

    # ダッシュボード
    dashboard: bool = False
    dashboard_port: int = 8080

    # ML自動再学習
    auto_retrain: bool = True           # 自動再学習を有効化
    retrain_threshold: int = 20         # 何マーケット解決ごとに再学習するか


class Orchestrator:
    """統合オーケストレーター"""
    
    def __init__(self, config: OrchestratorConfig = None):
        self.config = config or OrchestratorConfig()
        
        # コンポーネント
        self.scanner = MarketScanner()
        # ML モデルパス
        ml_model_path = Path(__file__).parent.parent / "models" / "lgb_model.pkl"
        use_ml = ml_model_path.exists()
        
        # Ensemble Analyst
        self.analyst = EnsembleAnalyst(
            llm_model=self.config.llm_model,
            ml_model_path=str(ml_model_path) if use_ml else None,
            use_ml=use_ml,
            use_orderflow=True,  # WebSocket から取引データ収集
        )
        self.executor = TradeExecutor(
            dry_run=(self.config.mode == RunMode.DRY_RUN),
            use_risk_manager=False,  # オーケストレーターが一元管理するため無効化
        )
        self.risk_manager = RiskManager()
        self.auditor = Auditor()
        self.factor_manager = FactorManager()
        self.position_tracker = PositionTracker()
        
        # Price History Fetcher
        self.price_fetcher = PriceHistoryFetcher()
        
        # Google News RSS (高速・安定)
        self.news_fetcher = GoogleNewsFetcher()
        
        # 取引履歴キャッシュ (Orderflow用)
        self.trade_cache: Dict[str, List] = {}

        # BTC/ETH価格キャッシュ (スキャン時に更新)
        self._btc_price: Optional[float] = None
        self._eth_price: Optional[float] = None

        # ダッシュボード
        self.dashboard = None
        if self.config.dashboard and DASHBOARD_AVAILABLE:
            self.dashboard = DashboardServer(port=self.config.dashboard_port)
        
        # WebSocket
        self.websocket: Optional[PolyWebSocket] = None
        
        # トリガー管理
        self.active_triggers: Dict[str, TriggerCondition] = {}
        # 再起動後もポジション重複を防ぐため、既存のオープンポジションを読み込む
        self.executed_markets: Set[str] = set(self.position_tracker.get_open_market_ids())
        
        # 状態
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._analysis_task: Optional[asyncio.Task] = None

        # ML再学習管理
        self._resolved_since_last_training: int = 0
        self._retraining: bool = False

        # 構造化ログ (data/trade_log.jsonl)
        _log_dir = Path(__file__).parent.parent / "data"
        _log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = _log_dir / "trade_log.jsonl"

        # サイクルごとのトリガー設定数 (max_trades_per_cycle 上限管理)
        self._triggers_this_cycle: int = 0

        # 統計
        self.stats = {
            "cycles": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "trades_success": 0,
        }
    
    # ========== メインループ ==========
    
    async def start(self):
        """オーケストレーター開始"""
        self._running = True
        
        print("🚀 Poly AI Trader 起動")
        print(f"   モード: {self.config.mode.value}")
        print(f"   モデル: {self.config.llm_model}")
        print(f"   最小エッジ: {self.config.min_edge:.0%}")
        
        # ダッシュボード起動
        dashboard_task = None
        if self.dashboard:
            print(f"   📊 Dashboard: http://localhost:{self.config.dashboard_port}")
            dashboard_task = asyncio.create_task(self.dashboard.run_async())
            await self.dashboard.update_state("status", "running")
        
        print("\nCtrl+C で停止\n")
        
        try:
            # 残高取得 (認証モードでCLOBから正確な残高を取得)
            from client import PolyClient
            try:
                poly_client = PolyClient()
                poly_client.connect()  # 認証あり → CLOB残高を取得
                balance = poly_client.get_balance()
                print(f"💰 残高: ${balance:.2f} USDC")
                
                # RiskManager に残高設定
                self.risk_manager.update_balance(balance)
                
                if self.dashboard:
                    await self.dashboard.update_state("balance", balance)
            except Exception as e:
                print(f"⚠️ 残高取得失敗: {e}")
            
            # 既存オープンポジションを RiskManager に復元 (再起動後のエクスポージャー誤認防止)
            open_positions = self.position_tracker.get_open_positions()
            if open_positions:
                for pos in open_positions:
                    self.risk_manager.open_positions[pos.market_id] = {
                        "symbol": pos.question[:30],
                        "amount": pos.size,
                    }
                total_restored = sum(p.size for p in open_positions)
                print(f"📂 既存ポジション復元: {len(open_positions)}件 ${total_restored:.2f} → エクスポージャー {self.risk_manager.get_exposure_ratio():.0%}")

            # 初回スキャン
            markets = await self._scan_markets()
            
            if not markets:
                print("❌ マーケットが見つかりません")
                return
            
            # WebSocket起動 (バックグラウンド)
            self._ws_task = asyncio.create_task(
                self._websocket_monitor(markets)
            )
            
            # 分析ループ起動
            self._analysis_task = asyncio.create_task(
                self._analysis_loop(markets)
            )
            
            # タスクを待機
            tasks = [self._ws_task, self._analysis_task]
            if dashboard_task:
                tasks.append(dashboard_task)
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except KeyboardInterrupt:
            print("\n\n👋 停止中...")
        finally:
            await self.stop()
    
    async def stop(self):
        """停止"""
        self._running = False
        
        if self._ws_task:
            self._ws_task.cancel()
        if self._analysis_task:
            self._analysis_task.cancel()
        if self.websocket:
            await self.websocket.disconnect()
        
        # PnL計算
        tracker_stats = self.position_tracker.get_stats()
        
        print(f"\n📊 最終統計:")
        print(f"   サイクル: {self.stats['cycles']}")
        print(f"   シグナル: {self.stats['signals_generated']}")
        print(f"   取引: {self.stats['trades_executed']} (成功: {self.stats['trades_success']})")
        print(f"   オープン: {tracker_stats['open']} ポジション")
        print(f"   総PnL: ${tracker_stats['total_pnl']:+.2f}")
    
    # ========== スキャン ==========
    
    async def _scan_markets(self) -> List:
        """マーケットスキャン"""
        print("🔍 マーケットスキャン中...")
        result = await self.scanner.scan(
            min_liquidity=self.config.min_liquidity,
            min_volume=self.config.min_volume,
        )

        # BTC/ETH価格をキャッシュ
        if result.btc_price:
            self._btc_price = result.btc_price.price
        if result.eth_price:
            self._eth_price = result.eth_price.price

        markets = result.markets[:self.config.max_markets]
        print(f"   {len(markets)} マーケット検出")

        return markets
    
    # ========== WebSocket監視 ==========
    
    async def _websocket_monitor(self, markets: List):
        """WebSocketでリアルタイム監視"""
        # トークンID収集
        token_ids = []
        token_to_market = {}
        
        for m in markets:
            if hasattr(m, 'yes_token_id') and m.yes_token_id:
                token_ids.append(m.yes_token_id)
                token_to_market[m.yes_token_id] = m
        
        if not token_ids:
            print("⚠️ WebSocket: トークンIDなし")
            return
        
        print(f"📡 WebSocket接続中... ({len(token_ids)} トークン)")
        
        self.websocket = PolyWebSocket()
        
        # 価格更新コールバック
        async def on_price(update):
            await self._check_triggers(update.asset_id, update.price)
        
        # 取引コールバック (Orderflow用)
        async def on_trade(update):
            token_id = update.asset_id
            if token_id not in self.trade_cache:
                self.trade_cache[token_id] = []
            
            # Trade オブジェクトを作成
            from analyst.orderflow import Trade
            trade = Trade(
                timestamp=update.timestamp,
                price=update.price,
                size=update.size,
                side=update.side,
            )
            self.trade_cache[token_id].append(trade)
            
            # 最新1000件のみ保持
            if len(self.trade_cache[token_id]) > 1000:
                self.trade_cache[token_id] = self.trade_cache[token_id][-1000:]
        
        self.websocket.on_price(on_price)
        self.websocket.on_trade(on_trade)
        
        # 接続
        try:
            await self.websocket.connect(token_ids)
        except Exception as e:
            print(f"❌ WebSocketエラー: {e}")
    
    async def _check_triggers(self, token_id: str, price: float):
        """トリガー条件チェック"""
        trigger = self.active_triggers.get(token_id)
        
        if not trigger:
            return
        
        if trigger.should_execute(price):
            print(f"\n⚡ トリガー発火!")
            print(f"   {trigger.question[:40]}")
            print(f"   価格: {price:.4f} (条件: {trigger.target_price:.4f})")
            
            await self._execute_trigger(trigger, price)
    
    async def _execute_trigger(self, trigger: TriggerCondition, price: float):
        """トリガー実行"""
        # 既に実行済みならスキップ
        if trigger.market_id in self.executed_markets:
            return

        # ─── 発火時エッジ再検証 ────────────────────────────────────────────
        # シグナル生成後に相場が動いてエッジが消滅していないかをチェック。
        # BUY_YES: モデルが YES を過小評価と判断 → edge = signal_prob - current_price
        # BUY_NO : モデルが NO を過小評価と判断 → edge = current_price - signal_prob
        #           (YES が高い = NO が安い ほどエッジが大きい)
        # SELL系 : ポジション決済なので常に通す
        if trigger.side.upper() in ("BUY_YES", "BUY_NO"):
            if trigger.side.upper() == "BUY_YES":
                current_edge = trigger.signal_probability - price
            else:
                current_edge = price - trigger.signal_probability

            min_viable_edge = self.config.min_edge * 0.5  # シグナル閾値の50%まで許容
            print(f"   🔎 エッジ再検証: {trigger.side} signal_prob={trigger.signal_probability:.4f} "
                  f"price={price:.4f} edge={current_edge:+.3f} (閾値>{min_viable_edge:.3f})")
            if current_edge < min_viable_edge:
                print(f"   ⚪ 発火キャンセル: エッジ消滅 (現在エッジ {current_edge:+.1%} < 閾値 {min_viable_edge:.1%})")
                self._log_event("trigger_cancelled", {
                    "market_id": trigger.market_id,
                    "question": trigger.question[:60],
                    "side": trigger.side,
                    "signal_probability": round(trigger.signal_probability, 6),
                    "current_price": round(price, 6),
                    "current_edge": round(current_edge, 6),
                    "min_viable_edge": round(min_viable_edge, 6),
                })
                del self.active_triggers[trigger.watch_token_id]
                self.risk_manager.remove_pending_exposure(trigger.size)
                return
        # ─────────────────────────────────────────────────────────────────────

        try:
            # 実行
            result = await self.executor.execute_order(
                market_id=trigger.market_id,
                token_id=trigger.token_id,
                side=trigger.side,
                size=trigger.size,
                price=price,
            )
            
            self.stats["trades_executed"] += 1
            
            if result.success:
                self.stats["trades_success"] += 1
                print(f"   ✅ 約定: {result.message}")
                self.executed_markets.add(trigger.market_id)

                # 約定ログ (スリッページ = 発火価格 - シグナル時価格)
                slippage = price - trigger.target_price
                time_to_fire = (
                    datetime.now(timezone.utc) - trigger.created_at
                ).total_seconds()
                self._log_event("trigger_fired", {
                    "market_id": trigger.market_id,
                    "question": trigger.question[:60],
                    "side": trigger.side,
                    "target_price": round(trigger.target_price, 6),
                    "executed_price": round(price, 6),
                    "slippage": round(slippage, 6),
                    "slippage_pct": round(slippage / trigger.target_price, 6) if trigger.target_price else 0,
                    "size": round(trigger.size, 2),
                    "time_to_fire_sec": round(time_to_fire, 1),
                    "success": True,
                })
                
                # エクスポージャー: ペンディング → オープン
                self.risk_manager.convert_pending_to_open(
                    trigger.market_id, trigger.size, trigger.question[:30]
                )
                
                # 実際の約定価格 (CLOB ask/bid に更新済みの場合はそちらを使う)
                # position_tracker は entry_price を常に YES価格として扱う。
                # execute() は BUY_NO の executed_price を NO価格で返すので YES換算する。
                entry_price = result.executed_price if result.executed_price is not None else price
                if "NO" in trigger.side.upper() and result.executed_price is not None:
                    entry_price = 1.0 - result.executed_price  # NO価格 → YES換算

                # ポジション記録 (GTC注文はorder_id保存・未約定フラグ付き)
                self.position_tracker.record_trade(
                    market_id=trigger.market_id,
                    token_id=trigger.token_id,
                    yes_token_id=trigger.watch_token_id,  # 常にYES token (価格表示用)
                    question=trigger.question,
                    side=trigger.side,
                    entry_price=entry_price,
                    size=trigger.size,
                    order_id=result.order_id,
                    order_filled=False,  # GTC: 注文受理=未約定、後続チェックで確認
                )

                # ファクター記録 (アクティブファクターがあれば)
                active_factors = self.factor_manager.get_active_factors()
                if active_factors:
                    factor = active_factors[0]
                    self.factor_manager.record_trade(
                        factor_id=factor.hypothesis.id,
                        pnl=0,           # 解決後に update_pnl_by_market() で更新
                        entry_price=entry_price,
                        market_id=trigger.market_id,
                    )

                # 50トレードごとに新ファクターを生成 (学習層)
                if self.stats["trades_success"] % 50 == 0:
                    asyncio.create_task(self._mine_new_factor())
            else:
                print(f"   ❌ 失敗: {result.message}")
                self._log_event("trigger_fired", {
                    "market_id": trigger.market_id,
                    "question": trigger.question[:60],
                    "side": trigger.side,
                    "executed_price": round(price, 6),
                    "size": round(trigger.size, 2),
                    "success": False,
                    "error": result.message,
                })
                # 失敗時はペンディングを解放
                self.risk_manager.remove_pending_exposure(trigger.size)
            
            # ダッシュボード更新
            if self.dashboard:
                await self.dashboard.push_trade({
                    "question": trigger.question[:50],
                    "side": trigger.side,
                    "price": price,
                    "size": trigger.size,
                    "success": result.success,
                })
                await self.dashboard.remove_trigger(trigger.watch_token_id)
            
            # トリガー削除 (watch_token_id で管理)
            del self.active_triggers[trigger.watch_token_id]
            
        except Exception as e:
            print(f"   ❌ 実行エラー: {e}")
    
    # ========== 分析ループ ==========
    
    async def _analysis_loop(self, markets: List):
        """分析ループ (可変間隔)"""
        while self._running:
            try:
                self.stats["cycles"] += 1
                print(f"\n{'='*60}")
                print(f"📊 サイクル #{self.stats['cycles']} - {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")

                # サイクルごとに CLOB から実残高を再取得してリスク管理に反映
                try:
                    from client import PolyClient
                    _pc = PolyClient()
                    _pc.connect()
                    _balance = _pc.get_balance()
                    if _balance > 0:
                        self.risk_manager.update_balance(_balance)
                        if self.dashboard:
                            await self.dashboard.update_state("balance", _balance)
                        print(f"💰 残高更新: ${_balance:.2f} USDC")
                except Exception as _e:
                    pass  # 取得失敗時は前回値を継続使用

                # マーケット再スキャン (10サイクルごと)
                if self.stats["cycles"] % 10 == 0:
                    markets = await self._scan_markets()
                
                # 各マーケットを分析 (エクスポージャー上限はRiskManagerが管理)
                self._triggers_this_cycle = 0
                for market in markets:
                    if not self._running:
                        break
                    await self._analyze_market(market)
                
                # GTC未約定注文のチェック・自動キャンセル
                await self._check_pending_gtc_orders()

                # 解決済みマーケットをチェック
                await self._check_resolved_markets()
                
                # 利確・損切りチェック
                await self._check_position_exits(markets)

                # ダッシュボードにポジション一覧を送信
                if self.dashboard:
                    await self._push_positions_to_dashboard(markets)

                # 期限切れトリガーをクリーンアップ
                await self._cleanup_expired_triggers()
                
                # ダッシュボードにPnL更新
                if self.dashboard:
                    stats = self.position_tracker.get_stats()
                    await self.dashboard.update_state("pnl", stats["total_pnl"])
                
                # 次の間隔を決定
                interval = self._get_analysis_interval(markets)
                print(f"\n⏳ 次回分析: {interval}分後...")
                
                await asyncio.sleep(interval * 60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ 分析エラー: {e}")
                await asyncio.sleep(60)
    
    async def _analyze_market(self, market):
        """単一マーケット分析"""
        # 既に実行済みならスキップ
        market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', str(id(market)))
        if market_id in self.executed_markets:
            return
        
        # 既存トリガーをチェック (後で比較用)
        token_id = getattr(market, 'yes_token_id', None)
        existing_trigger = self.active_triggers.get(token_id) if token_id else None
        
        question = getattr(market, 'question', str(market))

        # 15%未満・85%超の長射程マーケットはスキップ (学習データと一致させる)
        yes_price_now = getattr(market, 'yes_price', 0.5)
        if yes_price_now <= 0.15 or yes_price_now >= 0.85:
            print(f"   ⏭️ スキップ (価格範囲外 {yes_price_now:.0%}): {question[:40]}")
            return

        # end_date なし (before GTA VI 等) または1時間未満・30日超はスキップ (資金長期ロック防止)
        end_date = getattr(market, 'end_date', None)
        if not end_date:
            print(f"   ⏭️ スキップ (end_dateなし): {question[:40]}")
            return
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        days_left = (end_date - datetime.now(timezone.utc)).total_seconds() / 86400
        if days_left < (1 / 24) or days_left > 30:
            print(f"   ⏭️ スキップ (期限 {days_left:.1f}日): {question[:40]}")
            return

        # エクスポージャー上限チェック (既存トリガーがない新規マーケットはLLM分析をスキップ)
        if not existing_trigger:
            if not self.risk_manager.can_add_position(self.risk_manager.min_position * 3):
                exposure_ratio = self.risk_manager.get_exposure_ratio()
                print(f"   ⏭️ スキップ (エクスポージャー上限 {exposure_ratio:.0%}/{self.risk_manager.max_total_exposure:.0%}): {question[:40]}")
                return

        print(f"\n🧠 分析: {question[:50]}...")

        try:
            # ニュース取得
            news_context = ""
            if self.config.fetch_news:
                articles = await self.news_fetcher.search(
                    question,
                    limit=self.config.news_limit,
                )
                if articles:
                    lines = []
                    for a in articles[:5]:
                        line = f"- {a.title}"
                        if a.summary:
                            line += f"\n  {a.summary[:300]}"
                        lines.append(line)
                    news_context = "\n".join(lines)
            
            # 価格履歴取得 (Orderflow/ML用)
            prices = []
            trades = []
            if token_id:
                try:
                    price_points = await self.price_fetcher.fetch_prices(
                        token_id=token_id,
                        interval="1d",  # 直近1日
                        fidelity=5,     # 5分足
                    )
                    prices = [p.price for p in price_points[-100:]]  # 最新100点
                    
                    # 取引履歴 (WebSocketから収集済みのもの)
                    trades = self.trade_cache.get(token_id, [])
                except Exception as e:
                    pass  # 価格取得失敗は無視
            
            # 流動性スナップショット (Orderflow分析用)
            if self.analyst.use_orderflow and self.analyst.orderflow_detector:
                market_liquidity = getattr(market, "liquidity", 0)
                if market_liquidity > 0:
                    self.analyst.orderflow_detector.add_liquidity_snapshot(
                        timestamp=datetime.now(timezone.utc),
                        total_liquidity=market_liquidity,
                    )

            # 前回LLM判断を読み込み (トリガー設定済みマーケットの再分析時に使用)
            previous_judgment = self._load_llm_judgment(token_id) if token_id else None

            # 分析
            signal = await self.analyst.analyze(
                market=market,
                prices=prices,
                trades=trades,
                btc_price=self._btc_price,
                news_context=news_context,
                previous_judgment=previous_judgment,
            )
            
            if not signal:
                print(f"   ⚪ シグナルなし")
                return
            
            self.stats["signals_generated"] += 1
            
            print(f"   予測: {signal.final_probability:.1%} | エッジ: {signal.edge:+.1%}")
            
            # ダッシュボード更新
            if self.dashboard:
                await self.dashboard.push_signal({
                    "question": question[:50],
                    "action": signal.action.value,
                    "market_price": getattr(market, 'yes_price', 0),
                    "predicted_prob": signal.final_probability,
                    "edge": signal.edge,
                    "confidence": signal.confidence,
                })
            
            # Auditorチェック
            audit_result = self.auditor.audit(
                market_id=getattr(market, 'market_id', ''),
                question=question,
                liquidity=getattr(market, 'liquidity', 0),
                end_date=getattr(market, 'end_date', None),
                llm_reasoning=signal.llm_reasoning,
                original_confidence=signal.confidence,
            )
            
            if not audit_result.passed:
                flags_str = ", ".join([f.value for f in audit_result.flags]) if audit_result.flags else "unknown"
                print(f"   🚫 ブロック: {flags_str}")
                return
            
            # 信頼度調整
            adjusted_confidence = audit_result.adjusted_confidence
            
            # 最小条件チェック
            if abs(signal.edge) < self.config.min_edge:
                print(f"   ⚪ エッジ不足 ({signal.edge:.1%}, 閾値: ±{self.config.min_edge:.0%})")
                if existing_trigger:
                    print(f"   🗑️ 既存トリガーキャンセル (エッジ消滅): {existing_trigger.side}")
                    self.risk_manager.remove_pending_exposure(existing_trigger.size)
                    del self.active_triggers[existing_trigger.watch_token_id]
                return

            if adjusted_confidence < self.config.min_confidence:
                print(f"   ⚪ 信頼度不足 ({adjusted_confidence:.0%})")
                # 方向が逆転していたらキャンセル、同方向なら維持
                if existing_trigger:
                    if existing_trigger.side != signal.action.value:
                        print(f"   🗑️ 既存トリガーキャンセル (方向逆転): {existing_trigger.side} → {signal.action.value}")
                        self.risk_manager.remove_pending_exposure(existing_trigger.size)
                        del self.active_triggers[existing_trigger.watch_token_id]
                    else:
                        print(f"   ⏸️ 既存トリガー維持中: {existing_trigger.side} @ {existing_trigger.target_price:.4f}")
                return
            
            # シグナルをログ
            self._log_event("signal_generated", {
                "market_id": getattr(market, "condition_id", ""),
                "question": question[:60],
                "action": signal.action.value,
                "market_price": getattr(market, "yes_price", 0),
                "predicted_prob": round(signal.final_probability, 4),
                "edge": round(signal.edge, 4),
                "confidence": round(adjusted_confidence, 4),
            })

            # ポジションサイズ計算
            market_price = getattr(market, 'yes_price', 0.5)
            position_result = self.risk_manager.calculate_position_size(
                edge=signal.edge,
                confidence=adjusted_confidence,
                market_price=market_price,
            )
            size = position_result.amount
            
            # トリガー設定
            await self._set_trigger(market, signal, size)
            
        except Exception as e:
            print(f"   ❌ エラー: {e}")
    
    async def _set_trigger(self, market, signal, size: float):
        """トリガー条件を設定"""
        # BUY_YES/SELL_YES は YES token、BUY_NO/SELL_NO は NO token
        if signal.action.value.upper() in ("BUY_YES", "SELL_YES"):
            token_id = getattr(market, 'yes_token_id', None)
        else:
            token_id = getattr(market, 'no_token_id', None) or getattr(market, 'yes_token_id', None)
        
        # 価格監視用のYESトークンID (常にYES価格で判定)
        watch_token_id = getattr(market, 'yes_token_id', None)
        if not watch_token_id:
            return
        
        market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', str(id(market)))
        question = getattr(market, 'question', str(market))

        # 既存トリガーをチェック (watch_token_id で管理)
        existing_trigger = self.active_triggers.get(watch_token_id)
        if existing_trigger:
            # 同じ方向なら維持
            if existing_trigger.side == signal.action.value:
                print(f"   ⏸️ トリガー維持中: {existing_trigger.side}")
                return
            
            # 反対方向 → 古いトリガーを削除
            print(f"   🔄 予測反転: {existing_trigger.side} → {signal.action.value}")
            self.risk_manager.remove_pending_exposure(existing_trigger.size)
            del self.active_triggers[watch_token_id]
        
        # 目標価格: 現在価格をそのまま使用
        # Polymarketはイベントドリブン。待機中にエッジが消えるリスクが高いため
        # 1%オフセットは設けず、シグナル生成時点の価格で即時発火を狙う
        current_price = getattr(market, 'yes_price', 0.5)
        target_price = current_price
        
        # トリガー有効期限: 分析間隔の1.5倍 (最低 trigger_expiry_minutes)
        # 解決まで7日あるマーケットは分析間隔が240分 → 期限360分にする
        _analysis_interval_min = self._get_analysis_interval([market])
        _trigger_expiry_minutes = max(
            self.config.trigger_expiry_minutes,
            int(_analysis_interval_min * 1.5),
        )

        # エクスポージャーチェック
        if not self.risk_manager.can_add_position(size):
            exposure_ratio = self.risk_manager.get_exposure_ratio()
            print(f"   ⚠️ エクスポージャー上限 ({exposure_ratio:.0%} / {self.risk_manager.max_total_exposure:.0%})")
            return
        
        trigger = TriggerCondition(
            market_id=market_id,
            token_id=token_id,           # 実際に売買するトークン
            watch_token_id=watch_token_id,  # 価格監視用 (YES token)
            question=question,
            side=signal.action.value,
            target_price=target_price,
            size=size,
            signal_confidence=signal.confidence,
            signal_probability=signal.final_probability,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=_trigger_expiry_minutes),
        )
        
        # YES token で監視 (WebSocket は YES 価格を送ってくる)
        self.active_triggers[watch_token_id] = trigger

        # LLM判断をキャッシュ (次サイクルのエッジ再検証時に使用)
        self._save_llm_judgment(token_id, signal)

        # ペンディングエクスポージャーに追加
        self.risk_manager.add_pending_exposure(size)

        # サイクル内トリガー数をカウント
        self._triggers_this_cycle += 1

        self._log_event("trigger_set", {
            "market_id": market_id,
            "question": question[:60],
            "side": signal.action.value,
            "target_price": round(target_price, 6),
            "size": round(size, 2),
            "expiry_minutes": _trigger_expiry_minutes,
        })

        print(f"   ⏰ トリガー設定: {signal.action.value} @ {target_price:.4f}")
        print(f"      サイズ: ${size:.2f} | 有効期限: {_trigger_expiry_minutes}分")
        
        # ダッシュボード更新
        if self.dashboard:
            await self.dashboard.push_trigger({
                "token_id": token_id,
                "question": question[:50],
                "side": signal.action.value,
                "target_price": target_price,
                "size": size,
            })
    
    async def _check_pending_gtc_orders(self):
        """GTC未約定注文の状態確認・60分超でキャンセル"""
        pending = self.position_tracker.get_pending_positions()
        if not pending:
            return

        from client import PolyClient
        try:
            client = PolyClient()
            client.connect()
        except Exception:
            return

        now = datetime.now(timezone.utc)
        gtc_cancel_minutes = 60

        # アクティブな注文IDセット (オープン注文一覧から取得)
        # CLOBは約定済み注文をリストから除外するため、不在 = 約定 or キャンセル
        try:
            active_orders = client.get_orders() or []
            active_ids: Optional[set] = set()
            for o in active_orders:
                oid = o.get("id") if isinstance(o, dict) else getattr(o, "id", None)
                if oid:
                    active_ids.add(oid)
        except Exception:
            active_ids = None  # 取得失敗時は個別確認にフォールバック

        for pos in pending:
            if not pos.order_id:
                self.position_tracker.mark_order_filled(pos.id)
                continue

            # アクティブ注文リストにない → 約定かキャンセル
            if active_ids is not None and pos.order_id not in active_ids:
                # 個別取得で区別を試みる
                order = client.get_order(pos.order_id)
                status = _order_status(order)
                if status in ("MATCHED", "FILLED") or status is None:
                    self.position_tracker.mark_order_filled(pos.id)
                    print(f"   ✅ GTC約定確認 (active_ids): {pos.question[:40]}")
                elif status == "CANCELLED":
                    self.position_tracker.remove_position(pos.id)
                    if pos.market_id in self.risk_manager.open_positions:
                        del self.risk_manager.open_positions[pos.market_id]
                    self.executed_markets.discard(pos.market_id)
                    print(f"   🗑️ GTC外部キャンセル検出: {pos.question[:40]}")
                continue

            # 個別にステータスを確認 (active_ids が取れなかった場合 or まだLIVE)
            order = client.get_order(pos.order_id)
            if order is None:
                # 見つからない → 約定済みと判断
                self.position_tracker.mark_order_filled(pos.id)
                print(f"   ✅ GTC約定確認 (order not found): {pos.question[:40]}")
                continue

            order_status = _order_status(order)

            if order_status in ("MATCHED", "FILLED"):
                self.position_tracker.mark_order_filled(pos.id)
                print(f"   ✅ GTC約定確認: {pos.question[:40]}")

            elif order_status == "CANCELLED":
                self.position_tracker.remove_position(pos.id)
                if pos.market_id in self.risk_manager.open_positions:
                    del self.risk_manager.open_positions[pos.market_id]
                self.executed_markets.discard(pos.market_id)
                print(f"   🗑️ GTC外部キャンセル検出: {pos.question[:40]}")

            elif order_status == "LIVE":
                # 未約定 → 経過時間チェック
                created = pos.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                elapsed_min = (now - created).total_seconds() / 60

                if elapsed_min > gtc_cancel_minutes:
                    result = client.cancel_order(pos.order_id)
                    if result.success:
                        self.position_tracker.remove_position(pos.id)
                        if pos.market_id in self.risk_manager.open_positions:
                            del self.risk_manager.open_positions[pos.market_id]
                        self.executed_markets.discard(pos.market_id)
                        print(f"   🗑️ GTC自動キャンセル ({elapsed_min:.0f}分経過): {pos.question[:40]}")
                    else:
                        print(f"   ⚠️ GTC自動キャンセル失敗: {result.message}")

    async def _check_resolved_markets(self):
        """解決済みマーケットをチェックしてPnL確定・自動クローズ"""
        open_market_ids = self.position_tracker.get_open_market_ids()
        if not open_market_ids:
            return

        try:
            from client import PolyClient
            _pc = PolyClient()

            for market_id in open_market_ids:
                try:
                    # orderbook が存在するポジションは取引中 → 解決チェック不要
                    pos_list = [p for p in self.position_tracker.get_open_positions()
                                if p.market_id == market_id]
                    if pos_list:
                        fetch_tok = pos_list[0].yes_token_id or pos_list[0].token_id
                        mid = _pc.get_midpoint(fetch_tok)
                        if mid is not None:
                            continue  # orderbook あり = まだ取引中

                    # CLOB API でクローズ状態を確認
                    market_data = _pc.get_market(market_id)
                    if not market_data:
                        continue
                    if not market_data.get("closed"):
                        continue  # まだ締め切り前 → 未解決

                    # closed=True → マーケット終了。last trade price で勝敗を判定
                    pos0 = pos_list[0] if pos_list else None
                    resolution = None
                    if pos0:
                        is_no_side = "no" in pos0.side.lower()
                        # BUY_NO: token_id はNOトークン。BUY_YES: yes_token_id はYESトークン
                        check_token = pos0.token_id
                        last_price = _pc.get_last_trade_price(check_token)
                        print(f"   [resolution debug] closed=True last_price={last_price} "
                              f"side={pos0.side} token={check_token[:12]}...")
                        if last_price is not None:
                            if is_no_side:
                                # NOトークン価格: 1.0近い→NO勝ち(resolution=0.0), 0.0近い→YES勝ち(resolution=1.0)
                                resolution = 1.0 - last_price
                            else:
                                # YESトークン価格: 1.0近い→YES勝ち(resolution=1.0)
                                resolution = last_price

                    if resolution is None:
                        continue  # 価格取得失敗 → スキップ

                    outcome_str = "YES" if resolution >= 0.5 else "NO"
                    pnl = self.position_tracker.resolve_by_market(market_id, resolution)

                    print(f"🏁 マーケット解決: {outcome_str}  PnL ${pnl:+.2f}")
                    self.risk_manager.record_close(market_id, pnl)
                    self.factor_manager.update_pnl_by_market(market_id, pnl)
                    self._log_event("market_resolved", {
                        "market_id": market_id,
                        "outcome": outcome_str,
                        "resolution": resolution,
                        "pnl": round(pnl, 4),
                    })

                    # 解決カウント更新 → ML再学習トリガー
                    self._resolved_since_last_training += 1
                    if (
                        self.config.auto_retrain
                        and not self._retraining
                        and self._resolved_since_last_training >= self.config.retrain_threshold
                    ):
                        asyncio.create_task(self._retrain_ml_model())

                    # ダッシュボードのクローズ済みポジションを更新
                    if self.dashboard:
                        await self._push_closed_positions_to_dashboard()

                except Exception:
                    continue

        except Exception:
            pass

    async def _push_closed_positions_to_dashboard(self):
        """クローズ済みポジションをダッシュボードへ送信"""
        try:
            closed = self.position_tracker.get_closed_positions(limit=20)
            closed_data = []
            for pos in closed:
                closed_data.append({
                    "market_id": pos.market_id,
                    "question": pos.question[:60],
                    "side": pos.side,
                    "entry_price": round(pos.entry_price, 6),
                    "exit_price": round(pos.exit_price, 6) if pos.exit_price is not None else None,
                    "size": round(pos.size, 2),
                    "pnl": round(pos.pnl, 4),
                    "status": pos.status.value,
                    "resolved_at": pos.resolved_at.isoformat() if pos.resolved_at else None,
                })
            await self.dashboard.push_closed_positions(closed_data)
        except Exception:
            pass
    
    async def _check_position_exits(self, markets: List):
        """利確・損切りをチェック"""
        # 無効なら SKIP
        if not self.config.enable_exit:
            return
        
        open_positions = self.position_tracker.get_open_positions()
        
        if not open_positions:
            return
        
        # 現在価格を収集
        current_prices = {}
        for market in markets:
            market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', None)
            yes_price = getattr(market, 'yes_price', None)
            if market_id and yes_price:
                current_prices[market_id] = yes_price
        
        # 利確・損切りチェック
        exit_signals = self.position_tracker.check_exit_conditions(
            current_prices=current_prices,
            take_profit_pct=self.config.take_profit_pct,
            stop_loss_pct=self.config.stop_loss_pct,
        )
        
        for exit_signal in exit_signals:
            pos = exit_signal["position"]
            action = exit_signal["action"]
            reason = exit_signal["reason"]
            pnl_pct = exit_signal["pnl_pct"]
            
            emoji = "💰" if reason == "take_profit" else "🛑"
            reason_jp = "利確" if reason == "take_profit" else "損切り"
            
            print(f"\n{emoji} {reason_jp}シグナル!")
            print(f"   {pos.question[:40]}")
            print(f"   含み損益: {pnl_pct:+.1%}")
            
            # 売却実行
            yes_price = current_prices.get(pos.market_id, 0.5)
            
            try:
                result = await self.executor.execute_order(
                    market_id=pos.market_id,
                    token_id=pos.token_id,
                    side=action,
                    size=pos.size,
                    price=yes_price if "YES" in action else (1 - yes_price),
                )
                
                if result.success:
                    realized_pnl = pos.calculate_unrealized_pnl(yes_price)
                    self.position_tracker.close_position(
                        position_id=pos.id,
                        exit_price=yes_price,
                        realized_pnl=realized_pnl,
                    )

                    # RiskManager からオープンポジション削除
                    if pos.market_id in self.risk_manager.open_positions:
                        del self.risk_manager.open_positions[pos.market_id]

                    # executed_markets から削除 → 再エントリーを許可
                    self.executed_markets.discard(pos.market_id)

                    print(f"   ✅ {reason_jp}完了: ${realized_pnl:+.2f}")
                else:
                    print(f"   ❌ {reason_jp}失敗: {result.message}")
                    
            except Exception as e:
                print(f"   ❌ エラー: {e}")
    
    def _get_analysis_interval(self, markets: List) -> int:
        """分析間隔を決定 (分)"""
        if not markets:
            return 60
        
        # 最も近い解決時間を取得
        min_time_to_resolution = timedelta(days=365)
        
        for m in markets:
            end_date = getattr(m, 'end_date', None)
            if end_date:
                if isinstance(end_date, str):
                    try:
                        end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    except:
                        continue
                
                now = datetime.now(timezone.utc)
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                time_to_res = end_date - now
                if time_to_res < min_time_to_resolution:
                    min_time_to_resolution = time_to_res
        
        # 間隔決定
        if min_time_to_resolution < timedelta(hours=2):
            return 5
        elif min_time_to_resolution < timedelta(hours=24):
            return 15
        elif min_time_to_resolution < timedelta(days=7):
            return 60
        else:
            return 240
    
    # ========== 学習層 ==========

    async def _mine_new_factor(self):
        """50トレードごとに新ファクターを生成 (バックグラウンド)"""
        print("\n⛏️ 学習層: 新ファクター生成中...")
        try:
            factor = await self.factor_manager.mine_new_factor()
            if factor:
                print(f"   ✅ 新ファクター採用: {factor.hypothesis.name} (IC: {factor.ic:.3f})")
            else:
                print("   ⚪ ファクター不採用 (IC不足 or 生成失敗)")
        except Exception as e:
            print(f"   ❌ ファクター生成エラー: {e}")

    async def _retrain_ml_model(self):
        """
        MLモデルをバックグラウンドで再学習してホットスワップ。
        LightGBM学習 (CPU bound) は ThreadPoolExecutor で実行するため
        WebSocket監視・分析ループをブロックしない。
        """
        self._retraining = True
        print("\n🔄 MLモデル再学習開始 (バックグラウンド)...")

        try:
            import re as _re
            import httpx as _httpx
            import numpy as np
            from analyst.features import FeatureExtractor
            from analyst.ml_analyst import MLAnalyst
            from analyst.orderflow import Trade as OFTrade
            from sklearn.model_selection import train_test_split
            from pathlib import Path as _Path

            loop = asyncio.get_running_loop()
            _gamma = "https://gamma-api.polymarket.com"
            _clob  = "https://clob.polymarket.com"
            _timeout = _httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

            def _parse_dt_local(s):
                """日時文字列を UTC datetime に変換。失敗時は None。"""
                if not s:
                    return None
                try:
                    s = str(s).strip().replace(" ", "T")
                    s = _re.sub(r'\.(\d+)', lambda m: '.' + m.group(1).ljust(6, '0')[:6], s)
                    if s.endswith("+00"):
                        s += ":00"
                    elif not s.endswith("Z") and "+" not in s[10:] and s.count("-") <= 2:
                        s += "+00:00"
                    s = s.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(s)
                    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    return None

            # 1. Gamma API から解決済みマーケットを取得
            #    - closedTime 降順: 最近解決されたものから
            #    - outcomePrices で YES/NO 判定 (resolutionResult は null が多い)
            #    - createdAt〜closedTime < 2日は短期バイナリ → 除外
            resolved = []
            cutoff_retrain = datetime.now(timezone.utc) - timedelta(days=30)
            offset_r = 0
            async with _httpx.AsyncClient(timeout=_timeout) as hclient:
                while len(resolved) < 1000:
                    resp = await hclient.get(
                        f"{_gamma}/markets",
                        params={
                            "closed": "true", "limit": 50,
                            "offset": offset_r,
                            "order": "closedTime", "ascending": "false",
                        },
                    )
                    resp.raise_for_status()
                    page = resp.json()
                    if not page:
                        break

                    all_old = True
                    for m in page:
                        closed_time = _parse_dt_local(m.get("closedTime"))
                        if closed_time and closed_time < cutoff_retrain:
                            break
                        if closed_time:
                            all_old = False

                        # 短期マーケット除外
                        created_at = _parse_dt_local(m.get("createdAt"))
                        if closed_time and created_at:
                            if (closed_time - created_at).total_seconds() < 172800:
                                continue

                        # outcomePrices で解決結果判定
                        outcome = None
                        op_raw = m.get("outcomePrices", "[]")
                        try:
                            op = json.loads(op_raw) if isinstance(op_raw, str) else op_raw
                            if op and len(op) >= 2:
                                p0, p1 = float(op[0]), float(op[1])
                                if p0 >= 0.99:
                                    outcome = "YES"
                                elif p1 >= 0.99:
                                    outcome = "NO"
                        except Exception:
                            pass
                        if outcome is None:
                            rs = str(m.get("resolutionResult") or m.get("resolution") or "").strip().upper()
                            if rs in ("1", "YES", "TRUE"):
                                outcome = "YES"
                            elif rs in ("0", "NO", "FALSE"):
                                outcome = "NO"
                        if outcome is None:
                            continue

                        clob_ids = m.get("clobTokenIds", "[]")
                        try:
                            token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                        except Exception:
                            token_ids = []
                        yes_token_id = token_ids[0] if token_ids else ""
                        if not yes_token_id:
                            continue

                        volume = float(m.get("volumeNum") or m.get("volume") or 0)
                        if volume < 1000:
                            continue

                        end_date = _parse_dt_local(m.get("endDateIso") or m.get("endDate"))
                        resolved.append({
                            "yes_token_id": yes_token_id,
                            "outcome": outcome,
                            "volume": volume,
                            "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
                            "end_date": end_date,
                        })

                    if all_old or len(page) < 50:
                        break
                    offset_r += 50
                    await asyncio.sleep(0.2)

            if not resolved:
                print("   ⚠️ 解決済みマーケットなし — 再学習スキップ")
                return

            print(f"   📋 解決済みマーケット: {len(resolved)}件")

            # 2. 特徴量 & ラベルを収集 (期間60%時点スナップショット / lookahead なし)
            extractor = FeatureExtractor()
            X_list, y_list = [], []

            async with _httpx.AsyncClient(timeout=_timeout) as hclient:
                for m in resolved:
                    try:
                        price_points = await self.price_fetcher.fetch_prices(
                            token_id=m["yes_token_id"],
                            interval="max",
                            fidelity=60,
                        )
                        n = len(price_points)
                        if n < 48:
                            continue

                        # 期間60%時点 (lookahead 防止)
                        analysis_idx = max(24, min(int(n * 0.6), n - 24))
                        history = [p.price for p in price_points[:analysis_idx]]
                        yes_price = history[-1]

                        # 価格が極端な場合はスキップ (解決直前データ汚染 / 長射程マーケット)
                        if yes_price <= 0.15 or yes_price >= 0.85:
                            continue

                        # 取引履歴
                        trades: List = []
                        try:
                            tr_resp = await hclient.get(
                                f"{_clob}/trades",
                                params={"market": m["yes_token_id"], "limit": 500},
                            )
                            raw_trades = tr_resp.json()
                            if isinstance(raw_trades, dict):
                                raw_trades = raw_trades.get("data", [])
                            for t in raw_trades:
                                try:
                                    ts = _parse_dt_local(
                                        t.get("timestamp") or t.get("match_time") or ""
                                    ) or datetime.now(timezone.utc)
                                    trades.append(OFTrade(
                                        timestamp=ts,
                                        price=float(t.get("price", 0)),
                                        size=float(t.get("size", 0)),
                                        side=(t.get("side") or "").lower(),
                                    ))
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        features = extractor.extract(
                            prices=history[-100:],
                            trades=trades if trades else None,
                            yes_price=yes_price,
                            market_volume=m["volume"],
                            market_liquidity=m["liquidity"],
                            end_date=m["end_date"],
                        )
                        X_list.append(features.to_list())
                        y_list.append(1 if m["outcome"] == "YES" else 0)

                    except Exception:
                        continue
                    await asyncio.sleep(0.2)

            if len(X_list) < 50:
                print(f"   ⚠️ データ不足 ({len(X_list)}件 < 50件) — 再学習スキップ")
                return

            print(f"   📦 学習データ: {len(X_list)}件")

            X = np.array(X_list)
            y = np.array(y_list)

            # 3. LightGBM学習 (CPU bound → executor でメインループをブロックしない)
            model_path = str(_Path(__file__).parent.parent / "models" / "lgb_model.pkl")

            def _train_sync():
                X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(set(y.tolist())) > 1 else None)
                analyst = MLAnalyst()
                result = analyst.train(X_tr, y_tr, X_val, y_val)
                analyst.save_model(model_path)
                return result

            result = await loop.run_in_executor(None, _train_sync)

            auc_str = f"AUC: {result['valid_auc']:.3f}" if result.get("valid_auc") else f"trees: {result['n_estimators']}"
            print(f"   ✅ 再学習完了 ({auc_str})")

            # 4. ホットスワップ (分析中でも安全に差し替え)
            self.analyst.reload_ml_model(model_path)
            self._resolved_since_last_training = 0

        except Exception as e:
            print(f"   ❌ 再学習エラー: {e}")
        finally:
            self._retraining = False

    # ========== 構造化ログ ==========

    def _log_event(self, event_type: str, data: Dict):
        """
        data/trade_log.jsonl にイベントを追記。
        1行1JSON。ログ書き込み失敗はサイレント無視 (メインループを止めない)。

        event_type:
            signal_generated  - Auditor通過後のシグナル
            trigger_set       - トリガー設定
            trigger_fired     - トリガー発火・約定
            trigger_expired   - トリガー期限切れ
            market_resolved   - マーケット解決
        """
        try:
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event_type,
                **data,
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # ログ失敗でもトレードは続行

    # ========== LLM判断キャッシュ ==========

    _JUDGMENT_DIR = Path("data/llm_judgments")

    def _save_llm_judgment(self, token_id: str, signal) -> None:
        """トリガーセット時にLLM判断をキャッシュ (1トークン1ファイル・上書き)"""
        try:
            self._JUDGMENT_DIR.mkdir(parents=True, exist_ok=True)
            path = self._JUDGMENT_DIR / f"{token_id}.json"
            data = {
                "probability": round(signal.final_probability, 4),
                "confidence": round(signal.confidence, 4),
                "reasoning": signal.llm_reasoning,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_llm_judgment(self, token_id: str) -> Optional[dict]:
        """前回のLLM判断を読み込む。なければ None"""
        try:
            path = self._JUDGMENT_DIR / f"{token_id}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    # ========== ポジションダッシュボード送信 ==========

    async def _push_positions_to_dashboard(self, markets: List):
        """オープンポジションの含み損益を計算してダッシュボードへ送信"""
        try:
            # market_id → 現在の YES 価格 マップ (スキャン結果から)
            current_prices: Dict[str, float] = {}
            for m in markets:
                mid = getattr(m, "condition_id", None)
                price = getattr(m, "yes_price", None)
                if mid and price:
                    current_prices[mid] = price

            # スキャンに含まれないポジションはCLOBから直接取得
            open_positions = self.position_tracker.get_open_positions()
            missing = [p for p in open_positions if p.market_id not in current_prices]
            if missing:
                try:
                    from client import PolyClient
                    _pc = PolyClient()
                    _pc.connect(read_only=True)
                    for pos in missing:
                        # yes_token_id があれば常にYES token で取得 (BUY_NO でも YES価格)
                        fetch_token = pos.yes_token_id or pos.token_id
                        mid_price = _pc.get_midpoint(fetch_token)
                        if mid_price is None:
                            # orderbook なし = マーケット解決済みの可能性
                            if pos.market_id not in getattr(self, '_no_orderbook_warned', set()):
                                if not hasattr(self, '_no_orderbook_warned'):
                                    self._no_orderbook_warned = set()
                                self._no_orderbook_warned.add(pos.market_id)
                                print(f"   ⚠️ orderbook なし (解決済み?): {pos.question[:50]}")
                        if mid_price is not None:
                            if pos.yes_token_id:
                                # YES token で取得済み → そのまま YES 価格
                                current_prices[pos.market_id] = mid_price
                            else:
                                # 旧レコード: side で判定 + ヒューリスティック
                                # BUY_YES なのに midpoint が entry_price より (1-entry_price) に
                                # 近い場合はバグで NO token が格納されているので反転する
                                side_upper = pos.side.upper()
                                if "NO" in side_upper:
                                    current_prices[pos.market_id] = 1.0 - mid_price
                                elif (
                                    abs(mid_price - (1.0 - pos.entry_price))
                                    < abs(mid_price - pos.entry_price)
                                ):
                                    # NO token が誤格納されている → 反転して YES 価格に
                                    current_prices[pos.market_id] = 1.0 - mid_price
                                else:
                                    current_prices[pos.market_id] = mid_price
                except Exception:
                    pass  # 取得失敗時はフォールバック

            positions_data = []
            for pos in open_positions:
                yes_price = current_prices.get(pos.market_id, pos.entry_price)
                unrealized = pos.calculate_unrealized_pnl(yes_price)
                unrealized_pct = pos.get_unrealized_pnl_pct(yes_price)
                positions_data.append({
                    "market_id": pos.market_id,
                    "question": pos.question[:60],
                    "side": pos.side,
                    "entry_price": round(pos.entry_price, 6),
                    "current_price": round(yes_price, 6),
                    "size": round(pos.size, 2),
                    "unrealized_pnl": round(unrealized, 4),
                    "unrealized_pnl_pct": round(unrealized_pct, 4),
                    "created_at": pos.created_at.isoformat() if pos.created_at else None,
                    "order_filled": pos.order_filled,
                    "order_id": pos.order_id,
                })

            await self.dashboard.push_positions(positions_data)
            await self._push_closed_positions_to_dashboard()

            # ポートフォリオ集計 (PENDING は株式未保有のため除外)
            filled_data      = [p for p in positions_data if p.get("order_filled") is True]
            total_unrealized = round(sum(p.get("unrealized_pnl", 0) for p in filled_data), 2)
            total_exposure   = round(sum(p.get("size", 0) for p in filled_data), 2)
            portfolio        = round(self.risk_manager.current_balance + total_exposure + total_unrealized, 2)
            await self.dashboard.update_state("unrealized_pnl", total_unrealized)
            await self.dashboard.update_state("exposure", total_exposure)
            await self.dashboard.update_state("portfolio", portfolio)

        except Exception:
            pass  # ダッシュボード送信失敗でもメインループを止めない

    # ========== 期限切れトリガー清掃 ==========

    async def _cleanup_expired_triggers(self):
        """期限切れトリガーを削除"""
        expired = [
            (tid, t) for tid, t in self.active_triggers.items()
            if t.is_expired()
        ]
        
        for tid, trigger in expired:
            self.risk_manager.remove_pending_exposure(trigger.size)
            del self.active_triggers[tid]
            self._log_event("trigger_expired", {
                "market_id": trigger.market_id,
                "question": trigger.question[:60],
                "side": trigger.side,
                "target_price": round(trigger.target_price, 6),
                "size": round(trigger.size, 2),
            })
            print(f"🗑️ トリガー期限切れ: {tid[:16]}...")


# CLI用ヘルパー
async def run_orchestrator(
    mode: str = "dry_run",
    model: str = "claude-haiku-4-5-20251001",
    min_edge: float = 0.10,
    max_markets: int = 10,
    fetch_news: bool = True,
    dashboard: bool = True,
    dashboard_port: int = 8080,
    enable_exit: bool = False,
    take_profit_pct: float = 0.50,
    stop_loss_pct: float = -0.50,
    auto_retrain: bool = True,
    retrain_threshold: int = 20,
    min_liquidity: float = 10_000,
    min_volume: float = 50_000,
):
    """オーケストレーター実行"""
    config = OrchestratorConfig(
        mode=RunMode.LIVE if mode == "live" else RunMode.DRY_RUN,
        llm_model=model,
        min_edge=min_edge,
        max_markets=max_markets,
        fetch_news=fetch_news,
        dashboard=dashboard,
        dashboard_port=dashboard_port,
        enable_exit=enable_exit,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        auto_retrain=auto_retrain,
        retrain_threshold=retrain_threshold,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
    )

    orchestrator = Orchestrator(config)
    await orchestrator.start()
