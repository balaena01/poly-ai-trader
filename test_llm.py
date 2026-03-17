"""
LiteLLM 動作確認スクリプト
Usage:
  python test_llm.py
  python test_llm.py --model claude-sonnet-4.6
  python test_llm.py --model anthropic/claude-haiku-4-5-20251001
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def test(model: str):
    try:
        import litellm
    except ImportError:
        print("❌ litellm not installed: pip install litellm")
        return

    litellm.suppress_debug_info = True

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    print(f"ANTHROPIC_API_KEY : {key[:15]}..." if key else "ANTHROPIC_API_KEY : NOT SET")
    print(f"model             : {model}")
    print()

    try:
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Say hi in one word."}],
            max_tokens=10,
        )
        print(f"✅ OK: {resp.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="anthropic/claude-haiku-4-5-20251001",
        help="LiteLLM モデル名 (default: anthropic/claude-haiku-4-5-20251001)",
    )
    args = parser.parse_args()
    asyncio.run(test(args.model))
