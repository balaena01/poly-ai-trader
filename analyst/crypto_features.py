"""
Crypto-specific Feature Engineering
- 28 generic features (inherited from features.py) + 8 crypto-specific
- Only meaningful for markets whose outcome depends on BTC/ETH price movements
- Total: 36 features
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import math

from .features import Features, FeatureExtractor


# キーワード (小文字マッチ)
CRYPTO_KEYWORDS = [
    "bitcoin", "btc",
    "ethereum", "eth",
    "solana", "sol",
    "crypto", "cryptocurrency",
    "altcoin", "defi", "nft",
    "xrp", "ripple",
    "bnb", "binance",
    "doge", "dogecoin",
    "cardano", "ada",
    "polygon", "matic",
    "avalanche", "avax",
    "chainlink", "link",
    "shib", "shiba",
    "pepe", "meme coin",
    "coinbase", "binance", "kraken",
    "$100k", "$200k", "$50k", "$80k", "$150k",  # BTC価格目標
    "all-time high", "ath", "halving",
]


def is_crypto_market(question: str) -> bool:
    """questionがcrypto系マーケットか判定"""
    q = question.lower()
    return any(kw in q for kw in CRYPTO_KEYWORDS)


@dataclass
class CryptoFeatures(Features):
    """Crypto専用特徴量 (28 + 8 = 36特徴量)

    8つのcrypto固有特徴量を追加:
    - BTC/ETH の価格動向がマーケット結果と直接連動するマーケット向け
    - 汎用MLモデルとは別学習データ・別モデルファイルで管理
    """

    # ========== Crypto固有 (8) ==========
    btc_return_1h: float = 0        # BTC 1h リターン
    btc_return_24h: float = 0       # BTC 24h リターン (外部から渡す)
    eth_return_24h: float = 0       # ETH 24h リターン
    btc_eth_corr: float = 0         # BTC-ETH 30日相関係数
    market_btc_corr: float = 0      # YES価格とBTC方向の一致度 (-1〜1)
    btc_vol_regime: float = 0       # BTC ボラ体制: 1h_vol / 24h_vol (短期>長期なら高ボラ)
    crypto_momentum_align: float = 0  # LLM方向とBTC方向の一致 (+1/-1/0)
    yes_price_distance: float = 0   # YES価格と0.5からの距離 (確信度の代理変数)

    def to_dict(self) -> Dict[str, float]:
        base = super().to_dict()
        base.update({
            "btc_return_1h": self.btc_return_1h,
            "btc_return_24h": self.btc_return_24h,
            "eth_return_24h": self.eth_return_24h,
            "btc_eth_corr": self.btc_eth_corr,
            "market_btc_corr": self.market_btc_corr,
            "btc_vol_regime": self.btc_vol_regime,
            "crypto_momentum_align": self.crypto_momentum_align,
            "yes_price_distance": self.yes_price_distance,
        })
        return base

    def to_list(self) -> List[float]:
        return list(self.to_dict().values())


class CryptoFeatureExtractor:
    """Crypto専用特徴量抽出器

    FeatureExtractor (28特徴量) をラップし、
    BTC/ETH コンテキストから追加8特徴量を計算して結合。
    """

    def __init__(self):
        self._base = FeatureExtractor()

    def extract(
        self,
        # 通常特徴量と同じ引数
        prices: List[float],
        volumes: List[float] = None,
        bids: List[Dict] = None,
        asks: List[Dict] = None,
        trades: list = None,
        yes_price: float = 0.5,
        market_volume: float = 0,
        market_liquidity: float = 0,
        end_date: datetime = None,

        # Crypto固有: BTCコンテキスト
        btc_price: float = None,
        btc_change_24h: float = None,   # 24hリターン (小数: 0.05 = +5%)
        eth_change_24h: float = None,
        btc_prices_1h: List[float] = None,  # BTC 直近1h の価格履歴 (60本)
    ) -> CryptoFeatures:
        """
        36特徴量を抽出

        Args:
            prices: YES価格の履歴
            btc_prices_1h: BTC/USDの1分足 60本 (1時間分). Noneなら計算不可
            btc_change_24h: CoinGecko等から取得済みの 24h変化率 (小数)
            eth_change_24h: 同上 ETH
        """
        # --- 28特徴量 (base) ---
        base = self._base.extract(
            prices=prices,
            volumes=volumes,
            bids=bids,
            asks=asks,
            trades=trades,
            yes_price=yes_price,
            market_volume=market_volume,
            market_liquidity=market_liquidity,
            end_date=end_date,
        )

        # CryptoFeatures に変換 (全フィールドをコピー)
        cf = CryptoFeatures(timestamp=base.timestamp)
        for fname in base.to_dict():
            if hasattr(cf, fname):
                setattr(cf, fname, getattr(base, fname))

        # --- 8つの Crypto固有特徴量 ---

        # BTC 24h リターン (外部から)
        if btc_change_24h is not None:
            cf.btc_return_24h = max(-1.0, min(1.0, btc_change_24h))

        # ETH 24h リターン
        if eth_change_24h is not None:
            cf.eth_return_24h = max(-1.0, min(1.0, eth_change_24h))

        # BTC 1h リターン + ボラ体制
        if btc_prices_1h and len(btc_prices_1h) >= 2:
            first = btc_prices_1h[0]
            last = btc_prices_1h[-1]
            if first > 0:
                cf.btc_return_1h = (last - first) / first
                cf.btc_return_1h = max(-0.5, min(0.5, cf.btc_return_1h))

            # ボラ体制: 直近15本 vs 全60本の標準偏差比
            def _std(arr: List[float]) -> float:
                if len(arr) < 2:
                    return 0.0
                m = sum(arr) / len(arr)
                return math.sqrt(sum((x - m) ** 2 for x in arr) / len(arr))

            std_short = _std(btc_prices_1h[-15:])
            std_long = _std(btc_prices_1h)
            if std_long > 0:
                cf.btc_vol_regime = min(3.0, std_short / std_long)

        # BTC-ETH 相関 (30日データがあれば計算、なければ0.8をデフォルト)
        # ここでは外部から渡された 24h リターンで方向一致度を代替
        if btc_change_24h is not None and eth_change_24h is not None:
            # 方向一致 → 1.0, 不一致 → -1.0
            if (btc_change_24h >= 0) == (eth_change_24h >= 0):
                cf.btc_eth_corr = min(1.0, abs(btc_change_24h * eth_change_24h) ** 0.5 + 0.5)
            else:
                cf.btc_eth_corr = -0.5

        # YES価格とBTCリターン方向の一致度
        # YES価格が上昇傾向 (>0.5 or 最近上がっている) かつ BTC も上昇 → 一致
        if prices and len(prices) >= 2 and btc_change_24h is not None:
            yes_direction = prices[-1] - prices[0]
            btc_direction = btc_change_24h
            if yes_direction * btc_direction > 0:
                cf.market_btc_corr = min(1.0, abs(yes_direction) * abs(btc_direction) * 100)
            elif yes_direction * btc_direction < 0:
                cf.market_btc_corr = max(-1.0, -abs(yes_direction) * abs(btc_direction) * 100)
            else:
                cf.market_btc_corr = 0.0

        # crypto_momentum_align: LLM方向と BTC方向の一致
        # (LLMは呼び出し後に分かるので、ここでは BTC momentum だけ記録)
        # btc上昇 → +1, btc下落 → -1, 不明 → 0
        if btc_change_24h is not None:
            cf.crypto_momentum_align = 1.0 if btc_change_24h > 0.01 else (
                -1.0 if btc_change_24h < -0.01 else 0.0
            )

        # YES価格と0.5からの距離 (確信度の代理)
        cf.yes_price_distance = (yes_price - 0.5) * 2  # -1〜1

        return cf
