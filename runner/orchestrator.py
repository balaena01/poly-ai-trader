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
from data_fetcher import PolyWebSocket, GoogleNewsFetcher, PriceHistoryFetcher


class RunMode(Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


@dataclass
class TriggerCondition:
    """売買トリガー条件"""
    market_id: str
    token_id: str
    question: str
    side: str  # "BUY" or "SELL"
    target_price: float  # この価格以下で買い / 以上で売り
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
        if self.side == "BUY":
            return current_price <= self.target_price
        else:
            return current_price >= self.target_price


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
    
    # ニュース
    fetch_news: bool = True
    news_limit: int = 5


class Orchestrator:
    """統合オーケストレーター"""
    
    def __init__(self, config: OrchestratorConfig = None):
        self.config = config or OrchestratorConfig()
        
        # コンポーネント
        self.scanner = MarketScanner()
        self.analyst = EnsembleAnalyst(
            llm_model=self.config.llm_model,
            use_ml=True,
            use_orderflow=True,
        )
        self.executor = TradeExecutor(
            dry_run=(self.config.mode == RunMode.DRY_RUN)
        )
        self.risk_manager = RiskManager()
        self.auditor = Auditor()
        self.news_fetcher = GoogleNewsFetcher()
        
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
        print("\nCtrl+C で停止\n")
        
        try:
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
            
            # 両タスクを待機
            await asyncio.gather(
                self._ws_task,
                self._analysis_task,
                return_exceptions=True,
            )
            
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
        
        print(f"\n📊 最終統計:")
        print(f"   サイクル: {self.stats['cycles']}")
        print(f"   シグナル: {self.stats['signals_generated']}")
        print(f"   取引: {self.stats['trades_executed']} (成功: {self.stats['trades_success']})")
    
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
            else:
                print(f"   ❌ 失敗: {result.message}")
            
            # トリガー削除
            del self.active_triggers[trigger.token_id]
            
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
            
            # Auditorチェック
            audit_result = self.auditor.audit(signal, market)
            
            if audit_result.should_block:
                print(f"   🚫 ブロック: {audit_result.block_reason}")
                return
            
            # 信頼度調整
            adjusted_confidence = signal.confidence * (1 - audit_result.total_penalty)
            
            # 最小条件チェック
            if signal.edge < self.config.min_edge:
                print(f"   ⚪ エッジ不足 ({signal.edge:.1%} < {self.config.min_edge:.0%})")
                return
            
            if adjusted_confidence < self.config.min_confidence:
                print(f"   ⚪ 信頼度不足 ({adjusted_confidence:.0%})")
                return
            
            # ポジションサイズ計算
            size = self.risk_manager.calc_position_size(
                edge=signal.edge,
                confidence=adjusted_confidence,
                max_pct=self.config.max_position_pct,
            )
            
            # トリガー設定
            await self._set_trigger(market, signal, size)
            
        except Exception as e:
            print(f"   ❌ エラー: {e}")
    
    async def _set_trigger(self, market, signal, size: float):
        """トリガー条件を設定"""
        token_id = getattr(market, 'yes_token_id', None)
        if not token_id:
            return
        
        market_id = getattr(market, 'condition_id', str(id(market)))
        question = getattr(market, 'question', str(market))
        
        # 目標価格 (現在価格から少し有利な位置)
        current_price = getattr(market, 'yes_price', 0.5)
        if signal.action.value == "BUY":
            target_price = current_price * 0.98  # 2%下で買い
        else:
            target_price = current_price * 1.02  # 2%上で売り
        
        trigger = TriggerCondition(
            market_id=market_id,
            token_id=token_id,
            question=question,
            side=signal.action.value,
            target_price=target_price,
            size=size,
            signal_confidence=signal.confidence,
            expires_at=datetime.now() + timedelta(minutes=self.config.trigger_expiry_minutes),
        )
        
        self.active_triggers[token_id] = trigger
        
        print(f"   ⏰ トリガー設定: {signal.action.value} @ {target_price:.4f}")
        print(f"      サイズ: ${size:.2f} | 有効期限: {self.config.trigger_expiry_minutes}分")
    
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
            tid for tid, t in self.active_triggers.items()
            if t.is_expired()
        ]
        
        for tid in expired:
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
