"""
Crypto-specific ML Analyst
- CryptoFeatures (36特徴量) を使用
- models/lgb_crypto_model.pkl を別ファイルで管理
- is_crypto_market() が True のマーケットにのみ適用
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .ml_analyst import MLAnalyst, MLPrediction
from .crypto_features import CryptoFeatures, CryptoFeatureExtractor, is_crypto_market


class CryptoMLAnalyst(MLAnalyst):
    """Crypto市場専用 LightGBM アナリスト

    汎用MLAnalystを継承し、CryptoFeaturesExtractorと専用モデルを使用する。
    36特徴量: 28 (generic) + 8 (crypto-specific)
    """

    CRYPTO_MODEL_PATH = Path(__file__).parent.parent / "models" / "lgb_crypto_model.pkl"

    def __init__(self, model_path: str = None):
        """
        初期化

        Args:
            model_path: モデルパス (None → デフォルトの lgb_crypto_model.pkl)
        """
        # MLAnalyst.__init__ は lightgbm チェックをするのでそちらに委譲
        super().__init__(model_path=None)  # モデルは後で読み込む

        # 特徴量エクストラクタを Crypto 用に差し替え
        self.crypto_extractor = CryptoFeatureExtractor()
        self.feature_names = list(CryptoFeatures(timestamp=datetime.now()).to_dict().keys())

        # モデルロード
        path = model_path or str(self.CRYPTO_MODEL_PATH)
        if Path(path).exists():
            self.load_model(path)
            print(f"🔮 Crypto MLモデル読み込み: {path} ({len(self.feature_names)}特徴量)")
        else:
            print(f"⚠️ Crypto MLモデルなし: {path} (学習が必要)")

    @classmethod
    def is_available(cls) -> bool:
        """学習済みモデルが存在するか"""
        return cls.CRYPTO_MODEL_PATH.exists()

    def predict_crypto(
        self,
        prices: List[float],
        volumes: List[float] = None,
        bids: List[Dict] = None,
        asks: List[Dict] = None,
        trades: list = None,
        yes_price: float = 0.5,
        market_volume: float = 0,
        market_liquidity: float = 0,
        end_date=None,
        btc_price: float = None,
        btc_change_24h: float = None,
        eth_change_24h: float = None,
        btc_prices_1h: List[float] = None,
    ) -> MLPrediction:
        """
        Crypto特徴量から予測

        Args:
            btc_change_24h: BTC 24h変化率 (小数, e.g. 0.05 = +5%)
            eth_change_24h: ETH 24h変化率
            btc_prices_1h: BTC直近1h価格履歴 (1分足60本)

        Returns:
            MLPrediction
        """
        features = self.crypto_extractor.extract(
            prices=prices,
            volumes=volumes,
            bids=bids,
            asks=asks,
            trades=trades,
            yes_price=yes_price,
            market_volume=market_volume,
            market_liquidity=market_liquidity,
            end_date=end_date,
            btc_price=btc_price,
            btc_change_24h=btc_change_24h,
            eth_change_24h=eth_change_24h,
            btc_prices_1h=btc_prices_1h,
        )
        return self.predict(features)

    def save_model(self, path: str = None):
        """Crypto モデルを保存"""
        path = path or str(self.CRYPTO_MODEL_PATH)
        super().save_model(path)
