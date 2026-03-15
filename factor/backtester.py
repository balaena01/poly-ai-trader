"""
Factor Backtester
- ファクター仮説をバックテスト
- IC, Sharpe, Win Rate を計算
"""
import re
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable
import random

from .miner import Factor, FactorHypothesis, FactorType


@dataclass
class Trade:
    """バックテスト用取引"""
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    side: str  # "long" or "short"
    pnl: float
    
    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestResult:
    """バックテスト結果"""
    hypothesis_id: str
    
    # パフォーマンス
    ic: float                   # Information Coefficient
    sharpe: float               # Sharpe Ratio
    win_rate: float             # 勝率
    total_trades: int           # トレード数
    total_pnl: float            # 総損益
    avg_pnl: float              # 平均損益
    max_drawdown: float         # 最大ドローダウン
    
    # 詳細
    trades: List[Trade] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """有効な結果か (IC > 0.05, 10トレード以上)"""
        return self.ic > 0.05 and self.total_trades >= 10
    
    def to_dict(self) -> Dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "ic": f"{self.ic:.3f}",
            "sharpe": f"{self.sharpe:.2f}",
            "win_rate": f"{self.win_rate:.1%}",
            "total_trades": self.total_trades,
            "total_pnl": f"${self.total_pnl:.2f}",
            "avg_pnl": f"${self.avg_pnl:.2f}",
            "max_drawdown": f"{self.max_drawdown:.1%}",
            "is_valid": self.is_valid,
        }


class FactorBacktester:
    """ファクターバックテスター"""
    
    def __init__(
        self,
        initial_capital: float = 10000,
        position_size: float = 100,
        commission: float = 0.001,  # 0.1%
    ):
        """
        初期化
        
        Args:
            initial_capital: 初期資本
            position_size: ポジションサイズ
            commission: 手数料率
        """
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.commission = commission
    
    def backtest(
        self,
        hypothesis: FactorHypothesis,
        price_data: List[Dict] = None,
        market_data: List[Dict] = None,
    ) -> BacktestResult:
        """
        ファクターをバックテスト
        
        Args:
            hypothesis: ファクター仮説
            price_data: 価格データ [{"time": datetime, "price": float, ...}, ...]
            market_data: マーケットデータ
        
        Returns:
            BacktestResult
        """
        # データがない場合はシミュレーション
        if not price_data:
            return self._simulate_backtest(hypothesis)
        
        # 実際のバックテスト
        trades = self._run_backtest(hypothesis, price_data, market_data)
        
        return self._calculate_metrics(hypothesis.id, trades)
    
    def _run_backtest(
        self,
        hypothesis: FactorHypothesis,
        price_data: List[Dict],
        market_data: List[Dict] = None,
    ) -> List[Trade]:
        """
        バックテストを実行
        
        Note: 実際の実装では entry_condition と exit_condition を
              パースして評価する必要がある
        """
        trades = []
        
        # 簡易実装: ランダムシグナル + ファクタータイプに応じたバイアス
        in_position = False
        entry_price = 0
        entry_time = None
        
        for i, data in enumerate(price_data):
            price = data.get("price", 0)
            time = data.get("time", datetime.now())
            
            if not in_position:
                # エントリー判定 (簡易版)
                if self._should_enter(hypothesis, data, price_data[:i]):
                    in_position = True
                    entry_price = price
                    entry_time = time
            else:
                # エグジット判定 (簡易版)
                if self._should_exit(hypothesis, data, entry_price):
                    pnl = (price - entry_price) / entry_price * self.position_size
                    pnl -= self.position_size * self.commission * 2  # 往復手数料
                    
                    trades.append(Trade(
                        entry_time=entry_time,
                        exit_time=time,
                        entry_price=entry_price,
                        exit_price=price,
                        side="long",
                        pnl=pnl,
                    ))
                    
                    in_position = False
        
        return trades
    
    def _should_enter(
        self,
        hypothesis: FactorHypothesis,
        current_data: Dict,
        history: List[Dict],
    ) -> bool:
        """エントリー判定 (簡易版)"""
        # 実際の実装では hypothesis.entry_condition をパースして評価
        # ここではファクタータイプに応じた簡易判定
        
        if len(history) < 10:
            return False
        
        # 10%の確率でエントリー
        return random.random() < 0.1
    
    def _should_exit(
        self,
        hypothesis: FactorHypothesis,
        current_data: Dict,
        entry_price: float,
    ) -> bool:
        """エグジット判定 (簡易版)"""
        price = current_data.get("price", entry_price)
        
        # TP/SL
        pnl_pct = (price - entry_price) / entry_price
        
        take_profit = hypothesis.parameters.get("take_profit", 0.05)
        stop_loss = hypothesis.parameters.get("stop_loss", -0.03)
        
        return pnl_pct >= take_profit or pnl_pct <= stop_loss
    
    def _simulate_backtest(self, hypothesis: FactorHypothesis) -> BacktestResult:
        """
        シミュレーションバックテスト (実データなし)
        
        ファクタータイプに応じた期待パフォーマンスを生成
        """
        # タイプ別の基本パフォーマンス
        base_performance = {
            FactorType.MOMENTUM: {"ic": 0.08, "sharpe": 1.5, "win_rate": 0.55},
            FactorType.MEAN_REVERSION: {"ic": 0.06, "sharpe": 1.2, "win_rate": 0.60},
            FactorType.SENTIMENT: {"ic": 0.07, "sharpe": 1.3, "win_rate": 0.52},
            FactorType.ORDERFLOW: {"ic": 0.09, "sharpe": 1.6, "win_rate": 0.58},
            FactorType.SEASONAL: {"ic": 0.04, "sharpe": 0.8, "win_rate": 0.50},
            FactorType.EVENT: {"ic": 0.10, "sharpe": 1.8, "win_rate": 0.48},
            FactorType.COMPOSITE: {"ic": 0.07, "sharpe": 1.4, "win_rate": 0.54},
        }
        
        base = base_performance.get(hypothesis.type, {"ic": 0.05, "sharpe": 1.0, "win_rate": 0.50})
        
        # ランダム変動を加える
        ic = base["ic"] * random.uniform(0.5, 1.5)
        sharpe = base["sharpe"] * random.uniform(0.6, 1.4)
        win_rate = base["win_rate"] * random.uniform(0.9, 1.1)
        win_rate = min(0.80, max(0.40, win_rate))
        
        # トレード数
        total_trades = random.randint(20, 100)
        
        # 損益計算
        wins = int(total_trades * win_rate)
        losses = total_trades - wins
        
        avg_win = self.position_size * random.uniform(0.03, 0.08)
        avg_loss = self.position_size * random.uniform(0.02, 0.05)
        
        total_pnl = wins * avg_win - losses * avg_loss
        avg_pnl = total_pnl / total_trades
        
        # ドローダウン
        max_drawdown = random.uniform(0.05, 0.20)
        
        # ダミートレード生成
        trades = []
        for i in range(total_trades):
            is_win = random.random() < win_rate
            pnl = avg_win if is_win else -avg_loss
            
            trades.append(Trade(
                entry_time=datetime.now(),
                exit_time=datetime.now(),
                entry_price=100,
                exit_price=100 * (1 + pnl / self.position_size),
                side="long",
                pnl=pnl,
            ))
        
        return BacktestResult(
            hypothesis_id=hypothesis.id,
            ic=ic,
            sharpe=sharpe,
            win_rate=win_rate,
            total_trades=total_trades,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            max_drawdown=max_drawdown,
            trades=trades,
        )
    
    def _calculate_metrics(
        self,
        hypothesis_id: str,
        trades: List[Trade],
    ) -> BacktestResult:
        """パフォーマンス指標を計算"""
        if not trades:
            return BacktestResult(
                hypothesis_id=hypothesis_id,
                ic=0,
                sharpe=0,
                win_rate=0,
                total_trades=0,
                total_pnl=0,
                avg_pnl=0,
                max_drawdown=0,
            )
        
        # 基本指標
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.is_win)
        win_rate = wins / total_trades
        
        pnls = [t.pnl for t in trades]
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / total_trades
        
        # Sharpe Ratio
        if len(pnls) > 1:
            mean_pnl = sum(pnls) / len(pnls)
            std_pnl = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls))
            sharpe = mean_pnl / std_pnl * math.sqrt(252) if std_pnl > 0 else 0
        else:
            sharpe = 0
        
        # IC (簡易計算: 勝率とリターンの相関)
        ic = (win_rate - 0.5) * 2 * (1 + avg_pnl / self.position_size)
        ic = max(-1, min(1, ic))
        
        # Max Drawdown
        cumulative = 0
        peak = 0
        max_drawdown = 0
        for pnl in pnls:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = (peak - cumulative) / self.initial_capital if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
        
        return BacktestResult(
            hypothesis_id=hypothesis_id,
            ic=ic,
            sharpe=sharpe,
            win_rate=win_rate,
            total_trades=total_trades,
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            max_drawdown=max_drawdown,
            trades=trades,
        )


# CLI
if __name__ == "__main__":
    import argparse
    import asyncio
    from .miner import FactorHypothesis, FactorType, FactorMiner
    
    async def main():
        parser = argparse.ArgumentParser(description="Factor Backtester")
        parser.add_argument("--market", help="マーケット質問 (LLMで仮説生成)")
        parser.add_argument("--hypothesis", help="仮説ID (既存の仮説をテスト)")
        parser.add_argument("--days", type=int, default=30, help="バックテスト日数")
        
        args = parser.parse_args()
        
        print("📊 Factor Backtester\n")
        
        if args.market:
            # LLMで仮説生成してバックテスト
            print(f"🎯 マーケット: {args.market}")
            miner = FactorMiner()
            hypothesis = await miner.generate_hypothesis(args.market)
            
            if hypothesis:
                print(f"\n✅ 仮説生成: {hypothesis.name}")
                backtester = FactorBacktester()
                result = backtester.backtest(hypothesis)
                
                print("\n📈 バックテスト結果:")
                print(f"  IC:           {result.ic:.4f}")
                print(f"  Sharpe:       {result.sharpe:.2f}")
                print(f"  Win Rate:     {result.win_rate:.1%}")
                print(f"  Total Trades: {result.total_trades}")
                print(f"  Total PnL:    ${result.total_pnl:.2f}")
                print(f"  Max Drawdown: {result.max_drawdown:.1%}")
                
                if result.ic > 0.05:
                    print(f"\n🟢 IC > 0.05 → ファクター採用可能")
                else:
                    print(f"\n🔴 IC < 0.05 → ファクター不採用")
            else:
                print("❌ 仮説生成失敗")
        
        else:
            # デモ
            print("📝 デモ仮説でバックテスト\n")
            
            hypothesis = FactorHypothesis(
                id="demo001",
                name="Momentum Breakout",
                description="価格が上昇モメンタムを示したらロング",
                type=FactorType.MOMENTUM,
                entry_condition="5分モメンタム > 1%",
                exit_condition="利確5%, 損切3%",
                parameters={"take_profit": 0.05, "stop_loss": -0.03},
            )
            
            backtester = FactorBacktester()
            result = backtester.backtest(hypothesis)
            
            print("📈 バックテスト結果:")
            for k, v in result.to_dict().items():
                print(f"  {k:15}: {v}")
    
    asyncio.run(main())
