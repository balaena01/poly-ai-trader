"""
LLM Analyst
- マーケット情報 + 外部価格を分析
- LiteLLM で複数プロバイダー対応 (Anthropic, OpenAI, etc.)
- 売買シグナル生成
"""
import os
import json
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from enum import Enum

from dotenv import load_dotenv

load_dotenv()

# LiteLLM
try:
    import litellm
    from litellm import acompletion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    print("Warning: litellm not installed. Run: pip install litellm")


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
    market_price: float  # 現在のマーケット価格
    predicted_prob: float  # LLM予測確率
    confidence: float  # 信頼度 (0-1)
    edge: float  # エッジ (predicted - market)
    reasoning: str
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    @property
    def is_tradeable(self) -> bool:
        """取引可能か (エッジ > 閾値)"""
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


# ========== 利用可能なモデル ==========
# LiteLLM は環境変数から自動で API キーを読み込む:
#   ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY

MODELS = {
    # ========== Anthropic (最新) ==========
    # anthropic/ プレフィックスで litellm が確実にルーティング
    "claude-opus-4.6":  "anthropic/claude-opus-4-6",    # 最高性能
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4-6", # バランス
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4-5-20251001",  # 最速・低コスト

    "claude-sonnet-4.5": "anthropic/claude-sonnet-4-5-20250929",
    "claude-opus-4.5":   "anthropic/claude-opus-4-5-20251101",
    "claude-sonnet-4":   "anthropic/claude-sonnet-4-20250514",
    "claude-opus-4":     "anthropic/claude-opus-4-20250514",

    # claude-3-haiku-20240307 は Deprecated (2026/4/20 退役予定) のため削除済み
    
    # ========== OpenAI ==========
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4-turbo",
    "gpt-3.5-turbo": "gpt-3.5-turbo",
    
    # ========== OpenRouter 経由 ==========
    "or/claude-haiku": "openrouter/anthropic/claude-3-haiku",
    "or/claude-sonnet": "openrouter/anthropic/claude-3.5-sonnet",
    "or/gpt-4o": "openrouter/openai/gpt-4o",
    "or/llama-70b": "openrouter/meta-llama/llama-3.1-70b-instruct",
    
    # ========== Groq (高速推論) ==========
    "groq/llama-70b": "groq/llama-3.1-70b-versatile",
    "groq/llama-8b": "groq/llama-3.1-8b-instant",
    "groq/mixtral": "groq/mixtral-8x7b-32768",
}

# デフォルトモデル
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class LLMAnalyst:
    """LLM を使った市場分析 (LiteLLM 対応)"""
    
    SYSTEM_PROMPT = """あなたは予測市場のアナリストです。
与えられた情報から、イベントが「YES」で解決する確率を予測してください。

## ルール
1. 客観的データに基づいて分析すること
2. バイアスを避け、確率を正確に見積もること
3. 不確実性が高い場合は confidence を下げること
4. 根拠を簡潔に説明すること

## 出力形式 (JSON)
{
    "probability": 0.65,  // YESの確率 (0.0 - 1.0)
    "confidence": 0.7,    // 予測の信頼度 (0.0 - 1.0)
    "reasoning": "理由を簡潔に"
}
"""
    
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        fallback_model: str = None,
    ):
        """
        LLM Analyst 初期化
        
        Args:
            model: モデル名 (MODELS のキーまたは完全名)
            fallback_model: フォールバックモデル
        
        環境変数 (LiteLLM が自動読み込み):
            ANTHROPIC_API_KEY  : Anthropic 直接
            OPENAI_API_KEY     : OpenAI 直接
            OPENROUTER_API_KEY : OpenRouter 経由
            GROQ_API_KEY       : Groq
        """
        if not LITELLM_AVAILABLE:
            raise RuntimeError("litellm not installed")
        
        # モデル名を解決
        self.model = MODELS.get(model, model)
        self.fallback_model = MODELS.get(fallback_model, fallback_model) if fallback_model else None
        
        # デバッグ出力を抑制
        litellm.suppress_debug_info = True
        
        print(f"🤖 LLM: {self.model}")
    
    def _parse_llm_json(self, content: str) -> Optional[dict]:
        """LLMレスポンスからJSONを抽出。コードブロック・正規表現をフォールバックに使用。"""
        if not content or not content.strip():
            return None
        text = content.strip()
        # コードブロック除去
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        # 通常のJSONパース
        try:
            return json.loads(text)
        except Exception:
            pass
        # { } の範囲を抽出して再試行
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        # 正規表現で probability / confidence だけ抽出
        prob = re.search(r'"probability"\s*:\s*([0-9.]+)', text)
        conf = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
        if prob:
            return {
                "probability": float(prob.group(1)),
                "confidence": float(conf.group(1)) if conf else 0.5,
                "reasoning": "",
            }
        return None

    async def analyze_market(
        self,
        question: str,
        current_price: float,
        context: dict = None,
    ) -> Optional[dict]:
        """
        マーケットを分析
        
        Args:
            question: マーケットの質問
            current_price: 現在のYES価格
            context: 追加コンテキスト (BTC価格、ニュース等)
        
        Returns:
            {"probability": float, "confidence": float, "reasoning": str}
        """
        # コンテキスト構築
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
        
        user_prompt = f"""## 予測対象
質問: {question}
現在のマーケット価格 (YES): {current_price:.1%}

## コンテキスト{ctx_text if ctx_text else " なし"}

## タスク
この質問が「YES」で解決する確率を予測してください。
JSON形式で回答してください。
"""
        
        try:
            response = await acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            
            content = response.choices[0].message.content
            
            # JSON抽出
            return self._parse_llm_json(content)
            
        except Exception as e:
            print(f"LLM分析エラー: {e}")
            
            # フォールバック
            if self.fallback_model:
                try:
                    print(f"  → フォールバック: {self.fallback_model}")
                    response = await acompletion(
                        model=self.fallback_model,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        max_tokens=500,
                    )
                    content = response.choices[0].message.content
                    return self._parse_llm_json(content)
                except Exception as e2:
                    print(f"フォールバックも失敗: {e2}")
            
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
        """
        複数マーケットからシグナルを生成
        """
        signals = []
        
        # コンテキスト構築
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
            
            # エッジ計算
            edge = prob - market.yes_price
            
            # アクション決定
            if edge > min_edge:
                action = Action.BUY_YES
                token_id = market.yes_token_id
            elif edge < -min_edge:
                action = Action.BUY_NO
                token_id = market.no_token_id or market.yes_token_id
            else:
                action = Action.HOLD
                token_id = market.yes_token_id
            
            signal = Signal(
                action=action,
                market_id=market.market_id,
                token_id=token_id,
                question=market.question,
                market_price=market.yes_price,
                predicted_prob=prob,
                confidence=conf,
                edge=edge,
                reasoning=reason,
            )
            
            signals.append(signal)
            
            # レート制限対策
            await asyncio.sleep(0.5)
        
        # エッジの絶対値でソート
        signals.sort(key=lambda x: abs(x.edge), reverse=True)
        
        return signals


def list_models():
    """利用可能なモデル一覧"""
    print("\n🤖 利用可能なモデル:\n")
    
    print("━━━ Anthropic (最新) ━━━")
    for key in ["claude-opus-4.6", "claude-sonnet-4.6", "claude-haiku-4-5-20251001"]:
        print(f"  {key:20} → {MODELS[key]}")
    
    print("\n━━━ Anthropic (レガシー) ━━━")
    for key in ["claude-sonnet-4.5", "claude-opus-4.5", "claude-sonnet-4", "claude-opus-4", "claude-3-haiku"]:
        print(f"  {key:20} → {MODELS[key]}")
    
    print("\n━━━ OpenAI ━━━")
    for key in ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]:
        print(f"  {key:20} → {MODELS[key]}")
    
    print("\n━━━ OpenRouter 経由 ━━━")
    for key in ["or/claude-haiku", "or/claude-sonnet", "or/gpt-4o", "or/llama-70b"]:
        print(f"  {key:20} → {MODELS[key]}")
    
    print("\n━━━ Groq (高速) ━━━")
    for key in ["groq/llama-70b", "groq/llama-8b", "groq/mixtral"]:
        print(f"  {key:20} → {MODELS[key]}")
    
    print("\n━━━ 環境変数 (LiteLLM 自動読み込み) ━━━")
    print("  ANTHROPIC_API_KEY   : Anthropic 直接")
    print("  OPENAI_API_KEY      : OpenAI 直接")
    print("  OPENROUTER_API_KEY  : OpenRouter 経由")
    print("  GROQ_API_KEY        : Groq")
    
    print(f"\n📌 デフォルト: {DEFAULT_MODEL}")


# テスト用
async def _test():
    from scanner import MarketScanner
    
    # スキャン
    scanner = MarketScanner()
    result = await scanner.scan()
    
    # 分析
    analyst = LLMAnalyst(model=DEFAULT_MODEL)
    
    signals = await analyst.generate_signals(
        markets=result.markets[:2],
        btc_price=result.btc_price.price if result.btc_price else None,
        btc_change=result.btc_price.change_24h if result.btc_price else None,
    )
    
    print(f"\n🎯 シグナル ({len(signals)}件):")
    for s in signals:
        print(json.dumps(s.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "models":
        list_models()
    else:
        asyncio.run(_test())
