"""
Risk Manager
- Quarter Kelly サイジング
- 連敗停止
- ドローダウン制限
- 相関キャップ
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PositionSize:
    """ポジションサイズ計算結果"""
    amount: float               # 推奨金額 (USDC)
    kelly_fraction: float       # Kelly比率
    applied_fraction: float     # 適用比率 (Quarter Kelly等)
    risk_adjusted: bool         # リスク調整されたか
    reason: str = ""


@dataclass
class RiskCheck:
    """リスクチェック結果"""
    allowed: bool               # 取引許可
    risk_level: RiskLevel
    position_size: Optional[PositionSize] = None
    warnings: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "allowed": self.allowed,
            "risk_level": self.risk_level.value,
            "position_size": self.position_size.amount if self.position_size else 0,
            "warnings": self.warnings,
            "blocks": self.blocks,
        }


@dataclass
class TradeRecord:
    """取引記録"""
    timestamp: datetime
    market_id: str
    symbol: str             # "BTC" or "ETH" 等
    side: str               # "buy" or "sell"
    amount: float
    price: float
    pnl: float = 0          # 実現損益
    is_win: bool = None


class RiskManager:
    """リスク管理"""
    
    def __init__(
        self,
        initial_balance: float = 1000,
        
        # Kelly設定
        kelly_fraction: float = 0.25,   # Quarter Kelly
        max_position_pct: float = 0.10, # 最大10%
        min_position: float = 1.0,      # 最小$1
        
        # 連敗設定
        max_consecutive_losses: int = 3,
        
        # ドローダウン設定
        max_drawdown_pct: float = 0.15, # 15%で停止
        
        # 相関設定
        max_correlated_exposure: float = 0.20,  # 相関資産の最大エクスポージャー
    ):
        """
        初期化
        
        Args:
            initial_balance: 初期残高
            kelly_fraction: Kelly比率 (0.25 = Quarter Kelly)
            max_position_pct: 1ポジションの最大比率
            min_position: 最小ポジションサイズ
            max_consecutive_losses: 連敗停止閾値
            max_drawdown_pct: 最大ドローダウン
            max_correlated_exposure: 相関資産の最大エクスポージャー
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.min_position = min_position
        
        self.max_consecutive_losses = max_consecutive_losses
        self.max_drawdown_pct = max_drawdown_pct
        self.max_correlated_exposure = max_correlated_exposure
        
        # 取引履歴
        self.trade_history: List[TradeRecord] = []
        
        # 現在のポジション
        self.open_positions: Dict[str, Dict] = {}  # market_id -> {symbol, amount, ...}
        
        # 状態
        self.consecutive_losses = 0
        self.is_shutdown = False
        self.shutdown_reason = ""
    
    # ========== 残高管理 ==========
    
    def update_balance(self, new_balance: float):
        """残高を更新"""
        self.current_balance = new_balance
        
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance
    
    def get_drawdown(self) -> float:
        """現在のドローダウン率を取得"""
        if self.peak_balance == 0:
            return 0
        return (self.peak_balance - self.current_balance) / self.peak_balance
    
    # ========== Kelly サイジング ==========
    
    def calculate_kelly(
        self,
        win_prob: float,
        win_amount: float,
        loss_amount: float,
    ) -> float:
        """
        Kelly Criterion を計算
        
        f* = (p * b - q) / b
        
        where:
            p = 勝率
            q = 1 - p
            b = 勝った時の倍率 (win_amount / loss_amount)
        
        Args:
            win_prob: 勝率
            win_amount: 勝った時の利益
            loss_amount: 負けた時の損失
        
        Returns:
            Kelly fraction (0-1)
        """
        if loss_amount == 0:
            return 0
        
        p = win_prob
        q = 1 - p
        b = win_amount / loss_amount
        
        kelly = (p * b - q) / b
        
        # 負のKellyは0にクリップ
        return max(0, kelly)
    
    def calculate_position_size(
        self,
        edge: float,
        confidence: float,
        market_price: float,
    ) -> PositionSize:
        """
        ポジションサイズを計算
        
        Args:
            edge: エッジ (例: 0.15 = 15%)
            confidence: 信頼度 (0-1)
            market_price: マーケット価格
        
        Returns:
            PositionSize
        """
        # 期待リターン計算
        # YES を買う場合: 勝てば (1 - price) / price のリターン
        # 負ければ -1 (全損)
        
        if edge > 0:
            # BUY YES
            win_return = (1 - market_price) / market_price
        else:
            # BUY NO
            win_return = market_price / (1 - market_price)
        
        win_prob = 0.5 + abs(edge) / 2  # エッジを勝率に変換
        win_prob = min(0.95, max(0.5, win_prob))  # 50-95%にクリップ
        
        # Kelly計算
        raw_kelly = self.calculate_kelly(win_prob, win_return, 1.0)
        
        # Quarter Kelly適用
        applied_kelly = raw_kelly * self.kelly_fraction
        
        # 信頼度で調整
        applied_kelly *= confidence
        
        # 最大比率でキャップ
        applied_kelly = min(applied_kelly, self.max_position_pct)
        
        # 金額計算
        amount = self.current_balance * applied_kelly
        
        # 最小/最大制限
        amount = max(self.min_position, amount)
        amount = min(self.current_balance * self.max_position_pct, amount)
        
        risk_adjusted = applied_kelly < raw_kelly * self.kelly_fraction
        
        return PositionSize(
            amount=round(amount, 2),
            kelly_fraction=raw_kelly,
            applied_fraction=applied_kelly,
            risk_adjusted=risk_adjusted,
            reason="Quarter Kelly" if not risk_adjusted else "Risk adjusted",
        )
    
    # ========== リスクチェック ==========
    
    def check_trade(
        self,
        market_id: str,
        symbol: str,
        edge: float,
        confidence: float,
        market_price: float,
    ) -> RiskCheck:
        """
        取引前のリスクチェック
        
        Args:
            market_id: マーケットID
            symbol: シンボル (BTC, ETH等)
            edge: エッジ
            confidence: 信頼度
            market_price: マーケット価格
        
        Returns:
            RiskCheck
        """
        warnings = []
        blocks = []
        
        # ========== シャットダウン確認 ==========
        if self.is_shutdown:
            return RiskCheck(
                allowed=False,
                risk_level=RiskLevel.CRITICAL,
                blocks=[f"システム停止中: {self.shutdown_reason}"],
            )
        
        # ========== ドローダウン確認 ==========
        drawdown = self.get_drawdown()
        if drawdown >= self.max_drawdown_pct:
            self.is_shutdown = True
            self.shutdown_reason = f"最大ドローダウン超過 ({drawdown:.1%})"
            return RiskCheck(
                allowed=False,
                risk_level=RiskLevel.CRITICAL,
                blocks=[self.shutdown_reason],
            )
        
        if drawdown >= self.max_drawdown_pct * 0.8:
            warnings.append(f"ドローダウン警告: {drawdown:.1%}")
        
        # ========== 連敗確認 ==========
        if self.consecutive_losses >= self.max_consecutive_losses:
            return RiskCheck(
                allowed=False,
                risk_level=RiskLevel.HIGH,
                blocks=[f"連敗停止: {self.consecutive_losses}連敗"],
            )
        
        if self.consecutive_losses >= self.max_consecutive_losses - 1:
            warnings.append(f"連敗警告: {self.consecutive_losses}連敗中")
        
        # ========== 相関エクスポージャー確認 ==========
        symbol_exposure = self._get_symbol_exposure(symbol)
        if symbol_exposure >= self.max_correlated_exposure:
            return RiskCheck(
                allowed=False,
                risk_level=RiskLevel.HIGH,
                blocks=[f"{symbol} エクスポージャー超過: {symbol_exposure:.1%}"],
            )
        
        if symbol_exposure >= self.max_correlated_exposure * 0.8:
            warnings.append(f"{symbol} エクスポージャー警告: {symbol_exposure:.1%}")
        
        # ========== ポジションサイズ計算 ==========
        position_size = self.calculate_position_size(edge, confidence, market_price)
        
        # 残高チェック
        if position_size.amount > self.current_balance * 0.9:
            blocks.append("残高不足")
            return RiskCheck(
                allowed=False,
                risk_level=RiskLevel.HIGH,
                position_size=position_size,
                warnings=warnings,
                blocks=blocks,
            )
        
        # ========== リスクレベル判定 ==========
        if warnings:
            risk_level = RiskLevel.MEDIUM
        elif drawdown > 0.05:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW
        
        return RiskCheck(
            allowed=len(blocks) == 0,
            risk_level=risk_level,
            position_size=position_size,
            warnings=warnings,
            blocks=blocks,
        )
    
    def _get_symbol_exposure(self, symbol: str) -> float:
        """特定シンボルへのエクスポージャーを計算"""
        total = sum(
            pos.get("amount", 0)
            for pos in self.open_positions.values()
            if pos.get("symbol") == symbol
        )
        
        if self.current_balance == 0:
            return 0
        
        return total / self.current_balance
    
    # ========== 取引記録 ==========
    
    def record_trade(
        self,
        market_id: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ):
        """取引を記録"""
        record = TradeRecord(
            timestamp=datetime.now(),
            market_id=market_id,
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
        )
        
        self.trade_history.append(record)
        
        # オープンポジションに追加
        self.open_positions[market_id] = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "timestamp": datetime.now(),
        }
    
    def record_close(
        self,
        market_id: str,
        pnl: float,
    ):
        """クローズを記録"""
        if market_id in self.open_positions:
            del self.open_positions[market_id]
        
        # 直近の取引を更新
        for record in reversed(self.trade_history):
            if record.market_id == market_id and record.pnl == 0:
                record.pnl = pnl
                record.is_win = pnl > 0
                break
        
        # 連敗カウント更新
        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        # 残高更新
        self.update_balance(self.current_balance + pnl)
    
    # ========== 統計 ==========
    
    def get_stats(self) -> Dict:
        """統計を取得"""
        closed_trades = [t for t in self.trade_history if t.is_win is not None]
        
        if not closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "drawdown": self.get_drawdown(),
                "consecutive_losses": self.consecutive_losses,
            }
        
        wins = sum(1 for t in closed_trades if t.is_win)
        total_pnl = sum(t.pnl for t in closed_trades)
        
        return {
            "total_trades": len(closed_trades),
            "wins": wins,
            "losses": len(closed_trades) - wins,
            "win_rate": wins / len(closed_trades),
            "total_pnl": total_pnl,
            "current_balance": self.current_balance,
            "peak_balance": self.peak_balance,
            "drawdown": self.get_drawdown(),
            "consecutive_losses": self.consecutive_losses,
            "is_shutdown": self.is_shutdown,
        }
    
    def reset_consecutive_losses(self):
        """連敗カウントをリセット (手動介入用)"""
        self.consecutive_losses = 0
    
    def resume(self):
        """シャットダウンを解除"""
        self.is_shutdown = False
        self.shutdown_reason = ""


# テスト
if __name__ == "__main__":
    print("💰 Risk Manager テスト\n")
    
    rm = RiskManager(initial_balance=1000)
    
    # ポジションサイズ計算
    print("📊 ポジションサイズ計算:")
    size = rm.calculate_position_size(edge=0.15, confidence=0.8, market_price=0.55)
    print(f"  Kelly: {size.kelly_fraction:.1%}")
    print(f"  適用: {size.applied_fraction:.1%}")
    print(f"  金額: ${size.amount:.2f}")
    
    # リスクチェック
    print("\n🔍 リスクチェック:")
    check = rm.check_trade(
        market_id="test",
        symbol="BTC",
        edge=0.15,
        confidence=0.8,
        market_price=0.55,
    )
    print(f"  許可: {check.allowed}")
    print(f"  リスクレベル: {check.risk_level.value}")
    print(f"  推奨サイズ: ${check.position_size.amount:.2f}")
    
    # 連敗シミュレーション
    print("\n📉 連敗シミュレーション:")
    for i in range(4):
        rm.record_trade("test", "BTC", "buy", 50, 0.55)
        rm.record_close("test", -50)
        check = rm.check_trade("test2", "BTC", 0.15, 0.8, 0.55)
        print(f"  {i+1}連敗: 許可={check.allowed}, ブロック={check.blocks}")
    
    print(f"\n📈 統計: {rm.get_stats()}")
