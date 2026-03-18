"""
Polymarket Client Wrapper
py-clob-client をラップしたシンプルなインターフェース
"""
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

# py-clob-client
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        OrderArgs,
        MarketOrderArgs,
        OrderType,
        BookParams,
    )
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False
    print("Warning: py-clob-client not installed. Run: pip install py-clob-client")


# Constants
HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class Market:
    """マーケット情報"""
    id: str
    question: str
    description: str
    outcomes: List[str]
    tokens: List[Dict[str, Any]]
    end_date: Optional[str] = None
    volume: float = 0
    liquidity: float = 0
    
    @property
    def yes_token_id(self) -> Optional[str]:
        """YESトークンID"""
        for t in self.tokens:
            if t.get("outcome") == "Yes":
                return t.get("token_id")
        return self.tokens[0].get("token_id") if self.tokens else None
    
    @property
    def no_token_id(self) -> Optional[str]:
        """NOトークンID"""
        for t in self.tokens:
            if t.get("outcome") == "No":
                return t.get("token_id")
        return self.tokens[1].get("token_id") if len(self.tokens) > 1 else None


@dataclass
class OrderBook:
    """オーダーブック"""
    token_id: str
    bids: List[Dict[str, Any]]  # 買い注文
    asks: List[Dict[str, Any]]  # 売り注文
    
    @property
    def best_bid(self) -> Optional[float]:
        """最良買い気配"""
        if self.bids:
            return float(self.bids[0].get("price", 0))
        return None
    
    @property
    def best_ask(self) -> Optional[float]:
        """最良売り気配"""
        if self.asks:
            return float(self.asks[0].get("price", 0))
        return None
    
    @property
    def spread(self) -> Optional[float]:
        """スプレッド"""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None


@dataclass
class Position:
    """ポジション"""
    market_id: str
    token_id: str
    outcome: str
    size: float
    avg_price: float
    current_price: float
    
    @property
    def pnl(self) -> float:
        """損益"""
        return (self.current_price - self.avg_price) * self.size
    
    @property
    def pnl_pct(self) -> float:
        """損益率"""
        if self.avg_price > 0:
            return (self.current_price - self.avg_price) / self.avg_price * 100
        return 0


@dataclass
class TradeResult:
    """取引結果"""
    success: bool
    order_id: Optional[str] = None
    message: str = ""


class PolyClient:
    """Polymarket クライアント"""
    
    def __init__(
        self,
        private_key: str = None,
        funder: str = None,
        signature_type: int = 0,
        chain_id: int = 137,
    ):
        """
        Polymarket クライアント初期化
        
        Args:
            private_key: ウォレットの秘密鍵
            funder: 資金を保持するアドレス (proxy wallet使用時)
            signature_type: 0=EOA, 1=Magic, 2=Browser proxy
            chain_id: Polygon chain ID (137)
        """
        if not CLOB_AVAILABLE:
            raise RuntimeError("py-clob-client not installed")
        
        self.private_key = private_key or os.getenv("POLY_PRIVATE_KEY")
        self.funder = funder or os.getenv("POLY_FUNDER_ADDRESS")
        self.signature_type = signature_type or int(os.getenv("POLY_SIGNATURE_TYPE", "0"))
        self.chain_id = chain_id or int(os.getenv("POLY_CHAIN_ID", "137"))
        
        self._client = None
        self._authenticated = False
    
    def connect(self, read_only: bool = False) -> bool:
        """
        Polymarket に接続
        
        Args:
            read_only: 読み取り専用モード (認証不要)
        """
        try:
            if read_only or not self.private_key:
                # 読み取り専用
                self._client = ClobClient(HOST)
                print("📊 Polymarket接続 (読み取り専用)")
                return True
            
            # 認証付き接続
            self._client = ClobClient(
                HOST,
                key=self.private_key,
                chain_id=self.chain_id,
                signature_type=self.signature_type,
                funder=self.funder,
            )
            
            # API認証情報を設定
            self._client.set_api_creds(self._client.create_or_derive_api_creds())
            self._authenticated = True

            # USDC allowance を on-chain から CLOB API へ同期し、残高を確認
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                # on-chain 状態を CLOB API に同期 (これがないと "not enough allowance" になる)
                self._client.update_balance_allowance(params=params)
                # 同期後の実際の値を取得してログ
                result = self._client.get_balance_allowance(params=params)
                balance = float(result.get("balance", 0)) / 1e6 if result else 0
                allowances_dict = result.get("allowances", {}) if result else {}
                if allowances_dict and any(int(v) > 1e30 for v in allowances_dict.values()):
                    allowance_str = "∞"
                elif allowances_dict:
                    min_a = min(float(v) / 1e6 for v in allowances_dict.values())
                    allowance_str = f"${min_a:.2f}"
                else:
                    allowance_str = "$0.00"
                print(f"✅ Polymarket接続成功 (認証済み) balance=${balance:.2f} allowance={allowance_str}")
            except Exception as ae:
                print(f"✅ Polymarket接続成功 (認証済み) ⚠️ 残高確認失敗: {ae}")

            return True
            
        except Exception as e:
            print(f"❌ 接続エラー: {e}")
            return False
    
    # ========== マーケットデータ ==========

    def get_market(self, market_id: str) -> Optional[dict]:
        """単一マーケットの生データを Gamma API から取得
        market_id は 0x... 形式の conditionId を想定。
        Gamma API は conditionId フィルタが効かないため、
        closed マーケット一覧を取得して条件IDで突合する。
        """
        import httpx
        market_id_lower = market_id.lower()
        try:
            # closed=true で取得して conditionId で突合
            for closed_val in ("true", "false"):
                resp = httpx.get(
                    f"{GAMMA_API}/markets",
                    params={"closed": closed_val, "limit": 100},
                    timeout=10,
                )
                resp.raise_for_status()
                markets = resp.json()
                if not isinstance(markets, list):
                    continue
                for m in markets:
                    cid = str(m.get("conditionId") or m.get("condition_id") or "").lower()
                    if cid == market_id_lower:
                        return m
            return None
        except Exception:
            return None

    def get_market_resolution(self, market_id: str, _debug: bool = False) -> Optional[float]:
        """
        マーケットの解決結果を返す。
        Returns: 1.0 (YES), 0.0 (NO), None (未解決 or 取得失敗)
        """
        import json as _json
        data = self.get_market(market_id)
        if not data:
            if _debug:
                print(f"   [resolution debug] market not found: {market_id[:20]}...")
            return None

        if _debug:
            print(f"   [resolution debug] closed={data.get('closed')} "
                  f"resolved={data.get('resolved')} active={data.get('active')} "
                  f"outcomePrices={data.get('outcomePrices')} "
                  f"resolutionResult={data.get('resolutionResult')}")

        # closed も resolved もなければ未解決
        if not data.get("closed") and not data.get("resolved"):
            return None

        print(f"   [resolution debug] closed={data.get('closed')} resolved={data.get('resolved')} "
              f"active={data.get('active')} outcomePrices={data.get('outcomePrices')} "
              f"resolutionResult={data.get('resolutionResult')} "
              f"question={str(data.get('question',''))[:40]}")

        # outcomePrices: ["1", "0"] → YES勝ち, ["0", "1"] → NO勝ち
        # ["0","0"] は「結果未確定」または「VOID」の両方で使われるため信頼できない → スキップ
        op_raw = data.get("outcomePrices", "[]")
        try:
            op = _json.loads(op_raw) if isinstance(op_raw, str) else op_raw
            if op and len(op) >= 2:
                p0, p1 = float(op[0]), float(op[1])
                if p0 >= 0.99:
                    return 1.0
                elif p1 >= 0.99:
                    return 0.0
                # [0,0] は無視 (未確定 or VOID の区別不可)
        except Exception:
            pass

        # resolutionResult / resolution フィールドで判定
        rs = str(data.get("resolutionResult") or data.get("resolution") or "").strip().upper()
        if rs in ("1", "YES", "TRUE"):
            return 1.0
        if rs in ("0", "NO", "FALSE"):
            return 0.0

        return None

    def get_markets(self, limit: int = 100, active: bool = True) -> List[Market]:
        """
        マーケット一覧を取得
        
        Note: Gamma API経由でマーケット情報を取得
        """
        import httpx
        
        params = {
            "limit": limit,
            "active": str(active).lower(),
            "closed": "false",  # 終了済みマーケット除外
        }
        
        try:
            resp = httpx.get(f"{GAMMA_API}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            
            markets = []
            for m in data:
                markets.append(Market(
                    id=m.get("condition_id", ""),
                    question=m.get("question", ""),
                    description=m.get("description", ""),
                    outcomes=m.get("outcomes", []),
                    tokens=m.get("tokens", []),
                    end_date=m.get("end_date_iso"),
                    volume=float(m.get("volume", 0) or 0),
                    liquidity=float(m.get("liquidity", 0) or 0),
                ))
            
            return markets
            
        except Exception as e:
            print(f"マーケット取得エラー: {e}")
            return []
    
    def search_markets(self, query: str, limit: int = 20) -> List[Market]:
        """マーケットを検索"""
        import httpx
        
        try:
            resp = httpx.get(
                f"{GAMMA_API}/markets",
                params={
                    "_q": query,
                    "limit": limit,
                    "active": "true",
                    "closed": "false",  # 終了済みマーケット除外
                }
            )
            resp.raise_for_status()
            data = resp.json()
            
            markets = []
            for m in data:
                markets.append(Market(
                    id=m.get("condition_id", ""),
                    question=m.get("question", ""),
                    description=m.get("description", ""),
                    outcomes=m.get("outcomes", []),
                    tokens=m.get("tokens", []),
                    volume=float(m.get("volume", 0) or 0),
                ))
            
            return markets
            
        except Exception as e:
            print(f"検索エラー: {e}")
            return []
    
    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """トークンの現在価格を取得"""
        if not self._client:
            return None

        try:
            result = self._client.get_price(token_id, side=side)
            # py-clob-client は {'price': '0.65'} 形式の dict を返す
            if isinstance(result, dict):
                result = result.get("price")
            return float(result) if result is not None else None
        except Exception as e:
            print(f"価格取得エラー: {e}")
            return None
    
    def get_midpoint(self, token_id: str) -> Optional[float]:
        """中間価格を取得"""
        if not self._client:
            return None

        try:
            result = self._client.get_midpoint(token_id)
            # py-clob-client は {'mid': '0.65'} 形式の dict を返す
            if isinstance(result, dict):
                result = result.get("mid")
            return float(result) if result is not None else None
        except Exception as e:
            err_str = str(e)
            if "404" not in err_str and "No orderbook" not in err_str:
                print(f"中間価格取得エラー: {e}")
            return None
    
    def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """オーダーブックを取得"""
        if not self._client:
            return None
        
        try:
            book = self._client.get_order_book(token_id)
            return OrderBook(
                token_id=token_id,
                bids=book.bids if hasattr(book, 'bids') else [],
                asks=book.asks if hasattr(book, 'asks') else [],
            )
        except Exception as e:
            print(f"オーダーブック取得エラー: {e}")
            return None
    
    # ========== 取引 ==========
    
    def buy(
        self,
        token_id: str,
        amount: float,
        price: float = None,
        order_type: str = "GTC",
    ) -> TradeResult:
        """
        買い注文
        
        Args:
            token_id: トークンID
            amount: 金額 (USDC)
            price: 指値価格 (Noneの場合は成行)
            order_type: GTC, FOK, IOC
        """
        return self._place_order(token_id, BUY, amount, price, order_type)
    
    def sell(
        self,
        token_id: str,
        amount: float,
        price: float = None,
        order_type: str = "GTC",
    ) -> TradeResult:
        """
        売り注文
        
        Args:
            token_id: トークンID
            amount: 金額 (USDC)
            price: 指値価格 (Noneの場合は成行)
            order_type: GTC, FOK, IOC
        """
        return self._place_order(token_id, SELL, amount, price, order_type)
    
    def _place_order(
        self,
        token_id: str,
        side: str,
        amount: float,
        price: float = None,
        order_type: str = "GTC",
    ) -> TradeResult:
        """注文を発注"""
        if not self._authenticated:
            return TradeResult(success=False, message="未認証")
        
        try:
            ot = getattr(OrderType, order_type, OrderType.GTC)
            
            if price is None:
                # 成行注文
                order = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                    side=side,
                    order_type=OrderType.FOK,
                )
                signed = self._client.create_market_order(order)
                resp = self._client.post_order(signed, OrderType.FOK)
            else:
                # 指値注文
                # amount を size に変換 (shares = amount / price)
                # maker amount: 小数2桁まで, taker amount (size): 小数4桁まで
                # price: 小数4桁まで (浮動小数点誤差 1-0.66=0.3399... 対策)
                amount = round(amount, 2)
                price = round(price, 4)
                size = round(amount / price, 4)
                order = OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side,
                )
                signed = self._client.create_order(order)
                resp = self._client.post_order(signed, ot)
            
            return TradeResult(
                success=True,
                order_id=resp.get("orderID") if isinstance(resp, dict) else str(resp),
                message="注文成功",
            )
            
        except Exception as e:
            return TradeResult(success=False, message=str(e))
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """注文ステータスを取得 (status: LIVE / MATCHED / CANCELLED)"""
        if not self._authenticated:
            return None
        try:
            return self._client.get_order(order_id)
        except Exception:
            return None

    def cancel_order(self, order_id: str) -> TradeResult:
        """注文をキャンセル"""
        if not self._authenticated:
            return TradeResult(success=False, message="未認証")
        
        try:
            self._client.cancel(order_id)
            return TradeResult(success=True, message="キャンセル成功")
        except Exception as e:
            return TradeResult(success=False, message=str(e))
    
    def cancel_all(self) -> TradeResult:
        """全注文をキャンセル"""
        if not self._authenticated:
            return TradeResult(success=False, message="未認証")
        
        try:
            self._client.cancel_all()
            return TradeResult(success=True, message="全キャンセル成功")
        except Exception as e:
            return TradeResult(success=False, message=str(e))
    
    # ========== ポジション ==========
    
    def get_positions(self) -> List[Position]:
        """オープンポジションを取得"""
        # Note: CLOB APIではポジション取得は別エンドポイント
        # TODO: 実装
        return []
    
    def get_balance(self) -> float:
        """USDC残高を取得

        優先順位:
        1. CLOB API (認証済み時) — Polymarketに預けた実残高
        2. オンチェーン Web3 — proxy walletのUSDC残高 (fallback)
        """
        # ── 1. CLOB API (最も正確) ──────────────────────────────────────────
        # get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        # でPolymarket内のUSDC残高を取得する
        if self._authenticated and self._client:
            try:
                from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                result = self._client.get_balance_allowance(params)
                if result and "balance" in result:
                    balance_str = result["balance"]
                    # Polymarketの残高はUSDC(6 decimals)
                    return float(balance_str) / 1e6
            except Exception:
                pass  # CLOBで取れなければWeb3にフォールバック

        # ── 2. オンチェーン Web3 (fallback) ──────────────────────────────────
        if not self.funder:
            return 0.0

        try:
            from web3 import Web3

            # Polygon RPC (public endpoints)
            rpc_urls = [
                "https://polygon.llamarpc.com",
                "https://rpc.ankr.com/polygon",
                "https://polygon.drpc.org",
            ]

            w3 = None
            for rpc_url in rpc_urls:
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
                    if w3.is_connected():
                        break
                except Exception:
                    continue

            if not w3 or not w3.is_connected():
                return 0.0

            # USDC on Polygon (native + bridged)
            usdc_addresses = [
                "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC
                "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # Bridged USDC.e
            ]

            abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]

            total_balance = 0.0
            for usdc_address in usdc_addresses:
                try:
                    contract = w3.eth.contract(address=Web3.to_checksum_address(usdc_address), abi=abi)
                    balance_wei = contract.functions.balanceOf(Web3.to_checksum_address(self.funder)).call()
                    total_balance += balance_wei / 10**6  # USDC = 6 decimals
                except Exception:
                    continue

            return total_balance

        except Exception as e:
            print(f"残高取得エラー: {e}")
            return 0.0
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """オープンオーダーを取得"""
        if not self._authenticated:
            return []
        
        try:
            return self._client.get_orders()
        except Exception as e:
            print(f"注文取得エラー: {e}")
            return []


# テスト用
def _test():
    client = PolyClient()
    
    # 読み取り専用で接続
    if not client.connect(read_only=True):
        print("接続失敗")
        return
    
    # マーケット検索
    print("\n🔍 'Trump' で検索...")
    markets = client.search_markets("Trump", limit=5)
    
    for m in markets:
        print(f"\n📊 {m.question[:60]}...")
        print(f"   Volume: ${m.volume:,.0f}")
        
        if m.yes_token_id:
            price = client.get_midpoint(m.yes_token_id)
            if price:
                print(f"   YES価格: {price:.2%}")


if __name__ == "__main__":
    _test()
