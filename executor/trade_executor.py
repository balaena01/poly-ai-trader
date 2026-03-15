"""
Trade Executor
- シグナルに基づいて注文を実行
- リトライ機能
- ドライランモード
"""
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from dotenv import load_dotenv

from client import PolyClient
from analyst.llm_analyst import Signal, Action

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
    ):
        """
        Trade Executor 初期化
        
        Args:
            dry_run: True = 実際の注文を出さない
            max_retries: 最大リトライ回数
            default_amount: デフォルト注文金額
        """
        self.dry_run = dry_run
        self.max_retries = max_retries
        self.default_amount = default_amount
        
        self._client = None
        self._connected = False
        
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
    ) -> ExecutionResult:
        """
        シグナルに基づいて注文を実行
        
        Args:
            signal: 売買シグナル
            amount: 注文金額 (None = 自動計算)
        
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
        
        # 金額計算
        if amount is None:
            amount = self.calculate_amount(signal)
        
        # 価格決定 (指値 or 成行)
        # シンプル版: 現在価格で指値
        if signal.action == Action.BUY_YES:
            price = signal.market_price
        elif signal.action == Action.BUY_NO:
            price = 1 - signal.market_price
        else:
            price = None
        
        # ドライラン
        if self.dry_run:
            result = ExecutionResult(
                success=True,
                signal=signal,
                order_id="DRY_RUN",
                executed_price=price,
                executed_amount=amount,
                message=f"[DRY RUN] {signal.action.value} ${amount:.2f} @ {price:.1%}",
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
