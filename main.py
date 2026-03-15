#!/usr/bin/env python3
"""
Poly AI Trader - Polymarket 自動売買システム
"""
import argparse
from client import PolyClient


def cmd_markets(args):
    """マーケット一覧"""
    client = PolyClient()
    client.connect(read_only=True)
    
    if args.query:
        markets = client.search_markets(args.query, limit=args.limit)
        print(f"\n🔍 '{args.query}' の検索結果:\n")
    else:
        markets = client.get_markets(limit=args.limit)
        print(f"\n📊 アクティブマーケット TOP {args.limit}:\n")
    
    for i, m in enumerate(markets, 1):
        print(f"{i:2}. {m.question[:70]}")
        print(f"    Volume: ${m.volume:,.0f} | Liquidity: ${m.liquidity:,.0f}")
        
        if m.yes_token_id:
            price = client.get_midpoint(m.yes_token_id)
            if price:
                print(f"    YES: {price:.1%} | NO: {1-price:.1%}")
        print()


def cmd_price(args):
    """価格確認"""
    client = PolyClient()
    client.connect(read_only=True)
    
    # マーケット検索
    markets = client.search_markets(args.query, limit=5)
    
    if not markets:
        print(f"❌ '{args.query}' に一致するマーケットが見つかりません")
        return
    
    m = markets[0]
    print(f"\n📊 {m.question}\n")
    
    if m.yes_token_id:
        mid = client.get_midpoint(m.yes_token_id)
        buy = client.get_price(m.yes_token_id, "BUY")
        sell = client.get_price(m.yes_token_id, "SELL")
        
        book = client.get_order_book(m.yes_token_id)
        
        print(f"YES トークン:")
        print(f"  中間価格: {mid:.2%}" if mid else "  中間価格: N/A")
        print(f"  買い価格: {buy:.2%}" if buy else "  買い価格: N/A")
        print(f"  売り価格: {sell:.2%}" if sell else "  売り価格: N/A")
        
        if book and book.spread:
            print(f"  スプレッド: {book.spread:.2%}")
        
        print(f"\n  Token ID: {m.yes_token_id}")


def cmd_buy(args):
    """買い注文"""
    client = PolyClient()
    
    if not client.connect():
        print("❌ 認証エラー - 環境変数を確認してください")
        return
    
    print(f"\n🛒 買い注文: {args.amount} USDC @ {args.price or 'market'}")
    print(f"   Token: {args.token_id}")
    
    if not args.confirm:
        print("\n⚠️ 実行するには --confirm を追加してください")
        return
    
    result = client.buy(
        token_id=args.token_id,
        amount=args.amount,
        price=args.price,
    )
    
    if result.success:
        print(f"✅ {result.message}")
        print(f"   Order ID: {result.order_id}")
    else:
        print(f"❌ {result.message}")


def cmd_sell(args):
    """売り注文"""
    client = PolyClient()
    
    if not client.connect():
        print("❌ 認証エラー")
        return
    
    print(f"\n💰 売り注文: {args.amount} USDC @ {args.price or 'market'}")
    print(f"   Token: {args.token_id}")
    
    if not args.confirm:
        print("\n⚠️ 実行するには --confirm を追加してください")
        return
    
    result = client.sell(
        token_id=args.token_id,
        amount=args.amount,
        price=args.price,
    )
    
    if result.success:
        print(f"✅ {result.message}")
    else:
        print(f"❌ {result.message}")


def main():
    parser = argparse.ArgumentParser(description="Poly AI Trader")
    subparsers = parser.add_subparsers(dest="command", help="コマンド")
    
    # markets
    p_markets = subparsers.add_parser("markets", help="マーケット一覧")
    p_markets.add_argument("-q", "--query", help="検索キーワード")
    p_markets.add_argument("-n", "--limit", type=int, default=10, help="件数")
    p_markets.set_defaults(func=cmd_markets)
    
    # price
    p_price = subparsers.add_parser("price", help="価格確認")
    p_price.add_argument("query", help="マーケット検索キーワード")
    p_price.set_defaults(func=cmd_price)
    
    # buy
    p_buy = subparsers.add_parser("buy", help="買い注文")
    p_buy.add_argument("token_id", help="トークンID")
    p_buy.add_argument("amount", type=float, help="金額 (USDC)")
    p_buy.add_argument("-p", "--price", type=float, help="指値価格")
    p_buy.add_argument("--confirm", action="store_true", help="実行確認")
    p_buy.set_defaults(func=cmd_buy)
    
    # sell
    p_sell = subparsers.add_parser("sell", help="売り注文")
    p_sell.add_argument("token_id", help="トークンID")
    p_sell.add_argument("amount", type=float, help="金額 (USDC)")
    p_sell.add_argument("-p", "--price", type=float, help="指値価格")
    p_sell.add_argument("--confirm", action="store_true", help="実行確認")
    p_sell.set_defaults(func=cmd_sell)
    
    args = parser.parse_args()
    
    if args.command:
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
