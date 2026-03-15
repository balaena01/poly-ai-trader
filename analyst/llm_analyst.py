"""
LLM Analyst
- マーケット情報 + 外部価格を分析
- LLM (Claude/OpenAI) で確率予測
- 売買シグナル生成
"""
import os
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from enum import Enum

import httpx
from dotenv import load_dotenv

load_dotenv()


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


class LLMAnalyst:
    """LLM を使った市場分析"""
    
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
        provider: str = "openrouter",  # "openrouter" or "openai"
        model: str = "anthropic/claude-3-haiku",
    ):
        """
        LLM Analyst 初期化
        
        Args:
            provider: LLM プロバイダー
            model: モデル名
        """
        self.provider = provider
        self.model = model
        
        if provider == "openrouter":
            self.api_key = os.getenv("OPENROUTER_API_KEY")
            self.base_url = "https://openrouter.ai/api/v1"
        else:
            self.api_key = os.getenv("OPENAI_API_KEY")
            self.base_url = "https://api.openai.com/v1"
        
        if not self.api_key:
            print(f"⚠️ {provider.upper()}_API_KEY が設定されていません")
    
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
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                
                content = data["choices"][0]["message"]["content"]
                
                # JSON抽出
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                return json.loads(content.strip())
                
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
        """
        複数マーケットからシグナルを生成
        
        Args:
            markets: MarketData リスト
            btc_price: BTC価格
            btc_change: BTC 24h変化率
            eth_price: ETH価格
            eth_change: ETH 24h変化率
            min_edge: 最小エッジ
            max_markets: 最大分析数
        
        Returns:
            Signal リスト
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
            import asyncio
            await asyncio.sleep(0.5)
        
        # エッジの絶対値でソート
        signals.sort(key=lambda x: abs(x.edge), reverse=True)
        
        return signals


# テスト用
async def _test():
    from scanner import MarketScanner
    
    # スキャン
    scanner = MarketScanner()
    result = await scanner.scan()
    
    # 分析
    analyst = LLMAnalyst()
    
    signals = await analyst.generate_signals(
        markets=result.markets[:3],
        btc_price=result.btc_price.price if result.btc_price else None,
        btc_change=result.btc_price.change_24h if result.btc_price else None,
        eth_price=result.eth_price.price if result.eth_price else None,
        eth_change=result.eth_price.change_24h if result.eth_price else None,
    )
    
    print(f"\n🎯 シグナル ({len(signals)}件):")
    for s in signals:
        print(json.dumps(s.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import asyncio
    asyncio.run(_test())
