"""
Base Strategy - 戦略の基底クラス
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class Action(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    """売買シグナル"""
    action: Action
    market_id: str
    token_id: str
    outcome: str  # "Yes" or "No"
    confidence: float  # 0.0 ~ 1.0
    target_price: Optional[float] = None
    amount: Optional[float] = None
    reason: str = ""


class BaseStrategy(ABC):
    """戦略基底クラス"""
    
    name: str = "Base"
    
    @abstractmethod
    def analyze(self, market_data: dict) -> Optional[Signal]:
        """
        マーケットを分析してシグナルを生成
        
        Args:
            market_data: マーケット情報 (質問、価格、ボリューム等)
        
        Returns:
            Signal or None (シグナルなしの場合)
        """
        pass
    
    def filter_markets(self, markets: List[dict]) -> List[dict]:
        """
        分析対象のマーケットをフィルタリング
        
        デフォルト: 全マーケットを対象
        """
        return markets
    
    def calculate_position_size(
        self,
        balance: float,
        confidence: float,
        max_position_pct: float = 0.1,
    ) -> float:
        """
        ポジションサイズを計算
        
        Args:
            balance: 利用可能残高
            confidence: シグナル信頼度
            max_position_pct: 最大ポジション比率
        
        Returns:
            ポジションサイズ (USDC)
        """
        # 信頼度に応じてサイズを調整
        # confidence 0.5 → 25% of max
        # confidence 1.0 → 100% of max
        size_pct = max_position_pct * (confidence * 0.75 + 0.25)
        return balance * size_pct
