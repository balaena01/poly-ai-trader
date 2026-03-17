"""
Claude Code CLI 動作確認スクリプト
Usage:
  python test_llm.py
  python test_llm.py --model claude-sonnet-4.6
  python test_llm.py --model claude-haiku-4-5-20251001 --continue
"""
import argparse
import asyncio

from analyst.llm_analyst import LLMAnalyst, MODELS, DEFAULT_MODEL


async def test(model: str, use_continue: bool):
    print(f"model       : {model}")
    print(f"--continue  : {use_continue}")
    print()

    analyst = LLMAnalyst(model=model, use_continue=use_continue)

    result = await analyst.analyze_market(
        question="Will the sun rise tomorrow?",
        current_price=0.99,
    )

    if result:
        print(f"✅ OK: {result}")
    else:
        print("❌ 結果なし")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"モデル名 (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--continue",
        dest="use_continue",
        action="store_true",
        help="--continue フラグを使用",
    )
    args = parser.parse_args()
    asyncio.run(test(args.model, args.use_continue))
