"""
Trade Executor
- シグナルに基づいて注文を実行
- リトライ機能
- ドライランモード
- リスク管理統合
"""
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from dotenv import load_dotenv

from client import PolyClient
from analyst.llm_analyst import Signal, Action
from risk import RiskManager, Auditor

load_dotenv()


@dataclass
class ExecutionResult:
    """実行結果"""
    success: bool
    signal: Signal
    order_id: Optional[str] = None
    executed_price: Optional[float] = None
    executed_amount: Optional[float] = None
    message: str = ""
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action": self.signal.action.value,
            "question": self.signal.question[:40],
            "order_id": self.order_id,
            "price": self.executed_price,
            "amount": self.executed_amount,
            "message": self.message,
        }


class TradeExecutor:
    """取引実行エンジン"""
    
    def __init__(
        self,
        dry_run: bool = True,
        max_retries: int = 3,
        default_amount: float = 10.0,  # USDC
        initial_balance: float = 1000,
        use_risk_manager: bool = True,
        use_auditor: bool = True,
    ):
        """
        Trade Executor 初期化
        
        Args:
            dry_run: True = 実際の注文を出さない
            max_retries: 最大リトライ回数
            default_amount: デフォルト注文金額
            initial_balance: 初期残高
            use_risk_manager: リスク管理を使用
            use_auditor: 監査を使用
        """
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.default_amount = default_amount
        
        self._client = None
        self._connected = False
        
        # リスク管理
        self.use_risk_manager = use_risk_manager
        self.risk_manager = RiskManager(initial_balance=initial_balance) if use_risk_manager else None
        
        # 監査
        self.use_auditor = use_auditor
        self.auditor = Auditor() if use_auditor else None
        
        # 実行履歴
        self.history: List[ExecutionResult] = []
    
    def connect(self) -> bool:
        """Polymarket に接続"""
        self._client = PolyClient()
        
        if self.dry_run:
            # ドライランは読み取り専用
            self._connected = self._client.connect(read_only=True)
            print("🔧 ドライランモード (注文は実行されません)")
        else:
            self._connected = self._client.connect()
        
        return self._connected
    
    def calculate_amount(
        self,
        signal: Signal,
        balance: float = None,
        max_position_pct: float = 0.10,
    ) -> float:
        """
        注文金額を計算
        
        Kelly Criterion (簡易版):
        f = (p * b - q) / b
        where:
          p = 勝率 (predicted_prob)
          q = 1 - p
          b = オッズ (1 / market_price - 1)
        
        Quarter Kelly を使用
        """
        if balance is None:
            balance = 1000  # デフォルト
        
        p = signal.predicted_prob
        q = 1 - p
        
        # オッズ計算
        if signal.action == Action.BUY_YES:
            b = (1 / signal.market_price) - 1
        else:
            b = (1 / (1 - signal.market_price)) - 1
        
        if b <= 0:
            return self.default_amount
        
        # Kelly fraction
        kelly = (p * b - q) / b
        
        # Quarter Kelly + max cap
        quarter_kelly = kelly * 0.25
        position_pct = min(quarter_kelly, max_position_pct)
        
        amount = balance * position_pct
        
        # 最小/最大制限
        amount = max(1, min(amount, balance * max_position_pct))
        
        return round(amount, 2)
    
    async def execute(
        self,
        signal: Signal,
        amount: float = None,
        market_liquidity: float = None,
        market_end_date = None,
        symbol: str = "CRYPTO",
    ) -> ExecutionResult:
        """
        シグナルに基づいて注文を実行
        
        Args:
            signal: 売買シグナル
            amount: 注文金額 (None = 自動計算)
            market_liquidity: マーケット流動性
            market_end_date: マーケット終了日時
            symbol: シンボル (相関管理用)
        
        Returns:
            ExecutionResult
        """
        if not self._connected:
            if not self.connect():
                return ExecutionResult(
                    success=False,
                    signal=signal,
                    message="接続エラー",
                )
        
        # HOLD は何もしない
        if signal.action == Action.HOLD:
            return ExecutionResult(
                success=True,
                signal=signal,
                message="HOLD - 取引なし",
            )
        
        # ========== 監査 ==========
        if self.use_auditor and self.auditor:
            audit_result = self.auditor.audit(
                market_id=signal.market_id,
                question=signal.question,
                liquidity=market_liquidity or 50000,
                end_date=market_end_date,
                llm_reasoning=signal.reasoning,
                original_confidence=signal.confidence,
            )
            
            if not audit_result.passed:
                return ExecutionResult(
                    success=False,
                    signal=signal,
                    message=f"監査ブロック: {[f.value for f in audit_result.flags]}",
                )
            
            # 信頼度を調整
            signal.confidence = audit_result.adjusted_confidence
        
        # ========== リスクチェック ==========
        if self.use_risk_manager and self.risk_manager:
            risk_check = self.risk_manager.check_trade(
                market_id=signal.market_id,
                symbol=symbol,
                edge=signal.edge,
                confidence=signal.confidence,
                market_price=signal.market_price,
            )
            
            if not risk_check.allowed:
                return ExecutionResult(
                    success=False,
                    signal=signal,
                    message=f"リスクブロック: {risk_check.blocks}",
                )
            
            # リスク管理からポジションサイズを取得
            if risk_check.position_size:
                amount = risk_check.position_size.amount
        
        # 金額計算 (リスク管理がない場合)
        if amount is None:
            amount = self.calculate_amount(signal)
        
        # 価格決定 (指値 or 成行)
        # シンプル版: 現在価格で指値
        if signal.action == Action.BUY_YES:
            price = signal.market_price
        elif signal.action == Action.BUY_NO:
            price = 1 - signal.market_price
        elif signal.action == Action.SELL_YES:
            price = signal.market_price
        elif signal.action == Action.SELL_NO:
            price = 1 - signal.market_price
        else:
            price = signal.market_price or 0.5  # フォールバック
        
        # ドライラン
        if self.dry_run:
            result = ExecutionResult(
                success=True,
                signal=signal,
                order_id="DRY_RUN",
                executed_price=price,
                executed_amount=amount,
                message=f"[DRY RUN] {signal.action.value} ${amount:.2f} @ {(price or 0):.1%}",
            )
            self.history.append(result)
            
            print(f"  🔧 {result.message}")
            return result
        
        # 実際の注文
        for attempt in range(1, self.max_retries + 1):
            try:
                if signal.action in (Action.BUY_YES, Action.BUY_NO):
                    trade_result = self._client.buy(
                        token_id=signal.token_id,
                        amount=amount,
                        price=price,
                    )
                else:
                    trade_result = self._client.sell(
                        token_id=signal.token_id,
                        amount=amount,
                        price=price,
                    )
                
                if trade_result.success:
                    result = ExecutionResult(
                        success=True,
                        signal=signal,
                        order_id=trade_result.order_id,
                        executed_price=price,
                        executed_amount=amount,
                        message=f"注文成功 (試行 {attempt})",
                    )
                    self.history.append(result)
                    
                    print(f"  ✅ {signal.action.value} ${amount:.2f} @ {price:.1%}")
                    return result
                
            except Exception as e:
                print(f"  ⚠️ 試行 {attempt} 失敗: {e}")
                
                if attempt < self.max_retries:
                    import asyncio
                    await asyncio.sleep(1)
        
        # 全リトライ失敗
        result = ExecutionResult(
            success=False,
            signal=signal,
            message=f"注文失敗 ({self.max_retries}回試行)",
        )
        self.history.append(result)
        
        return result
    
    async def execute_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> ExecutionResult:
        """
        シンプルな注文実行 (Orchestrator用)
        
        Args:
            market_id: マーケットID
            token_id: トークンID
            side: "BUY" or "SELL"
            size: サイズ (USDC)
            price: 価格
        
        Returns:
            ExecutionResult
        """
        # 接続確認
        if not self._connected:
            self.connect()

        # ── CLOB から実際のask/bid価格を取得 ──────────────────────────────
        # WebSocketのmidpointではなく板情報から約定可能な価格を使う。
        # BUY系 → ask価格 (出来値)、SELL系 → bid価格 (受け値)
        if self._connected and self._client:
            is_buy = side.upper() in ("BUY_YES", "BUY_NO")
            quote_side = "BUY" if is_buy else "SELL"
            try:
                live_price = self._client.get_price(token_id, side=quote_side)
                if live_price:
                    is_no_side = side.upper() in ("BUY_NO", "SELL_NO")
                    adjusted_price = (1 - live_price) if is_no_side else live_price
                    print(f"   📈 約定価格更新: {price:.4f} → {adjusted_price:.4f} (CLOB {quote_side}{'→YES換算' if is_no_side else ''})")
                    price = adjusted_price
            except Exception:
                pass  # 取得失敗時はWebSocket価格で続行
        # ─────────────────────────────────────────────────────────────────

        # Signal オブジェクト作成
        signal = Signal(
            market_id=market_id,
            token_id=token_id,
            question=f"Market {market_id[:16]}",
            action=Action[side.upper()] if side.upper() in Action.__members__ else Action.BUY_YES,
            market_price=price,
            predicted_prob=price,  # ダミー
            edge=0.1,  # ダミー
            confidence=0.8,  # ダミー
            reasoning="Trigger execution",
        )

        return await self.execute(signal, amount=size)
    
    async def execute_signals(
        self,
        signals: List[Signal],
        max_trades: int = 3,
    ) -> List[ExecutionResult]:
        """
        複数シグナルを実行
        
        Args:
            signals: シグナルリスト
            max_trades: 最大取引数
        
        Returns:
            ExecutionResult リスト
        """
        results = []
        trade_count = 0
        
        for signal in signals:
            # 取引可能なシグナルのみ
            if not signal.is_tradeable:
                continue
            
            if trade_count >= max_trades:
                break
            
            print(f"\n💰 実行: {signal.question[:40]}...")
            print(f"   アクション: {signal.action.value}")
            print(f"   エッジ: {signal.edge:+.1%}")
            
            result = await self.execute(signal)
            results.append(result)
            
            if result.success and signal.action != Action.HOLD:
                trade_count += 1
        
        return results
    
    def get_stats(self) -> dict:
        """実行統計を取得"""
        if not self.history:
            return {"total": 0}
        
        total = len(self.history)
        success = sum(1 for r in self.history if r.success)
        
        return {
            "total": total,
            "success": success,
            "fail": total - success,
            "success_rate": success / total if total > 0 else 0,
        }


# テスト用
async def _test():
    from scanner import MarketScanner
    from analyst import LLMAnalyst
    
    # スキャン
    scanner = MarketScanner()
    scan_result = await scanner.scan()
    
    # 分析
    analyst = LLMAnalyst()
    signals = await analyst.generate_signals(
        markets=scan_result.markets[:2],
        btc_price=scan_result.btc_price.price if scan_result.btc_price else None,
    )
    
    # 実行 (ドライラン)
    executor = TradeExecutor(dry_run=True)
    results = await executor.execute_signals(signals)
    
    print(f"\n📊 実行結果:")
    for r in results:
        print(f"  {r.to_dict()}")
    
    print(f"\n📈 統計: {executor.get_stats()}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_test())
