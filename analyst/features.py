"""
Feature Engineering
- 価格、ボリューム、オーダーブックから特徴量を生成
- LightGBM モデル用
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional
import math


@dataclass
class Features:
    """特徴量セット (28特徴量)

    LLM予測確率・信頼度は含まない。
    LLM は Bayesian 統合で独立シグナルとして扱うため ML 特徴量から除外し
    二重カウントを防ぐ。
    """
    timestamp: datetime
    
    # ========== 価格モメンタム (8) ==========
    price_return_1m: float = 0      # 1分リターン
    price_return_5m: float = 0      # 5分リターン
    price_return_15m: float = 0     # 15分リターン
    price_return_1h: float = 0      # 1時間リターン
    price_return_4h: float = 0      # 4時間リターン
    price_return_24h: float = 0     # 24時間リターン
    price_momentum: float = 0       # モメンタム (加重平均)
    price_acceleration: float = 0   # 加速度 (モメンタムの変化率)
    
    # ========== ボラティリティ (6) ==========
    volatility_1h: float = 0        # 1時間ボラ
    volatility_24h: float = 0       # 24時間ボラ
    atr_14: float = 0               # ATR (14期間)
    bollinger_position: float = 0   # ボリンジャー内位置 (-1 to 1)
    volatility_ratio: float = 0     # 短期/長期ボラ比
    range_position: float = 0       # 日足レンジ内位置
    
    # ========== ボリューム (4) ==========
    volume_ratio_1h: float = 0      # 1時間ボリューム比 (vs 平均)
    volume_trend: float = 0         # ボリュームトレンド
    buy_volume_ratio: float = 0     # 買いボリューム比率
    volume_price_corr: float = 0    # ボリューム・価格相関
    
    # ========== オーダーブック (6) ==========
    bid_ask_spread: float = 0       # スプレッド
    book_imbalance: float = 0       # Bid/Ask 不均衡 (-1 to 1)
    depth_ratio: float = 0          # 深度比率
    large_order_bias: float = 0     # 大口注文バイアス
    liquidity_score: float = 0      # 流動性スコア
    order_flow_imbalance: float = 0 # オーダーフロー不均衡
    
    # ========== マーケット固有 (4) ==========
    market_yes_price: float = 0     # YES価格
    market_volume_24h: float = 0    # 24時間ボリューム
    market_liquidity: float = 0     # 流動性
    time_to_resolution: float = 0   # 解決までの時間 (日)
    
    def to_dict(self) -> Dict[str, float]:
        """辞書に変換"""
        return {
            # モメンタム
            "price_return_1m": self.price_return_1m,
            "price_return_5m": self.price_return_5m,
            "price_return_15m": self.price_return_15m,
            "price_return_1h": self.price_return_1h,
            "price_return_4h": self.price_return_4h,
            "price_return_24h": self.price_return_24h,
            "price_momentum": self.price_momentum,
            "price_acceleration": self.price_acceleration,
            # ボラティリティ
            "volatility_1h": self.volatility_1h,
            "volatility_24h": self.volatility_24h,
            "atr_14": self.atr_14,
            "bollinger_position": self.bollinger_position,
            "volatility_ratio": self.volatility_ratio,
            "range_position": self.range_position,
            # ボリューム
            "volume_ratio_1h": self.volume_ratio_1h,
            "volume_trend": self.volume_trend,
            "buy_volume_ratio": self.buy_volume_ratio,
            "volume_price_corr": self.volume_price_corr,
            # オーダーブック
            "bid_ask_spread": self.bid_ask_spread,
            "book_imbalance": self.book_imbalance,
            "depth_ratio": self.depth_ratio,
            "large_order_bias": self.large_order_bias,
            "liquidity_score": self.liquidity_score,
            "order_flow_imbalance": self.order_flow_imbalance,
            # マーケット
            "market_yes_price": self.market_yes_price,
            "market_volume_24h": self.market_volume_24h,
            "market_liquidity": self.market_liquidity,
            "time_to_resolution": self.time_to_resolution,
        }
    
    def to_list(self) -> List[float]:
        """リストに変換 (モデル入力用)"""
        return list(self.to_dict().values())


class FeatureExtractor:
    """特徴量抽出器"""
    
    def __init__(self):
        self.price_history: List[float] = []
        self.volume_history: List[float] = []
    
    def extract(
        self,
        # 価格データ
        prices: List[float],          # 価格履歴 (最新が最後)
        volumes: List[float] = None,  # ボリューム履歴

        # オーダーブック
        bids: List[Dict] = None,      # [{price, size}, ...]
        asks: List[Dict] = None,      # [{price, size}, ...]

        # 取引履歴 (buy_volume_ratio / order_flow_imbalance 計算に使用)
        trades: list = None,          # Trade-like objects with .price, .size, .side

        # マーケット情報
        yes_price: float = 0.5,
        market_volume: float = 0,
        market_liquidity: float = 0,
        end_date: datetime = None,

        # LLM予測
        llm_pred: float = None,
        llm_conf: float = None,
    ) -> Features:
        """特徴量を抽出"""
        
        features = Features(timestamp=datetime.now())
        
        if not prices or len(prices) < 2:
            return features
        
        # ========== 価格モメンタム ==========
        current = prices[-1]
        
        def safe_return(idx: int) -> float:
            if len(prices) > idx and prices[-idx-1] > 0:
                return (current - prices[-idx-1]) / prices[-idx-1]
            return 0
        
        features.price_return_1m = safe_return(1)
        features.price_return_5m = safe_return(5)
        features.price_return_15m = safe_return(15)
        features.price_return_1h = safe_return(60)
        features.price_return_4h = safe_return(240)
        features.price_return_24h = safe_return(1440)
        
        # 加重モメンタム
        features.price_momentum = (
            features.price_return_1m * 0.1 +
            features.price_return_5m * 0.2 +
            features.price_return_15m * 0.3 +
            features.price_return_1h * 0.4
        )
        
        # 加速度
        if len(prices) > 10:
            mom_now = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
            mom_prev = (prices[-5] - prices[-10]) / prices[-10] if prices[-10] > 0 else 0
            features.price_acceleration = mom_now - mom_prev
        
        # ========== ボラティリティ ==========
        def calc_volatility(data: List[float]) -> float:
            if len(data) < 2:
                return 0
            mean = sum(data) / len(data)
            variance = sum((x - mean) ** 2 for x in data) / len(data)
            return math.sqrt(variance)
        
        if len(prices) >= 60:
            features.volatility_1h = calc_volatility(prices[-60:])
        if len(prices) >= 1440:
            features.volatility_24h = calc_volatility(prices[-1440:])
        
        # ボラ比率
        if features.volatility_24h > 0:
            features.volatility_ratio = features.volatility_1h / features.volatility_24h
        
        # ボリンジャー位置
        if len(prices) >= 20:
            recent = prices[-20:]
            mean = sum(recent) / len(recent)
            std = calc_volatility(recent)
            if std > 0:
                features.bollinger_position = (current - mean) / (2 * std)
                features.bollinger_position = max(-1, min(1, features.bollinger_position))
        
        # レンジ位置
        if len(prices) >= 24:
            high = max(prices[-24:])
            low = min(prices[-24:])
            if high > low:
                features.range_position = (current - low) / (high - low) * 2 - 1
        
        # ========== ボリューム ==========
        if volumes and len(volumes) > 0:
            current_vol = volumes[-1]
            
            if len(volumes) >= 60:
                avg_vol = sum(volumes[-60:]) / 60
                if avg_vol > 0:
                    features.volume_ratio_1h = current_vol / avg_vol
            
            if len(volumes) >= 10:
                vol_start = sum(volumes[-10:-5]) / 5
                vol_end = sum(volumes[-5:]) / 5
                if vol_start > 0:
                    features.volume_trend = (vol_end - vol_start) / vol_start

            # ボリューム・価格相関 (直近20期間の絶対リターンとボリュームの相関)
            n = min(len(volumes), len(prices), 20)
            if n >= 5:
                pc = [
                    abs(prices[-i] - prices[-i - 1]) / prices[-i - 1]
                    if prices[-i - 1] > 0 else 0
                    for i in range(1, n)
                ]
                vs = list(volumes[-(n - 1):])
                if len(pc) == len(vs) and len(pc) >= 2:
                    mean_p = sum(pc) / len(pc)
                    mean_v = sum(vs) / len(vs)
                    cov = sum((pc[i] - mean_p) * (vs[i] - mean_v) for i in range(len(pc))) / len(pc)
                    std_p = math.sqrt(sum((x - mean_p) ** 2 for x in pc) / len(pc))
                    std_v = math.sqrt(sum((x - mean_v) ** 2 for x in vs) / len(vs))
                    if std_p > 0 and std_v > 0:
                        features.volume_price_corr = max(-1.0, min(1.0, cov / (std_p * std_v)))

        # ========== 取引フロー (buy_volume_ratio / order_flow_imbalance) ==========
        if trades:
            try:
                buy_val = sum(t.price * t.size for t in trades if getattr(t, "side", "") == "buy")
                sell_val = sum(t.price * t.size for t in trades if getattr(t, "side", "") == "sell")
                total_val = buy_val + sell_val
                if total_val > 0:
                    features.buy_volume_ratio = buy_val / total_val
                    features.order_flow_imbalance = (buy_val - sell_val) / total_val
            except Exception:
                pass  # 取引データ形式が不正でも続行

        # ========== オーダーブック ==========
        if bids and asks:
            best_bid = bids[0]["price"] if bids else 0
            best_ask = asks[0]["price"] if asks else 0
            
            if best_bid > 0 and best_ask > 0:
                features.bid_ask_spread = (best_ask - best_bid) / best_bid
            
            # 深度計算
            bid_depth = sum(b.get("size", 0) for b in bids[:5])
            ask_depth = sum(a.get("size", 0) for a in asks[:5])
            total_depth = bid_depth + ask_depth
            
            if total_depth > 0:
                features.book_imbalance = (bid_depth - ask_depth) / total_depth
                features.depth_ratio = bid_depth / total_depth
            
            # 大口注文検出
            large_threshold = total_depth * 0.1  # 上位10%を大口とみなす
            large_bids = sum(b.get("size", 0) for b in bids if b.get("size", 0) > large_threshold)
            large_asks = sum(a.get("size", 0) for a in asks if a.get("size", 0) > large_threshold)
            
            if large_bids + large_asks > 0:
                features.large_order_bias = (large_bids - large_asks) / (large_bids + large_asks)
            
            # 流動性スコア (正規化)
            features.liquidity_score = min(1.0, total_depth / 100000)
        
        # ========== マーケット固有 ==========
        features.market_yes_price = yes_price
        features.market_volume_24h = min(1.0, market_volume / 1000000)  # 100万で正規化
        features.market_liquidity = min(1.0, market_liquidity / 500000)  # 50万で正規化
        
        if end_date:
            now = datetime.now(timezone.utc) if end_date.tzinfo else datetime.now()
            days_to_resolution = (end_date - now).total_seconds() / 86400
            features.time_to_resolution = max(0, min(365, days_to_resolution)) / 365  # 1年で正規化
        
        # llm_pred / llm_conf は受け付けるが Features には含めない
        # LLM は Bayesian で独立シグナルとして扱うため ML 特徴量から除外

        return features


# テスト
if __name__ == "__main__":
    import random
    
    # ダミーデータ
    prices = [100 + random.uniform(-5, 5) for _ in range(100)]
    volumes = [1000 + random.uniform(-500, 500) for _ in range(100)]
    bids = [{"price": 99 - i * 0.1, "size": 100 + i * 10} for i in range(10)]
    asks = [{"price": 101 + i * 0.1, "size": 80 + i * 10} for i in range(10)]
    
    extractor = FeatureExtractor()
    features = extractor.extract(
        prices=prices,
        volumes=volumes,
        bids=bids,
        asks=asks,
        yes_price=0.65,
        market_volume=500000,
        llm_pred=0.70,
        llm_conf=0.8,
    )
    
    print("📊 特徴量 (30個):")
    for k, v in features.to_dict().items():
        print(f"  {k:25}: {v:+.4f}")
