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
class PositionReview:
    """ポジションレビュー結果"""
    should_exit: bool
    reason: str


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
    llm_is_sport: Optional[bool] = None  # LLMによるスポーツ市場判定

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
5. is_sport: このマーケットがスポーツ・eスポーツ・格闘技・競馬など「競技の勝敗や試合結果」に関するものであれば true。
   - true の例: NFL試合の勝者、NBAチャンピオン、テニス大会の優勝者、UFC試合結果、競馬レース、esports大会
   - false の例: BTC価格予測、大統領選挙、経済指標、エンタメ・映画、政治イベント
   - 判断が難しい場合は false (false side-safe)
6. is_correlated: 「保有中のポジション」が提供されている場合、分析対象マーケットがそれらと同一または強く相関するイベントであれば true。
   - true の例: 同じ試合の別条件、同じ選挙で排他的な結果、同じ資産の別閾値、同じ地政学イベントの別スケール
   - false の例: 明らかに無関係なイベント、保有ポジションが提供されていない場合
   - 判断が難しい場合は false (false side-safe)

## 出力形式 (JSON のみ。他のテキスト不要)
{"probability": 0.65, "confidence": 0.7, "reasoning": "理由を簡潔に", "is_sport": false, "is_correlated": false, "correlation_reason": ""}
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
            "-p", "-",            # stdin からプロンプトを読む (引数長制限を回避)
            "--model", self.model,
            "--output-format", "json",
            "--dangerously-skip-permissions",
        ]
        if self.use_continue:
            cmd.append("--continue")

        # ANTHROPIC_API_KEY を env から除外: セットされていると CLI がそれを使って
        # 直接 API 呼び出しをしてしまい、キーのモデル制限に引っかかる。
        # 除外することで CLI 自身の OAuth 認証 (~/.claude/) を使わせる。
        import os
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
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
            if "price_history" in context:
                ctx_text += f"\n\n価格推移(日足): {context['price_history']}"
            if "news" in context:
                ctx_text += f"\n\n関連ニュース:\n{context['news']}"
            if "previous_judgment" in context:
                ctx_text += f"\n\n{context['previous_judgment']}"
            if "performance_context" in context:
                ctx_text += f"\n\n{context['performance_context']}"
            if "open_positions_context" in context:
                ctx_text += f"\n\n{context['open_positions_context']}"

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

    async def review_position(
        self,
        question: str,
        side: str,
        entry_price: float,
        current_price: float,
        pnl_pct: float,
        days_left: float,
        entry_thesis: str = "",
        news: str = "",
        price_chart: str = "",
    ) -> PositionReview:
        """
        保有ポジションの出口判断をLLMに問う。

        Returns:
            PositionReview(should_exit, reason)
        """
        news_section = f"\n[直近ニュース]\n{news}" if news else ""
        chart_section = f"\n[価格推移 (直近7日)]\n{price_chart}" if price_chart else ""
        thesis_section = f"\n[エントリー時の根拠]\n{entry_thesis}" if entry_thesis else ""

        prompt = f"""あなたは保有ポジションの出口判断を行うトレーダーです。
以下の情報をもとに、**今すぐクローズすべきか**を判断してください。

[ポジション]
問い: {question}
方向: {side} (エントリー価格: {entry_price:.1%})
現在: {current_price:.1%} (PnL: {pnl_pct:+.1%}, 残り{days_left:.0f}日){thesis_section}{news_section}{chart_section}

## 判断基準
- エントリー時のthesisが崩れていればクローズ
- 新情報がthesisを支持していれば継続
- 残り日数が少なく損失が拡大中ならクローズ
- 利益が出ており更なる伸びが見込めるなら継続

JSON形式のみで回答:
{{"should_exit": true/false, "reason": "理由を1文で"}}
"""
        try:
            raw = await self._call_cli(prompt)
            data = self._parse_llm_json(raw)
            if data and "should_exit" in data:
                return PositionReview(
                    should_exit=bool(data["should_exit"]),
                    reason=data.get("reason", ""),
                )
        except Exception as e:
            print(f"LLMポジションレビューエラー: {e}")
        return PositionReview(should_exit=False, reason="レビュー失敗")

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
