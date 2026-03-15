"""
ML Analyst
- LightGBM による確率予測
- 30特徴量、500ツリー
"""
import os
import json
import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

import numpy as np

from .features import Features, FeatureExtractor

# LightGBM
try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    print("Warning: lightgbm not installed. Run: pip install lightgbm")


@dataclass
class MLPrediction:
    """ML予測結果"""
    probability: float      # YES確率
    confidence: float       # 信頼度
    feature_importance: Dict[str, float] = None


class MLAnalyst:
    """LightGBM による市場分析"""
    
    MODEL_DIR = Path(__file__).parent.parent / "models"
    
    # モデルパラメータ
    DEFAULT_PARAMS = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "n_estimators": 500,
        "early_stopping_rounds": 50,
    }
    
    def __init__(self, model_path: str = None):
        """
        ML Analyst 初期化
        
        Args:
            model_path: 学習済みモデルのパス (Noneの場合は未学習)
        """
        if not LIGHTGBM_AVAILABLE:
            raise RuntimeError("lightgbm not installed")
        
        self.model: Optional[lgb.Booster] = None
        self.feature_extractor = FeatureExtractor()
        self.feature_names: List[str] = list(Features(timestamp=datetime.now()).to_dict().keys())
        
        # モデル読み込み
        if model_path and os.path.exists(model_path):
            self.load_model(model_path)
    
    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        X_val: np.ndarray = None,
        y_val: np.ndarray = None,
        params: Dict = None,
    ) -> Dict:
        """
        モデルを学習
        
        Args:
            X: 特徴量 (n_samples, 30)
            y: ラベル (0 or 1)
            X_val: 検証用特徴量
            y_val: 検証用ラベル
            params: LightGBM パラメータ
        
        Returns:
            学習結果 (metrics)
        """
        params = params or self.DEFAULT_PARAMS.copy()
        
        # データセット作成
        train_data = lgb.Dataset(X, label=y, feature_name=self.feature_names)
        
        valid_sets = [train_data]
        valid_names = ["train"]
        
        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val, feature_name=self.feature_names)
            valid_sets.append(val_data)
            valid_names.append("valid")
        
        # 学習
        callbacks = [lgb.log_evaluation(period=100)]
        if params.get("early_stopping_rounds"):
            callbacks.append(lgb.early_stopping(params.pop("early_stopping_rounds")))
        
        self.model = lgb.train(
            params,
            train_data,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )
        
        # 結果
        result = {
            "n_estimators": self.model.num_trees(),
            "best_iteration": self.model.best_iteration,
        }
        
        # 特徴量重要度
        importance = self.model.feature_importance(importance_type="gain")
        result["feature_importance"] = dict(zip(self.feature_names, importance.tolist()))
        
        return result
    
    def predict(self, features: Features) -> MLPrediction:
        """
        特徴量から確率を予測
        
        Args:
            features: 特徴量
        
        Returns:
            MLPrediction
        """
        if self.model is None:
            # 未学習の場合はデフォルト値
            return MLPrediction(
                probability=0.5,
                confidence=0.0,
            )
        
        # 予測
        X = np.array([features.to_list()])
        prob = self.model.predict(X)[0]
        
        # 信頼度 (0.5からの距離)
        confidence = abs(prob - 0.5) * 2
        
        # 特徴量重要度
        importance = self.model.feature_importance(importance_type="gain")
        feature_importance = dict(zip(self.feature_names, importance.tolist()))
        
        return MLPrediction(
            probability=float(prob),
            confidence=float(confidence),
            feature_importance=feature_importance,
        )
    
    def predict_from_raw(
        self,
        prices: List[float],
        volumes: List[float] = None,
        bids: List[Dict] = None,
        asks: List[Dict] = None,
        yes_price: float = 0.5,
        market_volume: float = 0,
        market_liquidity: float = 0,
        end_date: datetime = None,
        llm_pred: float = None,
        llm_conf: float = None,
    ) -> MLPrediction:
        """
        生データから予測
        """
        features = self.feature_extractor.extract(
            prices=prices,
            volumes=volumes,
            bids=bids,
            asks=asks,
            yes_price=yes_price,
            market_volume=market_volume,
            market_liquidity=market_liquidity,
            end_date=end_date,
            llm_pred=llm_pred,
            llm_conf=llm_conf,
        )
        
        return self.predict(features)
    
    def save_model(self, path: str = None):
        """モデルを保存"""
        if self.model is None:
            raise ValueError("モデルが未学習です")
        
        path = path or (self.MODEL_DIR / "lightgbm_model.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        self.model.save_model(str(path))
        print(f"💾 モデル保存: {path}")
    
    def load_model(self, path: str):
        """モデルを読み込み"""
        self.model = lgb.Booster(model_file=str(path))
        print(f"📂 モデル読み込み: {path}")
    
    def get_feature_importance(self, top_n: int = 10) -> Dict[str, float]:
        """特徴量重要度を取得"""
        if self.model is None:
            return {}
        
        importance = self.model.feature_importance(importance_type="gain")
        sorted_idx = np.argsort(importance)[::-1][:top_n]
        
        return {
            self.feature_names[i]: float(importance[i])
            for i in sorted_idx
        }


# サンプルデータ生成 (学習用)
def generate_sample_data(n_samples: int = 1000):
    """
    サンプルデータを生成 (デモ用)
    
    実際の運用では過去のマーケットデータを使用
    """
    np.random.seed(42)
    
    n_features = 30
    X = np.random.randn(n_samples, n_features)
    
    # 簡単なルールでラベル生成
    # LLM予測 (index 28, 29) が高いほど YES になりやすい
    llm_pred = X[:, 28]
    llm_conf = X[:, 29]
    
    # モメンタム (index 0-7) もシグナルになる
    momentum = X[:, 6]
    
    # 合成スコア
    score = 0.4 * llm_pred + 0.2 * llm_conf + 0.3 * momentum + 0.1 * np.random.randn(n_samples)
    
    # シグモイド変換
    prob = 1 / (1 + np.exp(-score))
    y = (prob > 0.5).astype(int)
    
    return X, y


# テスト
if __name__ == "__main__":
    print("🤖 ML Analyst テスト\n")
    
    # サンプルデータ生成
    print("📊 サンプルデータ生成...")
    X, y = generate_sample_data(1000)
    
    # 学習/検証分割
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    
    print(f"  学習: {len(X_train)} | 検証: {len(X_val)}")
    
    # 学習
    print("\n🎓 モデル学習...")
    analyst = MLAnalyst()
    result = analyst.train(X_train, y_train, X_val, y_val)
    
    print(f"\n  ツリー数: {result['n_estimators']}")
    print(f"  ベストイテレーション: {result['best_iteration']}")
    
    # 特徴量重要度
    print("\n📈 特徴量重要度 (Top 5):")
    for name, imp in list(analyst.get_feature_importance(5).items()):
        print(f"  {name:25}: {imp:.2f}")
    
    # 予測テスト
    print("\n🎯 予測テスト:")
    from features import FeatureExtractor
    
    extractor = FeatureExtractor()
    features = extractor.extract(
        prices=[100 + i * 0.1 for i in range(100)],
        yes_price=0.55,
        llm_pred=0.65,
        llm_conf=0.8,
    )
    
    pred = analyst.predict(features)
    print(f"  確率: {pred.probability:.1%}")
    print(f"  信頼度: {pred.confidence:.1%}")
