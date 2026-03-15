#!/usr/bin/env python3
"""
ML Model Training Script

使用方法:
  1. 解決済みマーケットのデータを収集
  2. 特徴量を抽出
  3. LightGBM を学習
  4. モデルを保存

実行:
  python scripts/train_ml.py --days 30
"""
import os
import sys
import json
import asyncio
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# パス追加
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from client import PolyClient
from data_fetcher import PriceHistoryFetcher
from analyst.features import FeatureExtractor, Features
from analyst.ml_analyst import MLAnalyst


DATA_DIR = Path(__file__).parent.parent / "data" / "training"
MODEL_DIR = Path(__file__).parent.parent / "models"


async def collect_resolved_markets(days: int = 30) -> list:
    """解決済みマーケットを収集"""
    client = PolyClient()
    client.connect(read_only=True)
    
    # 解決済みマーケットを取得
    # Note: Polymarket API で closed=true のマーケットを取得
    markets = client.get_markets(limit=100, active=False)
    
    resolved = []
    for m in markets:
        if hasattr(m, 'outcome') and m.outcome:
            resolved.append({
                "market_id": m.market_id,
                "token_id": m.yes_token_id,
                "question": m.question,
                "outcome": m.outcome,  # "YES" or "NO"
                "yes_price": m.yes_price,
                "volume": m.volume,
            })
    
    print(f"📊 解決済みマーケット: {len(resolved)}件")
    return resolved


async def collect_training_data(markets: list) -> tuple:
    """特徴量とラベルを収集"""
    fetcher = PriceHistoryFetcher()
    extractor = FeatureExtractor()
    
    X_list = []
    y_list = []
    
    for i, m in enumerate(markets):
        try:
            # 価格履歴取得
            prices = await fetcher.fetch_prices(
                token_id=m["token_id"],
                interval="max",
                fidelity=60,  # 1時間足
            )
            
            if len(prices) < 10:
                continue
            
            # 特徴量抽出 (解決前のスナップショット)
            price_list = [p.price for p in prices[:-1]]  # 最後の1点を除く
            
            features = extractor.extract(
                prices=price_list[-100:],
                yes_price=m["yes_price"],
                market_volume=m["volume"],
            )
            
            X_list.append(features.to_list())
            y_list.append(1 if m["outcome"] == "YES" else 0)
            
            print(f"  [{i+1}/{len(markets)}] {m['question'][:40]}... → {m['outcome']}")
            
        except Exception as e:
            print(f"  ⚠️ スキップ: {e}")
            continue
        
        # レート制限対策
        await asyncio.sleep(0.5)
    
    X = np.array(X_list) if X_list else np.array([])
    y = np.array(y_list) if y_list else np.array([])
    
    print(f"\n📦 学習データ: {len(X)}件")
    return X, y


def train_and_save(X: np.ndarray, y: np.ndarray, model_path: str):
    """モデルを学習して保存"""
    if len(X) < 50:
        print("⚠️ データが少なすぎます (最低50件必要)")
        return False
    
    # Train/Val split
    from sklearn.model_selection import train_test_split
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # 学習
    analyst = MLAnalyst()
    result = analyst.train(X_train, y_train, X_val, y_val)
    
    # 保存
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    analyst.save_model(model_path)
    
    print(f"\n✅ モデル保存: {model_path}")
    print(f"   Train AUC: {result.get('train_auc', 'N/A')}")
    print(f"   Valid AUC: {result.get('valid_auc', 'N/A')}")
    
    return True


async def main():
    parser = argparse.ArgumentParser(description="ML Model Training")
    parser.add_argument("--days", type=int, default=30, help="過去何日のデータを使用")
    parser.add_argument("--output", default=str(MODEL_DIR / "lgb_model.pkl"), help="出力パス")
    args = parser.parse_args()
    
    print("🚀 ML Model Training\n")
    
    # 1. 解決済みマーケット収集
    markets = await collect_resolved_markets(args.days)
    
    if not markets:
        print("❌ 解決済みマーケットがありません")
        return
    
    # 2. 学習データ収集
    X, y = await collect_training_data(markets)
    
    if len(X) == 0:
        print("❌ 学習データを収集できませんでした")
        return
    
    # 3. 学習 & 保存
    train_and_save(X, y, args.output)


if __name__ == "__main__":
    asyncio.run(main())
