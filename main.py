#!/usr/bin/env python3
"""
Poly AI Trader - Polymarket 自動売買システム

Phase 1:
- Scanner: BTC/ETH マーケット監視
- Analyst: LLM 分析
- Executor: 注文実行 (ドライラン対応)
"""
import argparse
import asyncio
import json

from client import PolyClient
from scanner import MarketScanner
from analyst import LLMAnalyst
from executor import TradeExecutor


async def cmd_scan(args):
    """マーケットスキャン"""
    scanner = MarketScanner()
    result = await scanner.scan()
    
    print(f"\n📊 スキャン結果:")
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    if args.verbose:
        print(f"\n🎯 全マーケット ({len(result.markets)}件):")
        for i, m in enumerate(result.markets, 1):
            print(f"{i:2}. {m.question[:60]}")
            print(f"    YES: {m.yes_price:.1%} | Vol: ${m.volume:,.0f}")


async def cmd_analyze(args):
    """マーケット分析"""
    print("🔍 スキャン中...")
    scanner = MarketScanner()
    scan_result = await scanner.scan()
    
    print(f"\n🧠 LLM 分析中...")
    analyst = LLMAnalyst(model=args.model)
    
    signals = await analyst.generate_signals(
        markets=scan_result.markets[:args.limit],
        btc_price=scan_result.btc_price.price if scan_result.btc_price else None,
        btc_change=scan_result.btc_price.change_24h if scan_result.btc_price else None,
        eth_price=scan_result.eth_price.price if scan_result.eth_price else None,
        eth_change=scan_result.eth_price.change_24h if scan_result.eth_price else None,
        min_edge=args.min_edge,
    )
    
    print(f"\n🎯 シグナル ({len(signals)}件):")
    for s in signals:
        emoji = "🟢" if s.is_tradeable else "⚪"
        print(f"\n{emoji} {s.question[:50]}")
        print(f"   アクション: {s.action.value}")
        print(f"   マーケット: {s.market_price:.1%} → 予測: {s.predicted_prob:.1%}")
        print(f"   エッジ: {s.edge:+.1%} | 信頼度: {s.confidence:.0%}")
        print(f"   理由: {s.reasoning[:60]}")


async def cmd_trade(args):
    """取引実行"""
    print("🔍 スキャン中...")
    scanner = MarketScanner()
    scan_result = await scanner.scan()
    
    print(f"\n🧠 LLM 分析中...")
    analyst = LLMAnalyst()
    
    signals = await analyst.generate_signals(
        markets=scan_result.markets[:args.limit],
        btc_price=scan_result.btc_price.price if scan_result.btc_price else None,
        btc_change=scan_result.btc_price.change_24h if scan_result.btc_price else None,
        min_edge=args.min_edge,
    )
    
    # 取引可能なシグナルをフィルタ
    tradeable = [s for s in signals if s.is_tradeable]
    
    if not tradeable:
        print("\n⚪ 取引可能なシグナルなし")
        return
    
    print(f"\n🎯 取引可能シグナル ({len(tradeable)}件):")
    for s in tradeable:
        print(f"  • {s.question[:40]} | エッジ: {s.edge:+.1%}")
    
    if not args.execute:
        print("\n⚠️ 実行するには --execute を追加してください")
        return
    
    # 実行
    print(f"\n💰 取引実行中...")
    executor = TradeExecutor(dry_run=args.dry_run)
    results = await executor.execute_signals(tradeable, max_trades=args.max_trades)
    
    print(f"\n📊 実行結果:")
    for r in results:
        status = "✅" if r.success else "❌"
        print(f"  {status} {r.signal.action.value} | {r.message}")
    
    print(f"\n📈 統計: {executor.get_stats()}")


async def cmd_run(args):
    """自動売買ループ"""
    print("🚀 自動売買モード開始")
    print(f"   間隔: {args.interval}分")
    print(f"   ドライラン: {args.dry_run}")
    print(f"   最大取引/回: {args.max_trades}")
    print("\nCtrl+C で停止\n")
    
    scanner = MarketScanner()
    analyst = LLMAnalyst()
    executor = TradeExecutor(dry_run=args.dry_run)
    
    while True:
        try:
            print(f"\n{'='*60}")
            print(f"⏰ {asyncio.get_event_loop().time():.0f}")
            
            # スキャン
            scan_result = await scanner.scan()
            
            # 分析
            print("🧠 分析中...")
            signals = await analyst.generate_signals(
                markets=scan_result.markets[:args.limit],
                btc_price=scan_result.btc_price.price if scan_result.btc_price else None,
                btc_change=scan_result.btc_price.change_24h if scan_result.btc_price else None,
                min_edge=args.min_edge,
            )
            
            # 取引
            tradeable = [s for s in signals if s.is_tradeable]
            
            if tradeable:
                print(f"🎯 シグナル: {len(tradeable)}件")
                results = await executor.execute_signals(tradeable, max_trades=args.max_trades)
            else:
                print("⚪ 取引シグナルなし")
            
            # 統計
            stats = executor.get_stats()
            print(f"📈 累計: {stats}")
            
            # 待機
            print(f"\n⏳ 次回: {args.interval}分後...")
            await asyncio.sleep(args.interval * 60)
            
        except KeyboardInterrupt:
            print("\n\n👋 停止しました")
            print(f"📊 最終統計: {executor.get_stats()}")
            break
        except Exception as e:
            print(f"❌ エラー: {e}")
            await asyncio.sleep(60)


async def cmd_markets(args):
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


def main():
    parser = argparse.ArgumentParser(
        description="Poly AI Trader - Polymarket 自動売買",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python main.py scan                    # マーケットスキャン
  python main.py analyze -n 5            # 5マーケットを分析
  python main.py trade --execute         # 取引実行 (ドライラン)
  python main.py trade --execute --live  # 本番取引
  python main.py run --interval 60       # 自動売買ループ
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="コマンド")
    
    # scan
    p_scan = subparsers.add_parser("scan", help="マーケットスキャン")
    p_scan.add_argument("-v", "--verbose", action="store_true", help="詳細表示")
    
    # analyze
    p_analyze = subparsers.add_parser("analyze", help="LLM分析")
    p_analyze.add_argument("-n", "--limit", type=int, default=5, help="分析数")
    p_analyze.add_argument("--min-edge", type=float, default=0.10, help="最小エッジ")
    p_analyze.add_argument("-m", "--model", default="claude-haiku", help="モデル (claude-haiku, claude-sonnet, gpt-4o-mini, etc.)")
    
    # trade
    p_trade = subparsers.add_parser("trade", help="取引実行")
    p_trade.add_argument("-n", "--limit", type=int, default=5, help="分析数")
    p_trade.add_argument("--min-edge", type=float, default=0.10, help="最小エッジ")
    p_trade.add_argument("--max-trades", type=int, default=3, help="最大取引数")
    p_trade.add_argument("--execute", action="store_true", help="実行確認")
    p_trade.add_argument("--dry-run", action="store_true", default=True, help="ドライラン")
    p_trade.add_argument("--live", action="store_true", help="本番実行")
    
    # run (自動売買ループ)
    p_run = subparsers.add_parser("run", help="自動売買ループ")
    p_run.add_argument("-i", "--interval", type=int, default=60, help="間隔 (分)")
    p_run.add_argument("-n", "--limit", type=int, default=10, help="分析数")
    p_run.add_argument("--min-edge", type=float, default=0.10, help="最小エッジ")
    p_run.add_argument("--max-trades", type=int, default=3, help="最大取引数/回")
    p_run.add_argument("--dry-run", action="store_true", default=True, help="ドライラン")
    p_run.add_argument("--live", action="store_true", help="本番実行")
    
    # markets
    p_markets = subparsers.add_parser("markets", help="マーケット一覧")
    p_markets.add_argument("-q", "--query", help="検索キーワード")
    p_markets.add_argument("-n", "--limit", type=int, default=10, help="件数")
    
    # models
    subparsers.add_parser("models", help="利用可能なLLMモデル一覧")
    
    args = parser.parse_args()
    
    # --live で dry_run を無効化
    if hasattr(args, "live") and args.live:
        args.dry_run = False
    
    if args.command == "scan":
        asyncio.run(cmd_scan(args))
    elif args.command == "analyze":
        asyncio.run(cmd_analyze(args))
    elif args.command == "trade":
        asyncio.run(cmd_trade(args))
    elif args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "markets":
        asyncio.run(cmd_markets(args))
    elif args.command == "models":
        from analyst.llm_analyst import list_models
        list_models()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
