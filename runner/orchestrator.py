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
        if self.side == "BUY_YES":
            return current_price <= self.target_price
        elif self.side == "BUY_NO":
            return current_price >= self.target_price
        elif self.side == "SELL_YES":
            return current_price >= self.target_price
        else:  # SELL_NO
            return current_price <= self.target_price


@dataclass
class OrchestratorConfig:
    """設定"""
    # 分析
    llm_model: str = "claude-haiku-4-5-20251001"
    min_edge: float = 0.10
    min_confidence: float = 0.60
    max_markets: int = 10
    
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
        result = await self.scanner.scan()

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
        if trigger.side in ("BUY_YES", "BUY_NO"):
            if trigger.side == "BUY_YES":
                current_edge = trigger.signal_probability - price
            else:
                current_edge = price - trigger.signal_probability

            min_viable_edge = self.config.min_edge * 0.5  # シグナル閾値の50%まで許容
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
                
                # ポジション記録
                self.position_tracker.record_trade(
                    market_id=trigger.market_id,
                    token_id=trigger.token_id,
                    question=trigger.question,
                    side=trigger.side,
                    entry_price=price,
                    size=trigger.size,
                )
                
                # ファクター記録 (アクティブファクターがあれば)
                active_factors = self.factor_manager.get_active_factors()
                if active_factors:
                    factor = active_factors[0]
                    self.factor_manager.record_trade(
                        factor_id=factor.hypothesis.id,
                        pnl=0,           # 解決後に update_pnl_by_market() で更新
                        entry_price=price,
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
                
                # マーケット再スキャン (10サイクルごと)
                if self.stats["cycles"] % 10 == 0:
                    markets = await self._scan_markets()
                
                # 各マーケットを分析 (サイクルごとのトリガー上限を適用)
                self._triggers_this_cycle = 0
                for market in markets:
                    if not self._running:
                        break
                    if self._triggers_this_cycle >= self.config.max_trades_per_cycle:
                        print(f"   ⏸️ トリガー上限到達 ({self.config.max_trades_per_cycle}件/サイクル)")
                        break

                    await self._analyze_market(market)
                
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
                    # balance は起動時に設定済み (上書きしない)
                
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
        market_id = getattr(market, 'condition_id', str(id(market)))
        if market_id in self.executed_markets:
            return
        
        # 既存トリガーをチェック (後で比較用)
        token_id = getattr(market, 'yes_token_id', None)
        existing_trigger = self.active_triggers.get(token_id) if token_id else None
        
        question = getattr(market, 'question', str(market))
        print(f"\n🧠 分析: {question[:50]}...")
        
        try:
            # ニュース取得
            news_context = ""
            if self.config.fetch_news:
                articles = await self.news_fetcher.search(
                    question[:50],
                    limit=self.config.news_limit,
                )
                if articles:
                    news_context = "\n".join([
                        f"- {a.title}" for a in articles[:3]
                    ])
                    print(f"   📰 ニュース: {len(articles)}件")
            
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

            # 分析
            signal = await self.analyst.analyze(
                market=market,
                prices=prices,
                trades=trades,
                btc_price=self._btc_price,
                news_context=news_context,
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
                return
            
            if adjusted_confidence < self.config.min_confidence:
                print(f"   ⚪ 信頼度不足 ({adjusted_confidence:.0%})")
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
        if signal.action.value in ("BUY_YES", "SELL_YES"):
            token_id = getattr(market, 'yes_token_id', None)
        else:
            token_id = getattr(market, 'no_token_id', None) or getattr(market, 'yes_token_id', None)
        
        # 価格監視用のYESトークンID (常にYES価格で判定)
        watch_token_id = getattr(market, 'yes_token_id', None)
        if not watch_token_id:
            return
        
        market_id = getattr(market, 'condition_id', str(id(market)))
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
    
    async def _check_resolved_markets(self):
        """解決済みマーケットをチェックしてPnL更新"""
        open_market_ids = self.position_tracker.get_open_market_ids()
        
        if not open_market_ids:
            return
        
        try:
            # Polymarketから解決状態を取得
            from client import PolyClient
            client = PolyClient()
            client.connect(read_only=True)
            
            for market_id in open_market_ids:
                try:
                    # マーケット情報取得
                    market = client.get_market(market_id)
                    if market and market.get("closed"):
                        # 解決済み - outcome を確認
                        # outcome: "YES" or "NO"
                        outcome = market.get("outcome", "")
                        if outcome:
                            resolution = 1.0 if outcome.upper() == "YES" else 0.0
                            pnl = self.position_tracker.resolve_by_market(market_id, resolution)
                            if pnl != 0:
                                print(f"💰 マーケット解決: PnL ${pnl:+.2f}")
                                self.factor_manager.update_pnl_by_market(market_id, pnl)
                                self.risk_manager.record_close(market_id, pnl)
                                self._log_event("market_resolved", {
                                    "market_id": market_id,
                                    "outcome": outcome,
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
                except Exception as e:
                    continue  # 個別エラーは無視
                    
        except Exception as e:
            pass  # 静かに失敗
    
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
            market_id = getattr(market, 'condition_id', None)
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

            # 1. Gamma API から解決済みマーケットを直接取得
            #    PolyClient.get_markets() は closed=false をハードコードしているため使用不可
            resolved = []
            async with _httpx.AsyncClient(timeout=_timeout) as hclient:
                resp = await hclient.get(
                    f"{_gamma}/markets",
                    params={"closed": "true", "limit": 200, "order": "volume", "ascending": "false"},
                )
                resp.raise_for_status()
                for m in resp.json():
                    res_raw = str(
                        m.get("resolution") or m.get("resolutionResult") or ""
                    ).strip().upper()
                    if res_raw in ("1", "YES", "TRUE"):
                        outcome = "YES"
                    elif res_raw in ("0", "NO", "FALSE"):
                        outcome = "NO"
                    else:
                        continue

                    clob_ids = m.get("clobTokenIds", "[]")
                    try:
                        token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                    except Exception:
                        token_ids = []
                    yes_token_id = token_ids[0] if token_ids else ""
                    if not yes_token_id:
                        continue

                    resolved.append({
                        "yes_token_id": yes_token_id,
                        "outcome": outcome,
                        "volume": float(m.get("volumeNum") or m.get("volume") or 0),
                        "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
                        "end_date_str": m.get("endDateIso") or m.get("end_date_iso"),
                    })

            if not resolved:
                print("   ⚠️ 解決済みマーケットなし — 再学習スキップ")
                return

            print(f"   📋 解決済みマーケット: {len(resolved)}件")

            # 2. 特徴量 & ラベルを収集
            extractor = FeatureExtractor()
            X_list, y_list = [], []

            async with _httpx.AsyncClient(timeout=_timeout) as hclient:
                for m in resolved[:100]:
                    try:
                        # 価格履歴
                        price_points = await self.price_fetcher.fetch_prices(
                            token_id=m["yes_token_id"],
                            interval="max",
                            fidelity=60,
                        )
                        if len(price_points) < 10:
                            continue
                        prices = [p.price for p in price_points[:-1]]

                        # 取引履歴 (volume特徴量: buy_volume_ratio / order_flow_imbalance)
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
                                    ts_str = t.get("timestamp") or t.get("match_time") or ""
                                    ts = (
                                        datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                        if ts_str else datetime.now(timezone.utc)
                                    )
                                    trades.append(OFTrade(
                                        timestamp=ts,
                                        price=float(t.get("price", 0)),
                                        size=float(t.get("size", 0)),
                                        side=(t.get("side") or "").lower(),
                                    ))
                                except Exception:
                                    pass
                        except Exception:
                            pass  # trades 取得失敗は無視して続行

                        # 終了日パース
                        end_date = None
                        end_date_str = m.get("end_date_str")
                        if end_date_str:
                            try:
                                end_date = datetime.fromisoformat(
                                    end_date_str.replace("Z", "+00:00")
                                )
                            except Exception:
                                pass

                        features = extractor.extract(
                            prices=prices[-100:],
                            trades=trades if trades else None,
                            yes_price=prices[-1] if prices else 0.5,
                            market_volume=m["volume"],
                            market_liquidity=m["liquidity"],
                            end_date=end_date,
                        )
                        X_list.append(features.to_list())
                        y_list.append(1 if m["outcome"] == "YES" else 0)

                    except Exception:
                        continue
                    await asyncio.sleep(0.2)  # レート制限

            if len(X_list) < 50:
                print(f"   ⚠️ データ不足 ({len(X_list)}件 < 50件) — 再学習スキップ")
                return

            print(f"   📦 学習データ: {len(X_list)}件")

            X = np.array(X_list)
            y = np.array(y_list)

            # 3. LightGBM学習 (CPU bound → executor でメインループをブロックしない)
            model_path = str(_Path(__file__).parent.parent / "models" / "lgb_model.pkl")

            def _train_sync():
                X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
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

    # ========== ポジションダッシュボード送信 ==========

    async def _push_positions_to_dashboard(self, markets: List):
        """オープンポジションの含み損益を計算してダッシュボードへ送信"""
        try:
            # market_id → 現在の YES 価格 マップ
            current_prices: Dict[str, float] = {}
            for m in markets:
                mid = getattr(m, "condition_id", None)
                price = getattr(m, "yes_price", None)
                if mid and price:
                    current_prices[mid] = price

            positions_data = []
            for pos in self.position_tracker.get_open_positions():
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
                })

            await self.dashboard.push_positions(positions_data)
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
    )

    orchestrator = Orchestrator(config)
    await orchestrator.start()
