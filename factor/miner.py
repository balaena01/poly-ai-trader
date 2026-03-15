"""
Factor Miner
- LLM (Claude Haiku) で取引仮説を生成
- バックテストで検証
- IC > 0.05 のファクターのみ保持
"""
import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum

try:
    import litellm
    from litellm import acompletion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False


class FactorType(Enum):
    """ファクタータイプ"""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    SENTIMENT = "sentiment"
    ORDERFLOW = "orderflow"
    SEASONAL = "seasonal"
    EVENT = "event"
    COMPOSITE = "composite"


@dataclass
class FactorHypothesis:
    """ファクター仮説"""
    id: str
    name: str
    description: str
    type: FactorType
    
    # ルール
    entry_condition: str    # エントリー条件 (自然言語)
    exit_condition: str     # エグジット条件
    
    # パラメータ
    parameters: Dict[str, float] = field(default_factory=dict)
    
    # メタデータ
    created_at: datetime = field(default_factory=datetime.now)
    llm_model: str = ""
    raw_response: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "entry_condition": self.entry_condition,
            "exit_condition": self.exit_condition,
            "parameters": self.parameters,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Factor:
    """検証済みファクター"""
    hypothesis: FactorHypothesis
    
    # パフォーマンス指標
    ic: float = 0                   # Information Coefficient
    sharpe: float = 0               # Sharpe Ratio
    win_rate: float = 0             # 勝率
    total_trades: int = 0           # 総トレード数
    total_pnl: float = 0            # 総損益
    
    # 状態
    is_active: bool = True
    deactivated_at: Optional[datetime] = None
    deactivate_reason: str = ""
    
    # 履歴
    trade_history: List[Dict] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """有効なファクターか (IC > 0.05)"""
        return self.ic > 0.05 and self.total_trades >= 10
    
    def to_dict(self) -> Dict:
        return {
            "id": self.hypothesis.id,
            "name": self.hypothesis.name,
            "type": self.hypothesis.type.value,
            "ic": self.ic,
            "sharpe": self.sharpe,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "total_pnl": self.total_pnl,
            "is_active": self.is_active,
            "is_valid": self.is_valid,
        }


class FactorMiner:
    """ファクター生成器"""
    
    SYSTEM_PROMPT = """あなたは予測市場の定量アナリストです。
取引戦略のアイデア（ファクター）を生成してください。

## ファクターの種類
- momentum: 価格モメンタム
- mean_reversion: 平均回帰
- sentiment: センチメント
- orderflow: オーダーフロー
- seasonal: 季節性
- event: イベント駆動
- composite: 複合

## 出力形式 (JSON)
{
    "name": "ファクター名",
    "description": "説明",
    "type": "momentum|mean_reversion|sentiment|orderflow|seasonal|event|composite",
    "entry_condition": "エントリー条件（具体的に）",
    "exit_condition": "エグジット条件",
    "parameters": {
        "param1": 0.5,
        "param2": 10
    }
}

## ルール
1. 具体的で実装可能な条件を記述
2. パラメータは数値で指定
3. 過去データで検証可能なルールにする
4. シンプルで解釈可能な戦略を優先
"""
    
    def __init__(
        self,
        model: str = "claude-3-haiku-20240307",
        max_factors: int = 10,
    ):
        """
        初期化
        
        Args:
            model: 仮説生成に使うLLMモデル
            max_factors: 最大アクティブファクター数
        """
        if not LITELLM_AVAILABLE:
            raise RuntimeError("litellm not installed")
        
        self.model = model
        self.max_factors = max_factors
        
        litellm.suppress_debug_info = True
    
    async def generate_hypothesis(
        self,
        context: str = None,
        factor_type: FactorType = None,
        existing_factors: List[str] = None,
    ) -> Optional[FactorHypothesis]:
        """
        新しいファクター仮説を生成
        
        Args:
            context: 追加コンテキスト（市場状況等）
            factor_type: 生成するファクタータイプ
            existing_factors: 既存ファクターの名前（重複回避）
        
        Returns:
            FactorHypothesis or None
        """
        # プロンプト構築
        user_prompt = "新しい取引ファクターを1つ提案してください。\n"
        
        if factor_type:
            user_prompt += f"\nタイプ: {factor_type.value}\n"
        
        if context:
            user_prompt += f"\n市場コンテキスト:\n{context}\n"
        
        if existing_factors:
            user_prompt += f"\n既存ファクター（重複回避）:\n- " + "\n- ".join(existing_factors)
        
        user_prompt += "\n\nJSON形式で回答してください。"
        
        try:
            response = await acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,  # 創造性を高める
                max_tokens=1000,
            )
            
            content = response.choices[0].message.content
            
            # JSON抽出
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            # FactorHypothesis を作成
            return FactorHypothesis(
                id=str(uuid.uuid4())[:8],
                name=data.get("name", "Unnamed Factor"),
                description=data.get("description", ""),
                type=FactorType(data.get("type", "momentum")),
                entry_condition=data.get("entry_condition", ""),
                exit_condition=data.get("exit_condition", ""),
                parameters=data.get("parameters", {}),
                llm_model=self.model,
                raw_response=content,
            )
            
        except Exception as e:
            print(f"仮説生成エラー: {e}")
            return None
    
    async def generate_multiple(
        self,
        count: int = 5,
        context: str = None,
        existing_factors: List[str] = None,
    ) -> List[FactorHypothesis]:
        """
        複数のファクター仮説を生成
        """
        hypotheses = []
        existing = list(existing_factors or [])
        
        # 各タイプから1つずつ生成を試みる
        types = list(FactorType)
        
        for i in range(count):
            factor_type = types[i % len(types)]
            
            hypothesis = await self.generate_hypothesis(
                context=context,
                factor_type=factor_type,
                existing_factors=existing,
            )
            
            if hypothesis:
                hypotheses.append(hypothesis)
                existing.append(hypothesis.name)
            
            # レート制限
            await asyncio.sleep(0.5)
        
        return hypotheses


# テスト
async def _test():
    print("⛏️ Factor Miner テスト\n")
    
    miner = FactorMiner()
    
    print("📝 ファクター仮説を生成中...")
    hypothesis = await miner.generate_hypothesis(
        context="BTC価格が急騰中、ボラティリティ高い",
        factor_type=FactorType.MOMENTUM,
    )
    
    if hypothesis:
        print(f"\n✅ 生成成功:")
        print(json.dumps(hypothesis.to_dict(), indent=2, ensure_ascii=False))
    else:
        print("❌ 生成失敗")


if __name__ == "__main__":
    asyncio.run(_test())
