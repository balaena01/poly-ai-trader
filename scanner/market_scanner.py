"""
Market Scanner
- Polymarket の BTC/ETH 関連マーケットを監視
- Binance WebSocket でリアルタイム価格取得
- モメンタム、ボラティリティを計算
"""
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Callable
from collections import deque

import httpx

# Binance WebSocket (非同期)
try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


# Constants
GAMMA_API = "https://gamma-api.polymarket.com"
BINANCE_WS = "wss://stream.binance.com:9443/ws"
BINANCE_REST = "https://api.binance.com/api/v3"


@dataclass
class PriceData:
    """価格データ"""
    symbol: str
    price: float
    timestamp: datetime
    volume_24h: float = 0
    change_24h: float = 0


@dataclass
class MarketData:
    """Polymarket マーケットデータ"""
    market_id: str
    question: str
    yes_token_id: str
    no_token_id: Optional[str]
    yes_price: float
    volume: float
    liquidity: float
    end_date: Optional[datetime]
    last_updated: datetime = field(default_factory=datetime.now)
    
    # 計算済み指標
    momentum: float = 0  # 価格変化率
    volatility: float = 0  # ボラティリティ
    
    @property
    def implied_prob(self) -> float:
        """YES の暗示確率"""
        return self.yes_price
    
    @property
    def edge(self) -> float:
        """エッジ (外部シグナルとの差分用)"""
        return 0  # Analyst で計算


@dataclass
class ScanResult:
    """スキャン結果"""
    timestamp: datetime
    btc_price: Optional[PriceData]
    eth_price: Optional[PriceData]
    markets: List[MarketData]
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "btc": {"price": self.btc_price.price, "change_24h": self.btc_price.change_24h} if self.btc_price else None,
            "eth": {"price": self.eth_price.price, "change_24h": self.eth_price.change_24h} if self.eth_price else None,
            "markets": [
                {
                    "question": m.question[:50],
                    "yes_price": m.yes_price,
                    "volume": m.volume,
                }
                for m in self.markets[:5]
            ],
        }


class MarketScanner:
    """マーケットスキャナー"""
    
    def __init__(self):
        self.btc_prices: deque = deque(maxlen=60)  # 直近60分
        self.eth_prices: deque = deque(maxlen=60)
        self.market_cache: Dict[str, MarketData] = {}
        
        self._running = False
        self._ws_task = None
    
    # ========== Binance 価格取得 ==========
    
    async def get_binance_price(self, symbol: str = "BTCUSDT") -> Optional[PriceData]:
        """Binance REST API で現在価格を取得"""
        async with httpx.AsyncClient() as client:
            try:
                # 24h ticker
                resp = await client.get(
                    f"{BINANCE_REST}/ticker/24hr",
                    params={"symbol": symbol}
                )
                resp.raise_for_status()
                data = resp.json()
                
                return PriceData(
                    symbol=symbol,
                    price=float(data["lastPrice"]),
                    timestamp=datetime.now(),
                    volume_24h=float(data["volume"]),
                    change_24h=float(data["priceChangePercent"]),
                )
            except Exception as e:
                print(f"Binance価格取得エラー ({symbol}): {e}")
                return None
    
    async def start_price_stream(self, callback: Callable = None):
        """Binance WebSocket で価格ストリーム開始"""
        if not WS_AVAILABLE:
            print("websockets not installed. Using REST polling.")
            return
        
        streams = "btcusdt@ticker/ethusdt@ticker"
        url = f"{BINANCE_WS}/{streams}"
        
        self._running = True
        
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    print("📡 Binance WebSocket 接続")
                    
                    async for msg in ws:
                        if not self._running:
                            break
                        
                        data = json.loads(msg)
                        symbol = data.get("s", "")
                        
                        price_data = PriceData(
                            symbol=symbol,
                            price=float(data.get("c", 0)),
                            timestamp=datetime.now(),
                            volume_24h=float(data.get("v", 0)),
                            change_24h=float(data.get("P", 0)),
                        )
                        
                        if "BTC" in symbol:
                            self.btc_prices.append(price_data)
                        elif "ETH" in symbol:
                            self.eth_prices.append(price_data)
                        
                        if callback:
                            await callback(price_data)
                            
            except Exception as e:
                print(f"WebSocket エラー: {e}")
                if self._running:
                    await asyncio.sleep(5)  # 再接続待機
    
    def stop_price_stream(self):
        """価格ストリーム停止"""
        self._running = False
    
    # ========== Polymarket マーケット取得 ==========
    
    async def get_crypto_markets(
        self,
        keywords: List[str] = None,
        limit: int = 100,
        min_liquidity: float = 5_000,
        min_volume: float = 10_000,
    ) -> List[MarketData]:
        """
        アクティブマーケットを出来高順に取得してフィルタリング。
        キーワード検索はPolymarketの質問文と一致しないため廃止。
        """
        markets = []
        offset = 0
        fetch_per_page = 100
        max_pages = 10
        now = datetime.now(timezone.utc)

        async with httpx.AsyncClient() as client:
            for _ in range(max_pages):
                if len(markets) >= limit:
                    break
                try:
                    resp = await client.get(
                        f"{GAMMA_API}/markets",
                        params={
                            "active": "true",
                            "closed": "false",
                            "limit": fetch_per_page,
                            "offset": offset,
                            "order": "volume",
                            "ascending": "false",
                        }
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if not data:
                        break

                    for m in data:
                        if m.get("closed", False):
                            continue

                        # トークンID
                        clob_ids = m.get("clobTokenIds", "[]")
                        try:
                            token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                        except:
                            token_ids = []
                        yes_token_id = token_ids[0] if token_ids else ""
                        no_token_id = token_ids[1] if len(token_ids) > 1 else None
                        if not yes_token_id:
                            continue

                        # 価格
                        outcome_prices = m.get("outcomePrices", "[\"0.5\", \"0.5\"]")
                        try:
                            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                            yes_price = float(prices[0]) if prices else 0.5
                        except:
                            yes_price = 0.5

                        # 終了日時
                        end_date = None
                        end_date_str = m.get("endDateIso") or m.get("end_date_iso")
                        if end_date_str:
                            try:
                                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                            except:
                                pass

                        # end_dateなし・1時間未満・30日超は除外
                        if not end_date:
                            continue
                        ed = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
                        days_left = (ed - now).total_seconds() / 86400
                        if days_left < (1 / 24) or days_left > 30:
                            continue

                        volume = float(m.get("volumeNum") or m.get("volume", 0) or 0)
                        liquidity = float(m.get("liquidityNum") or m.get("liquidity", 0) or 0)

                        if liquidity < min_liquidity or volume < min_volume:
                            continue

                        market = MarketData(
                            market_id=m.get("conditionId") or m.get("condition_id", ""),
                            question=m.get("question", ""),
                            yes_token_id=yes_token_id,
                            no_token_id=no_token_id,
                            yes_price=yes_price,
                            volume=volume,
                            liquidity=liquidity,
                            end_date=ed,
                        )

                        if market.market_id not in [x.market_id for x in markets]:
                            markets.append(market)

                        if len(markets) >= limit:
                            break

                    if len(data) < fetch_per_page:
                        break
                    offset += fetch_per_page

                except Exception as e:
                    print(f"マーケット取得エラー: {e}")
                    break

        markets.sort(key=lambda x: x.volume, reverse=True)
        return markets[:limit]
    
    # ========== 指標計算 ==========
    
    def calc_momentum(self, prices: deque, period: int = 10) -> float:
        """
        モメンタム (価格変化率) を計算
        
        Args:
            prices: 価格履歴
            period: 期間 (分)
        
        Returns:
            変化率 (%)
        """
        if len(prices) < period:
            return 0
        
        current = prices[-1].price
        past = prices[-period].price
        
        if past == 0:
            return 0
        
        return (current - past) / past * 100
    
    def calc_volatility(self, prices: deque, period: int = 20) -> float:
        """
        ボラティリティ (標準偏差) を計算
        """
        if len(prices) < period:
            return 0
        
        recent = [p.price for p in list(prices)[-period:]]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        
        return variance ** 0.5
    
    # ========== スキャン実行 ==========
    
    async def scan(
        self,
        min_liquidity: float = 5_000,
        min_volume: float = 10_000,
    ) -> ScanResult:
        """
        フルスキャン実行

        Args:
            min_liquidity: 最低流動性フィルター ($)
            min_volume: 最低出来高フィルター ($)
        """
        print(f"\n🔍 スキャン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   フィルター: 流動性>${min_liquidity:,.0f} / 出来高>${min_volume:,.0f}")

        # 並列で取得
        btc_task = self.get_binance_price("BTCUSDT")
        eth_task = self.get_binance_price("ETHUSDT")
        markets_task = self.get_crypto_markets(
            min_liquidity=min_liquidity,
            min_volume=min_volume,
        )
        
        btc_price, eth_price, markets = await asyncio.gather(
            btc_task, eth_task, markets_task
        )
        
        # 価格履歴に追加
        if btc_price:
            self.btc_prices.append(btc_price)
        if eth_price:
            self.eth_prices.append(eth_price)
        
        # 指標計算
        btc_momentum = self.calc_momentum(self.btc_prices)
        eth_momentum = self.calc_momentum(self.eth_prices)
        btc_volatility = self.calc_volatility(self.btc_prices)
        eth_volatility = self.calc_volatility(self.eth_prices)
        
        # 結果表示
        if btc_price:
            print(f"  BTC: ${btc_price.price:,.0f} ({btc_price.change_24h:+.1f}%)")
        if eth_price:
            print(f"  ETH: ${eth_price.price:,.0f} ({eth_price.change_24h:+.1f}%)")
        print(f"  マーケット数: {len(markets)}")
        
        return ScanResult(
            timestamp=datetime.now(),
            btc_price=btc_price,
            eth_price=eth_price,
            markets=markets,
        )
    
    async def run_loop(
        self,
        interval_minutes: int = 60,
        callback: Callable = None,
    ):
        """
        定期スキャンループ
        
        Args:
            interval_minutes: スキャン間隔 (分)
            callback: スキャン結果コールバック
        """
        print(f"🚀 Scanner 開始 (間隔: {interval_minutes}分)")
        
        while True:
            try:
                result = await self.scan()
                
                if callback:
                    await callback(result)
                
                # 次回まで待機
                await asyncio.sleep(interval_minutes * 60)
                
            except KeyboardInterrupt:
                print("\n👋 Scanner 停止")
                break
            except Exception as e:
                print(f"❌ スキャンエラー: {e}")
                await asyncio.sleep(60)  # エラー時は1分待機


# テスト用
async def _test():
    scanner = MarketScanner()
    result = await scanner.scan()
    
    print(f"\n📊 スキャン結果:")
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    print(f"\n🎯 トップ5マーケット:")
    for m in result.markets[:5]:
        print(f"  • {m.question[:60]}")
        print(f"    YES: {m.yes_price:.1%} | Vol: ${m.volume:,.0f}")


if __name__ == "__main__":
    asyncio.run(_test())
