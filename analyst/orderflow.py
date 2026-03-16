"""
Orderflow Detector
- クジラ検出
- 流動性シフト
- 大口注文クラスタ
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import deque
import statistics


@dataclass
class Trade:
    """取引データ"""
    timestamp: datetime
    price: float
    size: float
    side: str  # "buy" or "sell"
    
    @property
    def value(self) -> float:
        return self.price * self.size


@dataclass
class OrderflowSignal:
    """オーダーフローシグナル"""
    timestamp: datetime
    
    # シグナル値 (-1 to 1)
    whale_signal: float = 0         # クジラ活動 (+買い優勢, -売り優勢)
    liquidity_signal: float = 0     # 流動性シフト (+増加, -減少)
    cluster_signal: float = 0       # 注文クラスタ (+買いクラスタ, -売りクラスタ)
    
    # 詳細
    whale_trades: int = 0           # クジラ取引数
    total_whale_value: float = 0    # クジラ取引総額
    liquidity_change_pct: float = 0 # 流動性変化率
    
    @property
    def composite_signal(self) -> float:
        """合成シグナル"""
        return (
            self.whale_signal * 0.4 +
            self.liquidity_signal * 0.3 +
            self.cluster_signal * 0.3
        )
    
    @property
    def confidence(self) -> float:
        """信頼度 (シグナルの強さ)"""
        return min(1.0, abs(self.composite_signal))
    
    def to_dict(self) -> Dict:
        return {
            "whale_signal": self.whale_signal,
            "liquidity_signal": self.liquidity_signal,
            "cluster_signal": self.cluster_signal,
            "composite": self.composite_signal,
            "confidence": self.confidence,
            "whale_trades": self.whale_trades,
        }


class OrderflowDetector:
    """オーダーフロー検出器"""
    
    def __init__(
        self,
        whale_threshold_usd: float = 10000,  # クジラ閾値 ($)
        lookback_minutes: int = 60,           # 分析期間 (分)
        cluster_window: int = 5,              # クラスタ検出ウィンドウ (分)
    ):
        """
        初期化
        
        Args:
            whale_threshold_usd: クジラとみなす取引額 ($)
            lookback_minutes: 分析対象期間
            cluster_window: クラスタ検出ウィンドウ
        """
        self.whale_threshold = whale_threshold_usd
        self.lookback_minutes = lookback_minutes
        self.cluster_window = cluster_window
        
        # 履歴
        self.trade_history: deque = deque(maxlen=10000)
        self.liquidity_history: deque = deque(maxlen=1000)
    
    def add_trade(self, trade: Trade):
        """取引を追加"""
        self.trade_history.append(trade)
    
    def add_trades(self, trades: List[Trade]):
        """複数取引を追加"""
        for t in trades:
            self.trade_history.append(t)
    
    def add_liquidity_snapshot(self, timestamp: datetime, total_liquidity: float):
        """流動性スナップショットを追加"""
        self.liquidity_history.append({
            "timestamp": timestamp,
            "liquidity": total_liquidity,
        })
    
    def detect_whales(self, trades: List[Trade] = None) -> Dict:
        """
        クジラ取引を検出

        Returns:
            {"buy_value": float, "sell_value": float, "signal": float, "trades": int}
        """
        if trades is None:
            cutoff = datetime.now() - timedelta(minutes=self.lookback_minutes)
            trades = [t for t in self.trade_history if t.timestamp > cutoff]

        # 動的閾値: max(絶対下限, ウィンドウ内総取引量の1%)
        # 流動性の小さいマーケットで全トレードがwhale判定されるのを防ぐ
        if trades:
            window_volume = sum(t.value for t in trades)
            dynamic_threshold = max(self.whale_threshold, window_volume * 0.01)
        else:
            dynamic_threshold = self.whale_threshold

        whale_trades = [t for t in trades if t.value >= dynamic_threshold]
        
        if not whale_trades:
            return {"buy_value": 0, "sell_value": 0, "signal": 0, "trades": 0}
        
        buy_value = sum(t.value for t in whale_trades if t.side == "buy")
        sell_value = sum(t.value for t in whale_trades if t.side == "sell")
        total = buy_value + sell_value
        
        # シグナル (-1 to 1)
        signal = (buy_value - sell_value) / total if total > 0 else 0
        
        return {
            "buy_value": buy_value,
            "sell_value": sell_value,
            "signal": signal,
            "trades": len(whale_trades),
        }
    
    def detect_liquidity_shift(self) -> Dict:
        """
        流動性シフトを検出
        
        Returns:
            {"change_pct": float, "signal": float}
        """
        if len(self.liquidity_history) < 2:
            return {"change_pct": 0, "signal": 0}
        
        # 直近と過去を比較
        recent = list(self.liquidity_history)[-5:]
        older = list(self.liquidity_history)[-20:-5] if len(self.liquidity_history) >= 20 else list(self.liquidity_history)[:5]
        
        if not recent or not older:
            return {"change_pct": 0, "signal": 0}
        
        recent_avg = statistics.mean(s["liquidity"] for s in recent)
        older_avg = statistics.mean(s["liquidity"] for s in older)
        
        if older_avg == 0:
            return {"change_pct": 0, "signal": 0}
        
        change_pct = (recent_avg - older_avg) / older_avg
        
        # シグナル (変化率を -1 to 1 にマップ)
        # +50% 以上 → +1, -50% 以下 → -1
        signal = max(-1, min(1, change_pct * 2))
        
        return {
            "change_pct": change_pct,
            "signal": signal,
        }
    
    def detect_order_clusters(self, trades: List[Trade] = None) -> Dict:
        """
        注文クラスタを検出
        
        短時間に同方向の注文が集中しているか
        
        Returns:
            {"buy_clusters": int, "sell_clusters": int, "signal": float}
        """
        if trades is None:
            cutoff = datetime.now() - timedelta(minutes=self.lookback_minutes)
            trades = [t for t in self.trade_history if t.timestamp > cutoff]
        
        if len(trades) < 5:
            return {"buy_clusters": 0, "sell_clusters": 0, "signal": 0}
        
        # 時間順ソート
        trades = sorted(trades, key=lambda t: t.timestamp)
        
        buy_clusters = 0
        sell_clusters = 0
        
        # スライディングウィンドウでクラスタ検出
        window = timedelta(minutes=self.cluster_window)
        
        i = 0
        while i < len(trades):
            # ウィンドウ内の取引を収集
            window_end = trades[i].timestamp + window
            window_trades = []
            j = i
            while j < len(trades) and trades[j].timestamp <= window_end:
                window_trades.append(trades[j])
                j += 1
            
            # クラスタ判定 (5件以上 & 80%以上が同方向)
            if len(window_trades) >= 5:
                buys = sum(1 for t in window_trades if t.side == "buy")
                sells = len(window_trades) - buys
                
                if buys / len(window_trades) >= 0.8:
                    buy_clusters += 1
                elif sells / len(window_trades) >= 0.8:
                    sell_clusters += 1
            
            i = j if j > i else i + 1
        
        total_clusters = buy_clusters + sell_clusters
        signal = (buy_clusters - sell_clusters) / total_clusters if total_clusters > 0 else 0
        
        return {
            "buy_clusters": buy_clusters,
            "sell_clusters": sell_clusters,
            "signal": signal,
        }
    
    def analyze(self, trades: List[Trade] = None) -> OrderflowSignal:
        """
        総合分析
        
        Args:
            trades: 取引リスト (Noneの場合は履歴から)
        
        Returns:
            OrderflowSignal
        """
        # 各シグナル計算
        whale_result = self.detect_whales(trades)
        liquidity_result = self.detect_liquidity_shift()
        cluster_result = self.detect_order_clusters(trades)
        
        return OrderflowSignal(
            timestamp=datetime.now(),
            whale_signal=whale_result["signal"],
            liquidity_signal=liquidity_result["signal"],
            cluster_signal=cluster_result["signal"],
            whale_trades=whale_result["trades"],
            total_whale_value=whale_result["buy_value"] + whale_result["sell_value"],
            liquidity_change_pct=liquidity_result["change_pct"],
        )


# テスト
if __name__ == "__main__":
    import random
    
    print("🐋 Orderflow Detector テスト\n")
    
    detector = OrderflowDetector(whale_threshold_usd=5000)
    
    # ダミー取引生成
    now = datetime.now()
    trades = []
    
    for i in range(100):
        t = Trade(
            timestamp=now - timedelta(minutes=random.randint(0, 60)),
            price=0.55 + random.uniform(-0.05, 0.05),
            size=random.uniform(100, 50000),  # 一部はクジラ
            side=random.choice(["buy", "buy", "buy", "sell"]),  # 買い優勢
        )
        trades.append(t)
    
    detector.add_trades(trades)
    
    # 流動性履歴追加
    for i in range(20):
        detector.add_liquidity_snapshot(
            now - timedelta(minutes=i * 5),
            100000 + i * 2000,  # 増加トレンド
        )
    
    # 分析
    signal = detector.analyze()
    
    print("📊 オーダーフロー分析:")
    print(f"  クジラシグナル:   {signal.whale_signal:+.2f} ({signal.whale_trades} trades)")
    print(f"  流動性シグナル:   {signal.liquidity_signal:+.2f} ({signal.liquidity_change_pct:+.1%})")
    print(f"  クラスタシグナル: {signal.cluster_signal:+.2f}")
    print(f"  合成シグナル:     {signal.composite_signal:+.2f}")
    print(f"  信頼度:           {signal.confidence:.0%}")
