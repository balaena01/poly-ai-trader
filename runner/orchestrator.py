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
from tracker.brier_tracker import BrierTracker

# Dashboard (optional)
try:
    from dashboard import DashboardServer
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False


class RunMode(Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


_SPORTS_KEYWORDS = [
    # 競技種目
    "nfl", "nba", "nhl", "mlb", "mls", "ufc", "pga",
    "soccer", "football", "basketball", "baseball", "hockey", "tennis",
    "golf", "boxing", "mma", "rugby", "cricket", "volleyball",
    # 試合・大会
    "match", " vs ", " vs.", "game ", "playoff", "championship",
    "tournament", "league", "cup", "serie", "super bowl", "world series",
    "stanley cup", "grand slam", "wimbledon", "us open", "french open",
    "australian open", "masters", "open championship",
    "world cup", "euro ", "champions league", "premier league",
    "la liga", "bundesliga", "serie a", "ligue 1",
    # 試合結果 (スポーツ文脈に限定)
    "o/u ", "over/under", "moneyline", "cover the",
    "final score", "first half", "second half", "overtime",
    # スポーツチーム・大会名によく出る単語
    "warriors", "lakers", "celtics", "heat ", "bulls ",
    "patriots", "chiefs ", "eagles ", "cowboys",
    "yankees", "dodgers", "red sox",
    "oilers", "sharks ", "leafs", "bruins",
    # 選手名は動的なので除外、試合構造ワードで判定
]

def is_sports_market(question: str) -> bool:
    """スポーツ系マーケットを判定 (分析はするがトレード対象外)"""
    q = question.lower()
    return any(kw in q for kw in _SPORTS_KEYWORDS)


def _order_status(order) -> Optional[str]:
    """py-clob-client の注文オブジェクト(dict or object)からステータス文字列を取得"""
    if order is None:
        return None
    if isinstance(order, dict):
        return order.get("status")
    return getattr(order, "status", None)



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

    # リスク
    max_position_pct: float = 0.10
    max_drawdown_pct: float = 0.15
    
    # 利確・損切り
    take_profit_pct: float = 0.40           # 含み益 40% 超で利確 (価格ベース・セカンダリ)
    take_profit_min_days: int = 14          # 利確は解決まで14日超のときのみ
    stop_loss_pct: float = -0.80            # 価格ベース損切り (ほぼ全損時の最終保険)
    llm_reversal_exit: bool = True          # LLM逆転シグナルでクローズ

    # 確率崩壊ストップ (㉑)
    collapse_threshold: float = 0.88        # YES確率がこれ以上 → BUY_NO を損切り (逆方向も対称)
    stop_loss_near_expiry_days: int = 7     # 残りN日以内かつ含み損が閾値以下なら損切り
    stop_loss_near_expiry_pct: float = -0.40  # 近解決時の含み損閾値

    # エッジ消失利確 (㉒)
    edge_take_profit_threshold: float = 0.05  # エッジがこれ以下になったら利確
    
    # ニュース
    fetch_news: bool = True
    news_limit: int = 5

    # ダッシュボード
    dashboard: bool = False
    dashboard_port: int = 8080

    # ML
    use_ml: bool = False                # ML使用 (デフォルトOFF: LLMのみで実績を積む)
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
        use_ml = self.config.use_ml and ml_model_path.exists()

        # Ensemble Analyst
        self.analyst = EnsembleAnalyst(
            llm_model=self.config.llm_model,
            ml_model_path=str(ml_model_path) if use_ml else None,
            use_ml=use_ml,
            use_orderflow=True,  # WebSocket から取引データ収集
        )
        if not use_ml:
            print("   ML: 無効 (LLMのみ運用中)")
        self.executor = TradeExecutor(
            dry_run=(self.config.mode == RunMode.DRY_RUN),
            use_risk_manager=False,  # オーケストレーターが一元管理するため無効化
        )
        self.risk_manager = RiskManager()
        self.auditor = Auditor()
        self.factor_manager = FactorManager()
        self.position_tracker = PositionTracker()
        self.brier_tracker = BrierTracker()
        # 起動時点で skill_score を適用 (未計測 → 半Kelly)
        self.risk_manager.update_llm_skill(self.brier_tracker.get_skill_score())

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
            self.dashboard.on_dismiss_manual_sale = self._handle_dismiss_manual_sale
        
        # WebSocket
        self.websocket: Optional[PolyWebSocket] = None
        
        # 再起動後もポジション重複を防ぐため、既存のオープンポジションを読み込む
        self.executed_markets: Set[str] = set(self.position_tracker.get_open_market_ids())
        
        # 状態
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._analysis_task: Optional[asyncio.Task] = None
        self._positions_task: Optional[asyncio.Task] = None
        self._last_markets: List = []  # 最新のマーケットリスト (positions loop が参照)

        # ML再学習管理
        self._resolved_since_last_training: int = 0
        self._retraining: bool = False

        # 最新シグナルキャッシュ (エッジ消失利確に使用)
        self._last_signals: Dict = {}  # market_id → Signal

        # パフォーマンスフィードバック context キャッシュ (30分ごとに再生成)
        self._perf_context_cache: str = ""
        self._perf_context_updated_at: Optional[datetime] = None

        # 構造化ログ (data/trade_log.jsonl)
        _log_dir = Path(__file__).parent.parent / "data"
        _log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = _log_dir / "trade_log.jsonl"

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

            # ポジション更新ループ起動 (30秒ごと、ダッシュボード専用)
            self._positions_task = asyncio.create_task(
                self._positions_loop()
            )

            # タスクを待機
            tasks = [self._ws_task, self._analysis_task, self._positions_task]
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
        
        self.websocket.on_trade(on_trade)
        
        # 接続
        try:
            await self.websocket.connect(token_ids)
        except Exception as e:
            print(f"❌ WebSocketエラー: {e}")
    
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
                self._last_markets = markets

                # LLM skill_score を更新してEnsemble・RiskManagerに反映
                skill_score = self.brier_tracker.get_skill_score()
                self.analyst.set_llm_skill(skill_score)
                self.risk_manager.update_llm_skill(skill_score)
                if self.dashboard:
                    await self.dashboard.update_state("llm_skill", skill_score)
                    await self.dashboard.push_brier_stats(self.brier_tracker.get_stats())

                # 各マーケットを分析 (エクスポージャー上限はRiskManagerが管理)
                for market in markets:
                    if not self._running:
                        break
                    await self._analyze_market(market)
                
                # 解決済みマーケットをチェック
                await self._check_resolved_markets()

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
        # 既に実行済みならスキップ (PENDING/FILLEDは再検証のため通過)
        market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', str(id(market)))
        _check_reversal_exit = False
        if market_id in self.executed_markets:
            pending_check = next(
                (p for p in self.position_tracker.get_pending_positions() if p.market_id == market_id),
                None,
            )
            if not pending_check:
                # FILLED → LLM逆転クローズ確認のため分析継続
                if not self.config.llm_reversal_exit:
                    return
                filled_check = next(
                    (p for p in self.position_tracker.get_open_positions()
                     if p.market_id == market_id and p.order_filled),
                    None,
                )
                if not filled_check:
                    return  # 完全終了済み → スキップ
                _check_reversal_exit = True
            # PENDING or FILLED(reversal) → fall through

        token_id = getattr(market, 'yes_token_id', None)
        # PENDING GTC注文があれば取得 (再分析でエッジ消失時にキャンセルするため)
        pending_pos = next(
            (p for p in self.position_tracker.get_pending_positions() if p.market_id == market_id),
            None,
        )
        
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

        # エクスポージャー上限チェック (新規のみ。PENDING/FILLEDは再検証のため継続)
        if not pending_pos and not _check_reversal_exit:
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
                        interval="1w",  # 直近1週間
                        fidelity=60,    # 1時間足
                    )
                    prices = [p.price for p in price_points]
                    
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

            # パフォーマンスフィードバック context (30分キャッシュ)
            performance_context = self._build_performance_context()

            # 保有ポジション context (相関チェック用、新規エントリー時のみ)
            open_positions_context = "" if (_check_reversal_exit or pending_pos) else self._build_open_positions_context()

            # 分析
            signal = await self.analyst.analyze(
                market=market,
                prices=prices,
                trades=trades,
                btc_price=self._btc_price,
                news_context=news_context,
                previous_judgment=previous_judgment,
                performance_context=performance_context,
                open_positions_context=open_positions_context,
            )

            # LLM予測をBrierTrackerに記録（最初の1回のみ保存）
            if signal and signal.llm_prob != 0.5:
                self.brier_tracker.record_prediction(
                    market_id=getattr(market, "market_id", ""),
                    llm_prob=signal.llm_prob,
                    market_price=getattr(market, "yes_price", 0.5),
                    yes_token_id=getattr(market, "yes_token_id", ""),
                )

            if not signal:
                print(f"   ⚪ シグナルなし")
                return

            # 最新シグナルをキャッシュ (エッジ消失利確に使用)
            self._last_signals[market_id] = signal

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

            # スポーツ系マーケットはトレード対象外 (Brier記録のみ)
            # キーワード判定 OR LLM判定のどちらかがスポーツと判断したらスキップ
            _kw_sport = is_sports_market(question)
            _llm_sport = getattr(signal, 'llm_is_sport', None) is True
            if _kw_sport or _llm_sport:
                reason = []
                if _kw_sport:  reason.append("キーワード")
                if _llm_sport: reason.append("LLM判定")
                print(f"   🏟️ スポーツ市場のためトレードスキップ ({'+'.join(reason)}, Brier記録のみ)")
                return

            # 相関ポジション検出 → 新規エントリーのみスキップ (reversal/pendingは通過)
            if not _check_reversal_exit and not pending_pos:
                if getattr(signal, 'llm_is_correlated', False):
                    corr_reason = getattr(signal, 'llm_correlation_reason', '')
                    print(f"   🔗 相関ポジション検出のためスキップ: {corr_reason}")
                    return

            # 信頼度調整
            adjusted_confidence = audit_result.adjusted_confidence
            if audit_result.flags:
                flags_str = ", ".join([f.value for f in audit_result.flags])
                print(f"   🔍 Audit: {flags_str} → penalty={audit_result.confidence_penalty:.0%} conf={signal.confidence:.0%}→{adjusted_confidence:.0%}")

            # 最小条件チェック
            if abs(signal.edge) < self.config.min_edge:
                print(f"   ⚪ エッジ不足 ({signal.edge:.1%}, 閾値: ±{self.config.min_edge:.0%})")
                if pending_pos:
                    await self._cancel_pending_order(pending_pos, "エッジ消滅")
                return

            if adjusted_confidence < self.config.min_confidence:
                print(f"   ⚪ 信頼度不足 ({adjusted_confidence:.0%})")
                if pending_pos:
                    if pending_pos.side != signal.action.value:
                        await self._cancel_pending_order(pending_pos, f"方向逆転: {pending_pos.side} → {signal.action.value}")
                    else:
                        print(f"   ⏸️ PENDING維持: {pending_pos.side}")
                return
            
            # ========== LLM逆転クローズチェック (FILLED ポジション) ==========
            if _check_reversal_exit:
                filled_pos = next(
                    (p for p in self.position_tracker.get_open_positions()
                     if p.market_id == market_id and p.order_filled
                     and not p.pending_sell_order_id),  # 売り注文約定待ち中は除外
                    None,
                )
                if filled_pos:
                    held_side = filled_pos.side.upper()
                    signal_side = signal.action.value.upper()
                    is_reversal = (
                        (held_side == "BUY_YES" and signal_side == "BUY_NO")
                        or (held_side == "BUY_NO" and signal_side == "BUY_YES")
                    )
                    if is_reversal and abs(signal.edge) >= self.config.min_edge and adjusted_confidence >= self.config.min_confidence:
                        current_price = getattr(market, 'yes_price', 0.5)
                        print(f"   🔄 LLM逆転クローズ: {held_side} → {signal_side} (edge={signal.edge:+.1%} conf={adjusted_confidence:.0%})")
                        await self._exit_position(filled_pos, "llm_reversal", current_price)
                    else:
                        print(f"   ⏸️ HOLD継続: edge={signal.edge:+.1%} conf={adjusted_confidence:.0%} (逆転={is_reversal})")
                return  # 逆転チェック完了、新規発注はしない

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
            
            # 即時発注
            await self._execute_order(market, signal, size, pending_pos)
            
        except Exception as e:
            print(f"   ❌ エラー: {e}")

    async def _cancel_pending_order(self, pos, reason: str):
        """PENDING GTC注文をキャンセル"""
        print(f"   🗑️ PENDING注文キャンセル ({reason}): {pos.question[:40]}")
        if pos.order_id:
            try:
                from client import PolyClient
                client = PolyClient()
                client.connect()
                result = client.cancel_order(pos.order_id)
                if result.success:
                    print(f"   ✅ キャンセル成功: {pos.order_id[:16]}...")
                else:
                    print(f"   ⚠️ キャンセル失敗: {result.message}")
            except Exception as e:
                print(f"   ⚠️ キャンセルエラー: {e}")
        self.position_tracker.remove_position(pos.id)
        if pos.market_id in self.risk_manager.open_positions:
            del self.risk_manager.open_positions[pos.market_id]
        self.executed_markets.discard(pos.market_id)
        self._log_event("order_cancelled", {
            "market_id": pos.market_id,
            "question": pos.question[:60],
            "side": pos.side,
            "reason": reason,
        })

    def _direct_close_position(self, pos, current_price: float, reason: str):
        """ポジションを直接クローズ (CLOB売り省略)"""
        realized_pnl = pos.calculate_unrealized_pnl(current_price)
        self.position_tracker.close_position(pos.id, current_price, realized_pnl)
        if pos.market_id in self.risk_manager.open_positions:
            del self.risk_manager.open_positions[pos.market_id]
        self.executed_markets.discard(pos.market_id)
        self._log_event("position_exited", {
            "market_id": pos.market_id,
            "question": pos.question[:60],
            "reason": reason,
            "exit_price": round(current_price, 6),
            "realized_pnl": round(realized_pnl, 4),
            "direct_close": True,
        })
        print(f"   💀 直接クローズ (CLOB売り省略): PnL ${realized_pnl:+.2f}")

    async def _exit_position(self, pos, reason: str, current_price: float):
        """ポジションを早期クローズ (利確 / 損切り / LLM逆転)"""
        _label = {"take_profit": "💰 利確", "stop_loss": "🛑 損切り", "llm_reversal": "🔄 LLM逆転"}.get(reason, f"📤 {reason}")
        print(f"\n{_label}: {pos.question[:40]}")

        exit_side = "SELL_YES" if "YES" in pos.side.upper() else "SELL_NO"
        sell_price = current_price if "YES" in exit_side else (1.0 - current_price)

        # ── 残存価値が極めて低い場合は直接クローズ (CLOB売りは流動性なし) ──────
        # 崩壊した側のトークンは買い手がおらず GTC が LIVE で放置されるのを防ぐ
        DIRECT_CLOSE_THRESHOLD = 2.0  # USD
        if "YES" in exit_side:
            estimated_value = pos.size * sell_price / pos.entry_price if pos.entry_price > 0 else 0.0
        else:
            entry_no_price = 1.0 - pos.entry_price
            estimated_value = pos.size * sell_price / entry_no_price if entry_no_price > 0 else 0.0
        if estimated_value < DIRECT_CLOSE_THRESHOLD:
            print(f"   ⚠️ 残存価値 ${estimated_value:.2f} < ${DIRECT_CLOSE_THRESHOLD} → CLOB売り省略")
            self._direct_close_position(pos, current_price, reason)
            return

        # 実トークン残高補正は execute_order 内で接続後に実施
        try:
            result = await self.executor.execute_order(
                market_id=pos.market_id,
                token_id=pos.token_id,
                side=exit_side,
                size=pos.size,
                price=sell_price,
            )
            if result.success:
                # GTC売り注文発注成功 → PENDING_SELL 状態に移行
                # 約定確認は _check_pending_gtc_orders で行い、確認後に close_position()
                sell_order_id = result.order_id or ""
                if not sell_order_id:
                    # order_id が取れなかった場合は追跡不可 → 手動フラグ
                    self.position_tracker.mark_needs_manual_sale(pos.id)
                    print(f"   ⚠️ order_id 未取得のため手動売却フラグをセット: {pos.question[:40]}")
                else:
                    self.position_tracker.mark_pending_sell(pos.id, sell_order_id, current_price)
                    print(f"   ⏳ 売り注文発注済み (約定確認待ち): {pos.question[:40]}")
            else:
                msg = result.message or ""
                if "スキップ" in msg or "not enough" in msg.lower():
                    self.position_tracker.mark_needs_manual_sale(pos.id)
                    print(f"   ⚠️ 手動売却フラグをセット: {pos.question[:40]}")
                print(f"   ❌ クローズ失敗: {msg}")
        except Exception as e:
            print(f"   ❌ クローズエラー: {e}")

    async def _execute_order(self, market, signal, size: float, pending_pos=None):
        """GTC注文を即時発注"""
        # BUY_YES/SELL_YES は YES token、BUY_NO/SELL_NO は NO token
        if signal.action.value.upper() in ("BUY_YES", "SELL_YES"):
            token_id = getattr(market, 'yes_token_id', None)
        else:
            token_id = getattr(market, 'no_token_id', None) or getattr(market, 'yes_token_id', None)

        yes_token_id = getattr(market, 'yes_token_id', None)
        if not yes_token_id:
            return

        market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', str(id(market)))
        question = getattr(market, 'question', str(market))
        current_price = getattr(market, 'yes_price', 0.5)

        # 同方向のPENDINGがあれば維持
        if pending_pos:
            if pending_pos.side == signal.action.value:
                print(f"   ⏸️ PENDING維持: {pending_pos.side} @ {pending_pos.entry_price:.4f}")
                return
            # 反対方向 → キャンセルして再発注
            await self._cancel_pending_order(pending_pos, f"方向逆転: {pending_pos.side} → {signal.action.value}")

        # 最小注文サイズチェック (Polymarket 最小: 5 tokens)
        POLY_MIN_TOKENS = 5.0
        token_count = size / current_price if current_price > 0 else 0
        if token_count < POLY_MIN_TOKENS:
            print(f"   ⚪ 発注サイズ不足 ({token_count:.2f} tokens < {POLY_MIN_TOKENS:.0f} 最小, ${size:.2f} @ {current_price:.4f})")
            return

        # エクスポージャーチェック
        if not self.risk_manager.can_add_position(size):
            exposure_ratio = self.risk_manager.get_exposure_ratio()
            print(f"   ⚠️ エクスポージャー上限 ({exposure_ratio:.0%} / {self.risk_manager.max_total_exposure:.0%})")
            return

        print(f"   🚀 即時発注: {signal.action.value} @ {current_price:.4f} ${size:.2f}")

        self._log_event("order_placed", {
            "market_id": market_id,
            "question": question[:60],
            "side": signal.action.value,
            "price": round(current_price, 6),
            "size": round(size, 2),
        })

        try:
            result = await self.executor.execute_order(
                market_id=market_id,
                token_id=token_id,
                side=signal.action.value,
                size=size,
                price=current_price,
            )

            self.stats["trades_executed"] += 1

            if result.success:
                self.stats["trades_success"] += 1
                print(f"   ✅ 発注成功: {result.message}")
                self.executed_markets.add(market_id)

                entry_price = result.executed_price if result.executed_price is not None else current_price
                if "NO" in signal.action.value.upper() and result.executed_price is not None:
                    entry_price = 1.0 - result.executed_price

                self.position_tracker.record_trade(
                    market_id=market_id,
                    token_id=token_id,
                    yes_token_id=yes_token_id,
                    question=question,
                    side=signal.action.value,
                    entry_price=entry_price,
                    size=size,
                    order_id=result.order_id,
                    order_filled=False,
                    entry_edge=signal.edge,
                )

                self.risk_manager.add_pending_exposure(size)

                # LLM判断をキャッシュ
                self._save_llm_judgment(token_id, signal)

                # ファクター記録
                active_factors = self.factor_manager.get_active_factors()
                if active_factors:
                    factor = active_factors[0]
                    self.factor_manager.record_trade(
                        factor_id=factor.hypothesis.id,
                        pnl=0,
                        entry_price=entry_price,
                        market_id=market_id,
                    )

                if self.stats["trades_success"] % 50 == 0:
                    asyncio.create_task(self._mine_new_factor())

                if self.dashboard:
                    await self.dashboard.push_trade({
                        "question": question[:50],
                        "side": signal.action.value,
                        "price": current_price,
                        "size": size,
                        "success": True,
                    })
            else:
                print(f"   ❌ 発注失敗: {result.message}")
                self._log_event("order_placed", {
                    "market_id": market_id,
                    "question": question[:60],
                    "side": signal.action.value,
                    "price": round(current_price, 6),
                    "size": round(size, 2),
                    "success": False,
                    "error": result.message,
                })

        except Exception as e:
            print(f"   ❌ 発注エラー: {e}")

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
                if status in ("MATCHED", "FILLED"):
                    self.position_tracker.mark_order_filled(pos.id)
                    print(f"   ✅ GTC約定確認 (active_ids): {pos.question[:40]}")
                elif status is None:
                    pass  # 取得失敗: スキップして次ループで再確認
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
                # 取得失敗 or 不明 → スキップして次ループで再確認
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
                    # 旧ポジション: ナイーブなローカル時刻 → UTC に正しく変換
                    created = created.astimezone(timezone.utc)
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
                else:
                    print(f"   ⏳ PENDING継続 ({elapsed_min:.0f}分経過 / {gtc_cancel_minutes}分でキャンセル): {pos.question[:40]}")

        # ── GTC売り注文の約定確認 ──────────────────────────────────────────
        pending_sell = self.position_tracker.get_pending_sell_positions()
        for pos in pending_sell:
            if not pos.pending_sell_order_id:
                continue

            if active_ids is not None and pos.pending_sell_order_id not in active_ids:
                order = client.get_order(pos.pending_sell_order_id)
                sell_status = _order_status(order)
            else:
                order = client.get_order(pos.pending_sell_order_id)
                sell_status = _order_status(order)

            if sell_status in ("MATCHED", "FILLED"):
                exit_price = pos.pending_sell_price or pos.entry_price
                realized_pnl = pos.calculate_unrealized_pnl(exit_price)
                self.position_tracker.close_position(pos.id, exit_price, realized_pnl)
                if pos.market_id in self.risk_manager.open_positions:
                    del self.risk_manager.open_positions[pos.market_id]
                self.executed_markets.discard(pos.market_id)
                self._log_event("position_exited", {
                    "market_id": pos.market_id,
                    "question": pos.question[:60],
                    "reason": "sell_confirmed",
                    "exit_price": round(exit_price, 6),
                    "realized_pnl": round(realized_pnl, 4),
                })
                print(f"   ✅ 売り約定確認・CLOSED: {pos.question[:40]} PnL: ${realized_pnl:+.2f}")

            elif sell_status == "CANCELLED":
                self.position_tracker.cancel_pending_sell(pos.id)
                print(f"   ↩️ 売り注文キャンセル検出 → ACTIVE復帰: {pos.question[:40]}")

            elif sell_status == "LIVE":
                created = pos.created_at
                if created.tzinfo is None:
                    created = created.astimezone(timezone.utc)
                elapsed_min = (now - created).total_seconds() / 60
                if elapsed_min > gtc_cancel_minutes:
                    result = client.cancel_order(pos.pending_sell_order_id)
                    if result.success:
                        self.position_tracker.cancel_pending_sell(pos.id)
                        print(f"   ↩️ 売り注文タイムアウトキャンセル ({elapsed_min:.0f}分) → ACTIVE復帰: {pos.question[:40]}")
                    else:
                        print(f"   ⚠️ 売り注文キャンセル失敗: {result.message}")
                else:
                    print(f"   ⏳ 売り注文待機中 ({elapsed_min:.0f}分経過): {pos.question[:40]}")

    async def _check_resolved_markets(self):
        """解決済みマーケットをチェックしてPnL確定・自動クローズ"""
        open_market_ids = self.position_tracker.get_open_market_ids()

        # ポジションなしでも Brier 予測が未解決のマーケットを追加チェック
        brier_unresolved = self.brier_tracker.get_unresolved_market_ids()
        brier_only_ids = [mid for mid in brier_unresolved if mid not in open_market_ids]

        if not open_market_ids and not brier_only_ids:
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

                    # BrierTrackerに実結果を記録
                    self.brier_tracker.record_outcome(market_id, round(resolution))

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

            # ========== ポジションなし・Brierのみ未解決マーケット ==========
            for market_id in brier_only_ids:
                try:
                    market_data = _pc.get_market(market_id)
                    if not market_data or not market_data.get("closed"):
                        continue  # まだ未解決

                    # yes_token_id を brier_tracker から取得
                    yes_token_id = self.brier_tracker.get_yes_token_id(market_id)
                    if not yes_token_id:
                        continue  # token_id 不明 → スキップ

                    last_price = _pc.get_last_trade_price(yes_token_id)
                    if last_price is None:
                        continue

                    # YES token の last_price = resolution
                    resolution = last_price
                    self.brier_tracker.record_outcome(market_id, round(resolution))
                    outcome_str = "YES" if resolution >= 0.5 else "NO"
                    print(f"📊 Brier解決記録: {outcome_str} (market={market_id[:12]}... resolution={resolution:.3f})")

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
        """利確・損切りをチェック (常時有効、条件で制御)"""
        open_positions = self.position_tracker.get_open_positions()
        if not open_positions:
            return

        # 現在価格 / end_date を market_id → value で収集
        current_prices = {}
        end_dates = {}
        for market in markets:
            market_id = getattr(market, 'market_id', None) or getattr(market, 'condition_id', None)
            yes_price = getattr(market, 'yes_price', None)
            end_date = getattr(market, 'end_date', None)
            if market_id:
                if yes_price:
                    current_prices[market_id] = yes_price
                if end_date:
                    end_dates[market_id] = end_date

        # _last_markets にないポジションは CLOB midpoint で価格を補完
        missing = [p for p in open_positions if p.order_filled and p.market_id not in current_prices]
        if missing:
            try:
                from client import PolyClient
                _pc = PolyClient()
                _pc.connect(read_only=True)
                for pos in missing:
                    tok = pos.yes_token_id or pos.token_id
                    if tok:
                        mid = _pc.get_midpoint(tok)
                        if mid is not None:
                            current_prices[pos.market_id] = mid
            except Exception:
                pass

        # 利確・損切り候補を取得
        exit_signals = self.position_tracker.check_exit_conditions(
            current_prices=current_prices,
            take_profit_pct=self.config.take_profit_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            collapse_threshold=self.config.collapse_threshold,
            stop_loss_near_expiry_days=self.config.stop_loss_near_expiry_days,
            stop_loss_near_expiry_pct=self.config.stop_loss_near_expiry_pct,
            end_dates=end_dates,
            last_signals=self._last_signals,
            edge_take_profit_threshold=self.config.edge_take_profit_threshold,
        )

        now = datetime.now(timezone.utc)

        # exit_signals に含まれないACTIVEポジション = HOLD継続 → ログ出力
        exit_market_ids = {es["position"].market_id for es in exit_signals}
        for pos in open_positions:
            if not pos.order_filled:
                continue  # PENDING は _check_pending_gtc_orders で処理
            if pos.pending_sell_order_id:
                continue  # 売り注文約定待ち中
            if pos.market_id in exit_market_ids:
                continue  # 以下で個別ログ出力
            yes_price = current_prices.get(pos.market_id, pos.entry_price)
            pnl_pct = pos.get_unrealized_pnl_pct(yes_price)
            end_date = end_dates.get(pos.market_id)
            days_left_str = f" {((end_date - now).total_seconds()/86400):.0f}d残" if end_date else ""
            print(f"   ⏸️ HOLD: {pos.question[:40]} (pnl={pnl_pct:+.1%}{days_left_str})")

        for exit_signal in exit_signals:
            pos = exit_signal["position"]
            if pos.pending_sell_order_id:
                continue  # 売り注文約定待ち中 → 再発注しない
            reason = exit_signal["reason"]
            pnl_pct = exit_signal["pnl_pct"]
            yes_price = current_prices.get(pos.market_id, 0.5)

            _icons = {"take_profit": "💰", "edge_take_profit": "🎯", "collapse_stop": "💥", "near_expiry_stop": "⏰", "stop_loss": "🛑"}
            _labels = {"take_profit": "利確", "edge_take_profit": "エッジ消失利確", "collapse_stop": "確率崩壊ストップ", "near_expiry_stop": "近解決損切り", "stop_loss": "損切り"}
            detail = exit_signal.get("detail", "")
            print(f"\n{_icons.get(reason,'🛑')} {_labels.get(reason,'損切り')}候補: {pos.question[:40]} ({pnl_pct:+.1%}) {detail}")

            # 価格ベース利確のみ: 解決まで14日超のときのみ実行 (スプレッドコストが割に合わない)
            # エッジ消失利確 (edge_take_profit) は14日制約なし — thesis消滅は即撤退
            if reason == "take_profit":
                end_date = end_dates.get(pos.market_id)
                if end_date:
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    days_left = (end_date - now).total_seconds() / 86400
                    if days_left <= self.config.take_profit_min_days:
                        print(f"   ⏸️ 利確スキップ (解決まで{days_left:.1f}日 ≤ {self.config.take_profit_min_days}日、HOLD継続)")
                        continue

            try:
                await self._exit_position(pos, reason, yes_price)
            except Exception as e:
                print(f"   ❌ _exit_position エラー (継続): {e}")
    
    def _build_open_positions_context(self) -> str:
        """保有中ポジション一覧を LLM の相関チェック用 context 文字列として生成"""
        positions = self.position_tracker.get_open_positions()
        filled = [p for p in positions if p.order_filled]
        if not filled:
            return ""
        lines = ["## 保有中のポジション (相関チェック用)"]
        for p in filled:
            lines.append(f'- "{p.question}" ({p.side.upper()})')
        return "\n".join(lines)

    def _classify_market_category(self, question: str) -> str:
        """マーケットをカテゴリ分類"""
        q = question.lower()
        if any(k in q for k in ["btc", "bitcoin", "eth", "ethereum", "crypto", "solana", "doge", "xrp"]):
            return "crypto"
        if any(k in q for k in ["election", "president", "prime minister", "vote", "poll", "senator", "governor"]):
            return "election"
        if any(k in q for k in ["war", "ceasefire", "troops", "military", "russia", "ukraine", "israel", "nato", "sanctions"]):
            return "geopolitical"
        return "other"

    def _build_performance_context(self) -> str:
        """
        過去の予測実績をまとめて LLM へのフィードバック context 文字列を生成。
        30分キャッシュ。解決済み10件未満の場合は空文字を返す。
        """
        now = datetime.now(timezone.utc)
        # キャッシュ有効期間: 30分
        if (self._perf_context_updated_at is not None and
                (now - self._perf_context_updated_at).total_seconds() < 1800):
            return self._perf_context_cache

        closed = self.position_tracker.get_closed_positions(limit=30)
        resolved = [p for p in closed if p.exit_price is not None]

        if len(resolved) < 10:
            self._perf_context_cache = ""
            self._perf_context_updated_at = now
            return ""

        # 勝敗判定: pnl > 0 = 勝ち
        wins = [p for p in resolved if p.pnl > 0]
        losses = [p for p in resolved if p.pnl <= 0]
        win_rate = len(wins) / len(resolved)
        avg_pnl = sum(p.pnl for p in resolved) / len(resolved)

        # カテゴリ別勝率
        cat_results: Dict[str, list] = {}
        for p in resolved:
            cat = self._classify_market_category(p.question)
            cat_results.setdefault(cat, []).append(p.pnl > 0)
        cat_lines = []
        for cat, results in sorted(cat_results.items()):
            rate = sum(results) / len(results)
            flag = " ⚠️ 注意" if rate < 0.45 else ""
            cat_lines.append(f"  - {cat}: 勝率{rate:.0%} ({len(results)}件){flag}")

        # 直近の外れパターン (最大5件)
        recent_losses = [p for p in resolved if p.pnl <= 0][:5]
        miss_lines = []
        for p in recent_losses:
            miss_lines.append(f"  - \"{p.question[:40]}\" {p.side} → 負け (PnL:{p.pnl:+.2f})")

        lines = [
            f"[あなたの過去{len(resolved)}件の予測実績]",
            f"勝率: {win_rate:.0%} ({len(wins)}勝/{len(losses)}敗) | 平均PnL: ${avg_pnl:+.2f}/件",
            "カテゴリ別:",
        ] + cat_lines

        if miss_lines:
            lines.append("直近の外れ予測:")
            lines += miss_lines

        lines.append("※ 苦手なカテゴリは特に保守的な確率推定を心がけてください。")

        context = "\n".join(lines)
        # 500文字上限
        if len(context) > 500:
            context = context[:497] + "..."

        self._perf_context_cache = context
        self._perf_context_updated_at = now

        cat_summary = " | ".join(f"{c}:{sum(r)/len(r):.0%}" for c, r in cat_results.items())
        print(f"   📊 LLM context: 過去{len(resolved)}件 勝率{win_rate:.0%} | {cat_summary}")

        return context

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

    async def _positions_loop(self):
        """1分ごとにPENDING確認・利確・損切り・ダッシュボード更新（分析ループとは独立）"""
        await asyncio.sleep(10)  # 起動直後は分析ループに任せる
        while self._running:
            try:
                pending_pos = self.position_tracker.get_pending_positions()
                active_pos  = self.position_tracker.get_open_positions()
                active_pos  = [p for p in active_pos if p.order_filled]
                now_str = datetime.now().strftime("%H:%M")
                print(f"\n[{now_str}] 📋 ポジション確認 — PENDING:{len(pending_pos)} ACTIVE:{len(active_pos)}")

                # GTC未約定注文のチェック・自動キャンセル
                await self._check_pending_gtc_orders()

                # 利確・損切りチェック
                await self._check_position_exits(self._last_markets)

                # ダッシュボード更新
                if self.dashboard:
                    await self._push_positions_to_dashboard(self._last_markets)
                    stats = self.position_tracker.get_stats()
                    await self.dashboard.update_state("pnl", stats["total_pnl"])
            except Exception as e:
                print(f"⚠️ positions_loop エラー: {e}")
            await asyncio.sleep(60)  # 1分ごと

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
                    "pos_id": pos.id,
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
                    "needs_manual_sale": pos.needs_manual_sale,
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

    async def _handle_dismiss_manual_sale(self, pos_id: str):
        """ダッシュボードからの手動売却アラート解除 → ポジションをCLOSEDにする"""
        pos = self.position_tracker.positions.get(pos_id)
        if not pos:
            return

        # _push_positions_to_dashboard と同じ優先順位で YES価格を取得
        # 1) _last_markets (スキャン結果) → open positions 表示と同じ価格
        # 2) CLOB 直接取得 (スキャン外マーケット)
        yes_price = pos.entry_price  # フォールバック
        found = False
        for m in self._last_markets:
            if getattr(m, "condition_id", None) == pos.market_id:
                price = getattr(m, "yes_price", None)
                if price:
                    yes_price = price
                    found = True
                break
        if not found:
            try:
                from client import PolyClient
                _pc = PolyClient()
                _pc.connect(read_only=True)
                fetch_token = pos.yes_token_id or pos.token_id
                mid = _pc.get_midpoint(fetch_token)
                if mid is not None:
                    if pos.yes_token_id:
                        yes_price = mid
                    else:
                        if "NO" in pos.side.upper():
                            yes_price = 1.0 - mid
                        elif abs(mid - (1.0 - pos.entry_price)) < abs(mid - pos.entry_price):
                            yes_price = 1.0 - mid
                        else:
                            yes_price = mid
            except Exception:
                pass

        estimated_pnl = pos.calculate_unrealized_pnl(yes_price)
        self.position_tracker.close_position(pos_id, exit_price=yes_price, realized_pnl=estimated_pnl)
        self.executed_markets.discard(pos.market_id)
        print(f"✅ 手動売却確認・クローズ: {pos.question[:40]} (推定PnL: ${estimated_pnl:+.2f})")

        if self.dashboard:
            await self._push_positions_to_dashboard(self._last_markets)
            await self._push_closed_positions_to_dashboard()


# CLI用ヘルパー
async def run_orchestrator(
    mode: str = "dry_run",
    model: str = "claude-haiku-4-5-20251001",
    min_edge: float = 0.10,
    max_markets: int = 10,
    fetch_news: bool = True,
    dashboard: bool = True,
    dashboard_port: int = 8080,
    take_profit_pct: float = 0.40,
    stop_loss_pct: float = -0.50,
    take_profit_min_days: int = 14,
    llm_reversal_exit: bool = True,
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
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_min_days=take_profit_min_days,
        llm_reversal_exit=llm_reversal_exit,
        auto_retrain=auto_retrain,
        retrain_threshold=retrain_threshold,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
    )

    orchestrator = Orchestrator(config)
    await orchestrator.start()
