"""
Price History Fetcher
- Polymarket の過去価格データを取得
- バックテスト用データ保存
"""
import os
import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

import httpx


CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

DATA_DIR = Path(__file__).parent.parent / "data" / "historical"


@dataclass
class PricePoint:
    """価格データポイント"""
    timestamp: datetime
    price: float
    
    def to_dict(self) -> Dict:
        return {
            "t": int(self.timestamp.timestamp()),
            "p": self.price,
        }


@dataclass
class MarketHistory:
    """マーケット履歴"""
    market_id: str
    token_id: str
    question: str
    prices: List[PricePoint]
    
    @property
    def start_time(self) -> Optional[datetime]:
        return self.prices[0].timestamp if self.prices else None
    
    @property
    def end_time(self) -> Optional[datetime]:
        return self.prices[-1].timestamp if self.prices else None
    
    def to_dict(self) -> Dict:
        return {
            "market_id": self.market_id,
            "token_id": self.token_id,
            "question": self.question,
            "start": self.start_time.isoformat() if self.start_time else None,
            "end": self.end_time.isoformat() if self.end_time else None,
            "count": len(self.prices),
            "prices": [p.to_dict() for p in self.prices],
        }


class PriceHistoryFetcher:
    """価格履歴取得"""
    
    def __init__(self, save_dir: Path = None):
        """
        初期化
        
        Args:
            save_dir: 保存ディレクトリ
        """
        self.save_dir = save_dir or DATA_DIR
        os.makedirs(self.save_dir, exist_ok=True)
    
    async def fetch_prices(
        self,
        token_id: str,
        start_ts: int = None,
        end_ts: int = None,
        interval: str = "all",
        fidelity: int = 1,
    ) -> List[PricePoint]:
        """
        価格履歴を取得
        
        Args:
            token_id: トークンID (asset_id)
            start_ts: 開始UNIXタイムスタンプ
            end_ts: 終了UNIXタイムスタンプ
            interval: max, all, 1m, 1w, 1d, 6h, 1h
            fidelity: 精度 (分)
        
        Returns:
            List[PricePoint]
        """
        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        
        if start_ts:
            params["startTs"] = start_ts
        if end_ts:
            params["endTs"] = end_ts
        
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{CLOB_API}/prices-history",
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                
                prices = []
                for item in data.get("history", []):
                    prices.append(PricePoint(
                        timestamp=datetime.fromtimestamp(item["t"]),
                        price=item["p"],
                    ))
                
                return prices
                
            except Exception as e:
                print(f"価格履歴取得エラー: {e}")
                return []
    
    async def fetch_market_info(self, market_id: str) -> Optional[Dict]:
        """マーケット情報を取得"""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(f"{GAMMA_API}/markets/{market_id}")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                print(f"マーケット情報取得エラー: {e}")
                return None
    
    async def fetch_crypto_markets(self, limit: int = 50) -> List[Dict]:
        """BTC/ETH関連マーケットを取得"""
        markets = []
        keywords = ["BTC", "Bitcoin", "ETH", "Ethereum"]
        
        async with httpx.AsyncClient(timeout=30) as client:
            for kw in keywords:
                try:
                    resp = await client.get(
                        f"{GAMMA_API}/markets",
                        params={"_q": kw, "limit": 20, "active": "true"}
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    
                    for m in data:
                        if m.get("condition_id") not in [x.get("condition_id") for x in markets]:
                            markets.append(m)
                            
                except Exception as e:
                    print(f"マーケット取得エラー ({kw}): {e}")
        
        return markets[:limit]
    
    async def fetch_and_save(
        self,
        token_id: str,
        question: str = "",
        market_id: str = "",
        days: int = 30,
    ) -> Optional[MarketHistory]:
        """
        価格履歴を取得して保存
        
        Args:
            token_id: トークンID
            question: マーケットの質問
            market_id: マーケットID
            days: 取得日数
        
        Returns:
            MarketHistory
        """
        end_ts = int(datetime.now().timestamp())
        start_ts = int((datetime.now() - timedelta(days=days)).timestamp())
        
        print(f"📊 取得中: {question[:40] if question else token_id[:20]}...")
        
        prices = await self.fetch_prices(
            token_id=token_id,
            start_ts=start_ts,
            end_ts=end_ts,
            interval="all",
            fidelity=1,  # 1分足
        )
        
        if not prices:
            print(f"  ❌ データなし")
            return None
        
        history = MarketHistory(
            market_id=market_id,
            token_id=token_id,
            question=question,
            prices=prices,
        )
        
        # 保存
        filename = f"{token_id[:16]}_{datetime.now().strftime('%Y%m%d')}.json"
        filepath = self.save_dir / filename
        
        with open(filepath, "w") as f:
            json.dump(history.to_dict(), f, indent=2)
        
        print(f"  ✅ {len(prices)}本 ({history.start_time} ~ {history.end_time})")
        print(f"  💾 {filepath}")
        
        return history
    
    async def fetch_all_crypto_markets(
        self,
        days: int = 30,
        limit: int = 20,
    ) -> List[MarketHistory]:
        """
        全BTC/ETHマーケットの価格履歴を取得
        
        Args:
            days: 取得日数
            limit: 最大マーケット数
        
        Returns:
            List[MarketHistory]
        """
        print(f"🔍 BTC/ETHマーケット検索中...")
        markets = await self.fetch_crypto_markets(limit=limit)
        print(f"  {len(markets)} マーケット発見\n")
        
        histories = []
        
        for m in markets:
            tokens = m.get("tokens", [])
            yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
            
            if not yes_token:
                continue
            
            history = await self.fetch_and_save(
                token_id=yes_token.get("token_id", ""),
                question=m.get("question", ""),
                market_id=m.get("condition_id", ""),
                days=days,
            )
            
            if history:
                histories.append(history)
            
            # レート制限対策
            await asyncio.sleep(0.5)
        
        return histories
    
    def load_history(self, filepath: str) -> Optional[MarketHistory]:
        """保存された履歴を読み込み"""
        try:
            with open(filepath) as f:
                data = json.load(f)
            
            prices = [
                PricePoint(
                    timestamp=datetime.fromtimestamp(p["t"]),
                    price=p["p"],
                )
                for p in data.get("prices", [])
            ]
            
            return MarketHistory(
                market_id=data.get("market_id", ""),
                token_id=data.get("token_id", ""),
                question=data.get("question", ""),
                prices=prices,
            )
            
        except Exception as e:
            print(f"読み込みエラー: {e}")
            return None
    
    def list_saved_histories(self) -> List[Path]:
        """保存済み履歴一覧"""
        return list(self.save_dir.glob("*.json"))


# CLI
async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Polymarket 価格履歴取得")
    parser.add_argument("--days", type=int, default=30, help="取得日数")
    parser.add_argument("--limit", type=int, default=10, help="マーケット数")
    parser.add_argument("--token", help="特定トークンID")
    
    args = parser.parse_args()
    
    fetcher = PriceHistoryFetcher()
    
    if args.token:
        # 特定トークン
        history = await fetcher.fetch_and_save(
            token_id=args.token,
            days=args.days,
        )
    else:
        # 全BTC/ETHマーケット
        histories = await fetcher.fetch_all_crypto_markets(
            days=args.days,
            limit=args.limit,
        )
        
        print(f"\n📊 取得完了: {len(histories)} マーケット")


if __name__ == "__main__":
    asyncio.run(main())
