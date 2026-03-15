"""
Polymarket WebSocket Client
- リアルタイムオーダーブック
- 価格更新
- 取引通知
"""
import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable, Any
from enum import Enum

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("Warning: websockets not installed. Run: pip install websockets")


# WebSocket URLs
WS_MARKET = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_USER = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
WS_RTDS = "wss://ws-live-data.polymarket.com"


class MessageType(Enum):
    """メッセージタイプ"""
    BOOK = "book"
    PRICE_CHANGE = "price_change"
    LAST_TRADE_PRICE = "last_trade_price"
    BEST_BID_ASK = "best_bid_ask"
    TICK_SIZE_CHANGE = "tick_size_change"
    NEW_MARKET = "new_market"
    MARKET_RESOLVED = "market_resolved"
    TRADE = "trade"
    ORDER = "order"


@dataclass
class OrderBookUpdate:
    """オーダーブック更新"""
    timestamp: datetime
    asset_id: str
    bids: List[Dict]  # [{price, size}, ...]
    asks: List[Dict]
    
    @property
    def best_bid(self) -> Optional[float]:
        return float(self.bids[0]["price"]) if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return float(self.asks[0]["price"]) if self.asks else None
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


@dataclass
class PriceUpdate:
    """価格更新"""
    timestamp: datetime
    asset_id: str
    price: float
    side: str  # "buy" or "sell"


@dataclass
class TradeUpdate:
    """取引更新"""
    timestamp: datetime
    asset_id: str
    price: float
    size: float
    side: str


class PolyWebSocket:
    """Polymarket WebSocket クライアント"""
    
    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        passphrase: str = None,
    ):
        """
        初期化
        
        Args:
            api_key: API キー (user channel用)
            api_secret: API シークレット
            passphrase: パスフレーズ
        """
        if not WS_AVAILABLE:
            raise RuntimeError("websockets not installed")
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        
        self._ws = None
        self._running = False
        self._subscribed_assets: List[str] = []
        
        # コールバック
        self._callbacks: Dict[MessageType, List[Callable]] = {t: [] for t in MessageType}
        
        # 最新データキャッシュ
        self.order_books: Dict[str, OrderBookUpdate] = {}
        self.last_prices: Dict[str, float] = {}
    
    # ========== コールバック登録 ==========
    
    def on_book(self, callback: Callable[[OrderBookUpdate], None]):
        """オーダーブック更新コールバック"""
        self._callbacks[MessageType.BOOK].append(callback)
    
    def on_price(self, callback: Callable[[PriceUpdate], None]):
        """価格更新コールバック"""
        self._callbacks[MessageType.PRICE_CHANGE].append(callback)
        self._callbacks[MessageType.LAST_TRADE_PRICE].append(callback)
    
    def on_trade(self, callback: Callable[[TradeUpdate], None]):
        """取引コールバック"""
        self._callbacks[MessageType.TRADE].append(callback)
    
    def on_message(self, msg_type: MessageType, callback: Callable[[Dict], None]):
        """汎用コールバック"""
        self._callbacks[msg_type].append(callback)
    
    # ========== 接続管理 ==========
    
    async def connect(
        self,
        asset_ids: List[str],
        channel: str = "market",
        custom_features: bool = True,
    ):
        """
        WebSocket に接続
        
        Args:
            asset_ids: 購読するトークンID
            channel: "market" or "user"
            custom_features: best_bid_ask等を有効化
        """
        url = WS_MARKET if channel == "market" else WS_USER
        
        self._running = True
        self._subscribed_assets = asset_ids
        
        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    print(f"📡 WebSocket接続: {channel}")
                    
                    # 購読メッセージ送信
                    subscribe_msg = {
                        "assets_ids": asset_ids,
                        "type": channel,
                        "custom_feature_enabled": custom_features,
                    }
                    
                    if channel == "user" and self.api_key:
                        subscribe_msg["auth"] = {
                            "apiKey": self.api_key,
                            "secret": self.api_secret,
                            "passphrase": self.passphrase,
                        }
                    
                    await ws.send(json.dumps(subscribe_msg))
                    print(f"  購読: {len(asset_ids)} アセット")
                    
                    # ハートビートとメッセージ受信
                    await asyncio.gather(
                        self._heartbeat(ws),
                        self._receive_messages(ws),
                    )
                    
            except websockets.exceptions.ConnectionClosed:
                if self._running:
                    print("⚠️ 接続断 - 5秒後に再接続...")
                    await asyncio.sleep(5)
            except Exception as e:
                if self._running:
                    print(f"❌ WebSocketエラー: {e}")
                    await asyncio.sleep(5)
    
    async def disconnect(self):
        """切断"""
        self._running = False
        if self._ws:
            await self._ws.close()
            print("👋 WebSocket切断")
    
    async def subscribe(self, asset_ids: List[str]):
        """動的購読追加"""
        if not self._ws:
            return
        
        msg = {
            "assets_ids": asset_ids,
            "operation": "subscribe",
            "custom_feature_enabled": True,
        }
        await self._ws.send(json.dumps(msg))
        self._subscribed_assets.extend(asset_ids)
        print(f"  + 購読追加: {len(asset_ids)} アセット")
    
    async def unsubscribe(self, asset_ids: List[str]):
        """動的購読解除"""
        if not self._ws:
            return
        
        msg = {
            "assets_ids": asset_ids,
            "operation": "unsubscribe",
        }
        await self._ws.send(json.dumps(msg))
        self._subscribed_assets = [a for a in self._subscribed_assets if a not in asset_ids]
        print(f"  - 購読解除: {len(asset_ids)} アセット")
    
    # ========== 内部処理 ==========
    
    async def _heartbeat(self, ws):
        """ハートビート送信 (10秒ごと)"""
        while self._running:
            try:
                await ws.send("PING")
                await asyncio.sleep(10)
            except:
                break
    
    async def _receive_messages(self, ws):
        """メッセージ受信ループ"""
        async for message in ws:
            if message == "PONG":
                continue
            
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"メッセージ処理エラー: {e}")
    
    async def _handle_message(self, data):
        """メッセージ処理"""
        # リストの場合は各要素を処理
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    await self._handle_message(item)
            return
        
        if not isinstance(data, dict):
            return
        
        event_type = data.get("event_type", "")
        
        # オーダーブック
        if event_type == "book":
            update = OrderBookUpdate(
                timestamp=datetime.now(),
                asset_id=data.get("asset_id", ""),
                bids=data.get("bids", []),
                asks=data.get("asks", []),
            )
            self.order_books[update.asset_id] = update
            
            for cb in self._callbacks[MessageType.BOOK]:
                await self._call(cb, update)
        
        # 価格更新
        elif event_type in ("price_change", "last_trade_price"):
            asset_id = data.get("asset_id", "")
            price = float(data.get("price", 0))
            
            self.last_prices[asset_id] = price
            
            update = PriceUpdate(
                timestamp=datetime.now(),
                asset_id=asset_id,
                price=price,
                side=data.get("side", ""),
            )
            
            msg_type = MessageType.PRICE_CHANGE if event_type == "price_change" else MessageType.LAST_TRADE_PRICE
            for cb in self._callbacks[msg_type]:
                await self._call(cb, update)
        
        # ベストBid/Ask
        elif event_type == "best_bid_ask":
            for cb in self._callbacks[MessageType.BEST_BID_ASK]:
                await self._call(cb, data)
        
        # 取引 (user channel)
        elif event_type == "trade":
            update = TradeUpdate(
                timestamp=datetime.now(),
                asset_id=data.get("asset_id", ""),
                price=float(data.get("price", 0)),
                size=float(data.get("size", 0)),
                side=data.get("side", ""),
            )
            
            for cb in self._callbacks[MessageType.TRADE]:
                await self._call(cb, update)
    
    async def _call(self, callback: Callable, *args):
        """コールバック呼び出し (sync/async対応)"""
        if asyncio.iscoroutinefunction(callback):
            await callback(*args)
        else:
            callback(*args)


# テスト
async def _test():
    print("🔌 WebSocket テスト\n")
    
    # テスト用にマーケット取得
    from .history import PriceHistoryFetcher
    
    fetcher = PriceHistoryFetcher()
    markets = await fetcher.fetch_crypto_markets(limit=3)
    
    if not markets:
        print("マーケットなし")
        return
    
    # トークンID取得
    asset_ids = []
    for m in markets:
        tokens = m.get("tokens", [])
        yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
        if yes_token:
            asset_ids.append(yes_token.get("token_id"))
            print(f"  {m.get('question', '')[:50]}")
    
    if not asset_ids:
        print("トークンなし")
        return
    
    # WebSocket接続
    ws = PolyWebSocket()
    
    # コールバック設定
    def on_price(update: PriceUpdate):
        print(f"  💰 価格: {update.price:.4f} ({update.asset_id[:16]}...)")
    
    def on_book(update: OrderBookUpdate):
        print(f"  📊 Book: bid={update.best_bid:.4f} ask={update.best_ask:.4f}")
    
    ws.on_price(on_price)
    ws.on_book(on_book)
    
    print(f"\n📡 接続中... (Ctrl+C で停止)")
    
    try:
        await asyncio.wait_for(
            ws.connect(asset_ids),
            timeout=30,  # 30秒テスト
        )
    except asyncio.TimeoutError:
        print("\n⏰ タイムアウト")
    except KeyboardInterrupt:
        pass
    finally:
        await ws.disconnect()


if __name__ == "__main__":
    asyncio.run(_test())
