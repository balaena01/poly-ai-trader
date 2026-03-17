"""
LLM Analyst
- Claude Code CLI をサブプロセスで呼び出して市場分析
- litellm 不要・API キー設定不要 (Claude Code の認証を使用)
- 売買シグナル生成
"""
import json
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from enum import Enum


class Action(Enum):
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    HOLD = "hold"


@dataclass
class Signal:
    """売買シグナル"""
    action: Action
    market_id: str
    token_id: str
    question: str
    market_price: float
    predicted_prob: float
    confidence: float
    edge: float
    reasoning: str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @property
    def is_tradeable(self) -> bool:
        return abs(self.edge) > 0.10 and self.confidence > 0.6

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "question": self.question[:50],
            "market_price": f"{self.market_price:.1%}",
            "predicted": f"{self.predicted_prob:.1%}",
            "edge": f"{self.edge:+.1%}",
            "confidence": f"{self.confidence:.0%}",
            "tradeable": self.is_tradeable,
        }


# Claude Code CLI で使えるモデル名 (anthropic/ プレフィックス不要)
MODELS = {
    "claude-opus-4.6":          "claude-opus-4-6",
    "claude-sonnet-4.6":        "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
    "claude-sonnet-4.5":        "claude-sonnet-4-5-20250929",
    "claude-opus-4.5":          "claude-opus-4-5-20251101",
    "claude-sonnet-4":          "claude-sonnet-4-20250514",
    "claude-opus-4":            "claude-opus-4-20250514",
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class LLMAnalyst:
    """Claude Code CLI を使った市場分析"""

    SYSTEM_PROMPT = """あなたは予測市場のアナリストです。
与えられた情報から、イベントが「YES」で解決する確率を予測してください。

## ルール
1. 客観的データに基づいて分析すること
2. バイアスを避け、確率を正確に見積もること
3. 不確実性が高い場合は confidence を下げること
4. 根拠を簡潔に説明すること

## 出力形式 (JSON のみ。他のテキスト不要)
{"probability": 0.65, "confidence": 0.7, "reasoning": "理由を簡潔に"}
"""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        use_continue: bool = False,
        timeout: int = 60,
    ):
        """
        Args:
            model: モデル名 (MODELS のキーまたは完全な API model name)
            use_continue: --continue フラグを使うか (直前の会話を継続)
            timeout: サブプロセスのタイムアウト秒数
        """
        self.model = MODELS.get(model, model)
        self.use_continue = use_continue
        self.timeout = timeout
        print(f"🤖 LLM (Claude CLI): {self.model}")

    def _parse_llm_json(self, content: str) -> Optional[dict]:
        """LLMレスポンスからJSONを抽出"""
        if not content or not content.strip():
            return None
        text = content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        prob = re.search(r'"probability"\s*:\s*([0-9.]+)', text)
        conf = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
        if prob:
            return {
                "probability": float(prob.group(1)),
                "confidence": float(conf.group(1)) if conf else 0.5,
                "reasoning": "",
            }
        return None

    async def _call_cli(self, prompt: str) -> str:
        """Claude Code CLI をサブプロセスで呼び出す"""
        cmd = [
            "claude",
            "-p", prompt,
            "--model", self.model,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]
        if self.use_continue:
            cmd.append("--continue")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Claude CLI タイムアウト ({self.timeout}s)")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Claude CLI エラー (code={proc.returncode}): {err}")

        # --output-format json → {"result": "...", ...} の result フィールドを取り出す
        raw = stdout.decode("utf-8", errors="replace")
        try:
            wrapper = json.loads(raw)
            return wrapper.get("result", raw)
        except Exception:
            return raw

    async def analyze_market(
        self,
        question: str,
        current_price: float,
        context: dict = None,
    ) -> Optional[dict]:
        """
        マーケットを分析

        Returns:
            {"probability": float, "confidence": float, "reasoning": str}
        """
        ctx_text = ""
        if context:
            if "btc_price" in context:
                ctx_text += f"\nBTC価格: ${context['btc_price']:,.0f}"
            if "btc_change" in context:
                ctx_text += f" (24h: {context['btc_change']:+.1f}%)"
            if "eth_price" in context:
                ctx_text += f"\nETH価格: ${context['eth_price']:,.0f}"
            if "eth_change" in context:
                ctx_text += f" (24h: {context['eth_change']:+.1f}%)"
            if "news" in context:
                ctx_text += f"\n\n関連ニュース:\n{context['news']}"
            if "previous_judgment" in context:
                ctx_text += f"\n\n{context['previous_judgment']}"

        full_prompt = f"""{self.SYSTEM_PROMPT}
## 予測対象
質問: {question}
現在のマーケット価格 (YES): {current_price:.1%}

## コンテキスト{ctx_text if ctx_text else " なし"}

## タスク
この質問が「YES」で解決する確率を予測してください。
JSONのみで回答してください。
"""
        try:
            raw = await self._call_cli(full_prompt)
            return self._parse_llm_json(raw)
        except Exception as e:
            print(f"LLM分析エラー: {e}")
            return None

    async def generate_signals(
        self,
        markets: list,
        btc_price: float = None,
        btc_change: float = None,
        eth_price: float = None,
        eth_change: float = None,
        min_edge: float = 0.10,
        max_markets: int = 5,
    ) -> List[Signal]:
        """複数マーケットからシグナルを生成"""
        signals = []

        context = {}
        if btc_price:
            context["btc_price"] = btc_price
        if btc_change:
            context["btc_change"] = btc_change
        if eth_price:
            context["eth_price"] = eth_price
        if eth_change:
            context["eth_change"] = eth_change

        for market in markets[:max_markets]:
            print(f"  📊 分析中: {market.question[:40]}...")

            result = await self.analyze_market(
                question=market.question,
                current_price=market.yes_price,
                context=context,
            )

            if not result:
                continue

            prob = result.get("probability", 0.5)
            conf = result.get("confidence", 0.5)
            reason = result.get("reasoning", "")
            edge = prob - market.yes_price

            if edge > min_edge:
                action = Action.BUY_YES
                token_id = market.yes_token_id
            elif edge < -min_edge:
                action = Action.BUY_NO
                token_id = market.no_token_id or market.yes_token_id
            else:
                action = Action.HOLD
                token_id = market.yes_token_id

            signals.append(Signal(
                action=action,
                market_id=market.market_id,
                token_id=token_id,
                question=market.question,
                market_price=market.yes_price,
                predicted_prob=prob,
                confidence=conf,
                edge=edge,
                reasoning=reason,
            ))

        signals.sort(key=lambda x: abs(x.edge), reverse=True)
        return signals


def list_models():
    """利用可能なモデル一覧"""
    print("\n🤖 Claude Code CLI モデル一覧:\n")
    for key, val in MODELS.items():
        print(f"  {key:30} → {val}")
    print(f"\n📌 デフォルト: {DEFAULT_MODEL}")


# テスト用
async def _test():
    from scanner import MarketScanner

    scanner = MarketScanner()
    result = await scanner.scan()

    analyst = LLMAnalyst(model=DEFAULT_MODEL)
    signals = await analyst.generate_signals(
        markets=result.markets[:2],
        min_edge=0.05,
    )
    for s in signals:
        print(s.to_dict())


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "models":
        list_models()
    else:
        asyncio.run(_test())
