"""
Orchestrator - フル統合ランナー

3層アーキテクチャ:
- リアルタイム層: WebSocket監視 + 即時売買
- 分析層: LLM + ML + Orderflow + Bayesian (可変間隔)
- 学習層: Factor Miner + Auto-Killer (バックグラウンド)
"""
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now() > self.expires_at
    
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


class Orchestrator:
    """統合オーケストレーター"""
    
    def __init__(self, config: OrchestratorConfig = None):
        self.config = config or OrchestratorConfig()
        
        # コンポーネント
        self.scanner = MarketScanner()
        # TODO: ML/Orderflow は価格履歴・取引履歴が必要
        # 現状は LLM のみで予測
        self.analyst = EnsembleAnalyst(
            llm_model=self.config.llm_model,
            use_ml=False,       # 学習済みモデルがない
            use_orderflow=False, # 取引履歴がない
        )
        self.executor = TradeExecutor(
            dry_run=(self.config.mode == RunMode.DRY_RUN)
        )
        self.risk_manager = RiskManager()
        self.auditor = Auditor()
        self.factor_manager = FactorManager()
        self.position_tracker = PositionTracker()
        # Google News RSS (高速・安定)
        self.news_fetcher = GoogleNewsFetcher()
        
        # ダッシュボード
        self.dashboard = None
        if self.config.dashboard and DASHBOARD_AVAILABLE:
            self.dashboard = DashboardServer(port=self.config.dashboard_port)
        
        # WebSocket
        self.websocket: Optional[PolyWebSocket] = None
        
        # トリガー管理
        self.active_triggers: Dict[str, TriggerCondition] = {}
        self.executed_markets: Set[str] = set()
        
        # 状態
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._analysis_task: Optional[asyncio.Task] = None
        
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
            # 残高取得
            from client import PolyClient
            try:
                poly_client = PolyClient()
                poly_client.connect(read_only=True)
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
        
        self.websocket.on_price(on_price)
        
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
                        pnl=0,
                        entry_price=price,
                        market_id=trigger.market_id,
                    )
            else:
                print(f"   ❌ 失敗: {result.message}")
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
                print(f"📊 サイクル #{self.stats['cycles']} - {datetime.now().strftime('%H:%M:%S')}")
                
                # マーケット再スキャン (10サイクルごと)
                if self.stats["cycles"] % 10 == 0:
                    markets = await self._scan_markets()
                
                # 各マーケットを分析
                for market in markets:
                    if not self._running:
                        break
                    
                    await self._analyze_market(market)
                
                # 解決済みマーケットをチェック
                await self._check_resolved_markets()
                
                # 利確・損切りチェック
                await self._check_position_exits(markets)
                
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
            
            # 分析
            signal = await self.analyst.analyze(
                market=market,
                btc_price=None,  # TODO: 価格取得
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
        
        # 目標価格 (現在価格から少し有利な位置)
        # YES価格ベースで計算
        current_price = getattr(market, 'yes_price', 0.5)
        action = signal.action.value
        
        if action == "BUY_YES":
            target_price = current_price * 0.99  # YES が1%下がったら買い
        elif action == "BUY_NO":
            target_price = current_price * 1.01  # YES が1%上がったら買い (= NO が安くなる)
        elif action == "SELL_YES":
            target_price = current_price * 1.01  # YES が1%上がったら売り
        else:  # SELL_NO
            target_price = current_price * 0.99  # YES が1%下がったら売り
        
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
            expires_at=datetime.now() + timedelta(minutes=self.config.trigger_expiry_minutes),
        )
        
        # YES token で監視 (WebSocket は YES 価格を送ってくる)
        self.active_triggers[watch_token_id] = trigger
        
        # ペンディングエクスポージャーに追加
        self.risk_manager.add_pending_exposure(size)
        
        print(f"   ⏰ トリガー設定: {signal.action.value} @ {target_price:.4f}")
        print(f"      サイズ: ${size:.2f} | 有効期限: {self.config.trigger_expiry_minutes}分")
        
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
                
                time_to_res = end_date - datetime.now(end_date.tzinfo if hasattr(end_date, 'tzinfo') else None)
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
    
    # ========== 期限切れトリガー清掃 ==========
    
    async def _cleanup_expired_triggers(self):
        """期限切れトリガーを削除"""
        expired = [
            (tid, t) for tid, t in self.active_triggers.items()
            if t.is_expired()
        ]
        
        for tid, trigger in expired:
            # ペンディングエクスポージャーを解放
            self.risk_manager.remove_pending_exposure(trigger.size)
            del self.active_triggers[tid]
            print(f"🗑️ トリガー期限切れ: {tid[:16]}...")


# CLI用ヘルパー
async def run_orchestrator(
    mode: str = "dry_run",
    model: str = "claude-haiku-4-5-20251001",
    min_edge: float = 0.10,
    max_markets: int = 10,
    fetch_news: bool = True,
):
    """オーケストレーター実行"""
    config = OrchestratorConfig(
        mode=RunMode.LIVE if mode == "live" else RunMode.DRY_RUN,
        llm_model=model,
        min_edge=min_edge,
        max_markets=max_markets,
        fetch_news=fetch_news,
    )
    
    orchestrator = Orchestrator(config)
    await orchestrator.start()
