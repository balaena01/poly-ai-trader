"""
Auditor
- ハルシネーション/検証不能ニュースをフラグ
- 解決まで10分未満のマーケットをブロック
- 低流動性マーケットをブロック
- フラグごとに信頼度ペナルティ
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum
import re


class AuditFlag(Enum):
    """監査フラグ"""
    HALLUCINATION = "hallucination"           # ハルシネーション疑い
    UNVERIFIABLE = "unverifiable"             # 検証不能
    LOW_LIQUIDITY = "low_liquidity"           # 低流動性
    NEAR_RESOLUTION = "near_resolution"       # 解決間近
    HIGH_SPREAD = "high_spread"               # 高スプレッド
    SUSPICIOUS_VOLUME = "suspicious_volume"   # 不審なボリューム
    NEWS_CONFLICT = "news_conflict"           # ニュース矛盾


@dataclass
class AuditResult:
    """監査結果"""
    timestamp: datetime
    market_id: str
    
    # 結果
    passed: bool                        # 監査通過
    flags: List[AuditFlag] = field(default_factory=list)
    
    # 調整
    confidence_penalty: float = 0       # 信頼度ペナルティ (0-1)
    adjusted_confidence: float = 1.0    # 調整後信頼度
    
    # 詳細
    details: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "flags": [f.value for f in self.flags],
            "penalty": f"{self.confidence_penalty:.0%}",
            "adjusted_confidence": f"{self.adjusted_confidence:.0%}",
            "details": self.details,
        }


class Auditor:
    """監査エンジン"""
    
    # ペナルティ設定 (フラグごとの信頼度減少)
    PENALTIES = {
        AuditFlag.HALLUCINATION: 0.20,
        AuditFlag.UNVERIFIABLE: 0.10,
        AuditFlag.LOW_LIQUIDITY: 0.08,
        AuditFlag.NEAR_RESOLUTION: 0.15,
        AuditFlag.HIGH_SPREAD: 0.05,
        AuditFlag.SUSPICIOUS_VOLUME: 0.08,
        AuditFlag.NEWS_CONFLICT: 0.12,
    }
    
    # ブロックフラグ (これらがあると取引ブロック)
    BLOCKING_FLAGS = {
        AuditFlag.NEAR_RESOLUTION,
        AuditFlag.LOW_LIQUIDITY,
    }
    
    def __init__(
        self,
        min_liquidity: float = 10000,       # 最小流動性 ($)
        min_time_to_resolution: int = 10,   # 最小残り時間 (分)
        max_spread_pct: float = 0.10,       # 最大スプレッド (10%)
        penalty_per_flag: float = 0.08,     # フラグごとのデフォルトペナルティ
    ):
        """
        初期化
        
        Args:
            min_liquidity: 最小流動性
            min_time_to_resolution: 解決までの最小時間 (分)
            max_spread_pct: 最大スプレッド比率
            penalty_per_flag: フラグあたりのデフォルトペナルティ
        """
        self.min_liquidity = min_liquidity
        self.min_time_to_resolution = min_time_to_resolution
        self.max_spread_pct = max_spread_pct
        self.penalty_per_flag = penalty_per_flag
    
    def audit(
        self,
        market_id: str,
        question: str,
        liquidity: float,
        end_date: datetime = None,
        spread: float = None,
        volume_24h: float = None,
        avg_volume: float = None,
        llm_reasoning: str = None,
        news_sources: List[str] = None,
        original_confidence: float = 1.0,
    ) -> AuditResult:
        """
        マーケットを監査
        
        Args:
            market_id: マーケットID
            question: 質問
            liquidity: 流動性
            end_date: 終了日時
            spread: スプレッド
            volume_24h: 24時間ボリューム
            avg_volume: 平均ボリューム
            llm_reasoning: LLMの推論
            news_sources: ニュースソース
            original_confidence: 元の信頼度
        
        Returns:
            AuditResult
        """
        flags = []
        details = {}
        
        # ========== 流動性チェック ==========
        if liquidity < self.min_liquidity:
            flags.append(AuditFlag.LOW_LIQUIDITY)
            details["liquidity"] = f"${liquidity:,.0f} < ${self.min_liquidity:,.0f}"
        
        # ========== 解決時間チェック ==========
        if end_date:
            time_to_resolution = (end_date - datetime.now()).total_seconds() / 60
            if time_to_resolution < self.min_time_to_resolution:
                flags.append(AuditFlag.NEAR_RESOLUTION)
                details["time_to_resolution"] = f"{time_to_resolution:.0f}分 < {self.min_time_to_resolution}分"
        
        # ========== スプレッドチェック ==========
        if spread is not None and spread > self.max_spread_pct:
            flags.append(AuditFlag.HIGH_SPREAD)
            details["spread"] = f"{spread:.1%} > {self.max_spread_pct:.1%}"
        
        # ========== ボリューム異常チェック ==========
        if volume_24h is not None and avg_volume is not None:
            if avg_volume > 0:
                volume_ratio = volume_24h / avg_volume
                if volume_ratio > 5:  # 平均の5倍以上
                    flags.append(AuditFlag.SUSPICIOUS_VOLUME)
                    details["volume"] = f"異常に高い ({volume_ratio:.1f}x)"
                elif volume_ratio < 0.1:  # 平均の10%未満
                    flags.append(AuditFlag.SUSPICIOUS_VOLUME)
                    details["volume"] = f"異常に低い ({volume_ratio:.1%})"
        
        # ========== LLM推論チェック ==========
        if llm_reasoning:
            # ハルシネーション疑いのパターン
            hallucination_patterns = [
                r"確定的に.*だろう",
                r"絶対に",
                r"100%",
                r"間違いなく",
                r"私の予測では",
                r"情報によると(?!.*ソース)",
            ]
            
            for pattern in hallucination_patterns:
                if re.search(pattern, llm_reasoning):
                    flags.append(AuditFlag.HALLUCINATION)
                    details["hallucination"] = f"疑わしい表現: {pattern}"
                    break
            
            # 検証不能チェック
            if not news_sources or len(news_sources) == 0:
                if any(word in llm_reasoning for word in ["ニュース", "報道", "発表"]):
                    flags.append(AuditFlag.UNVERIFIABLE)
                    details["unverifiable"] = "ニュース参照あるがソースなし"
        
        # ========== ペナルティ計算 ==========
        total_penalty = 0
        for flag in flags:
            penalty = self.PENALTIES.get(flag, self.penalty_per_flag)
            total_penalty += penalty
        
        # 最大ペナルティは80%
        total_penalty = min(0.80, total_penalty)
        
        adjusted_confidence = original_confidence * (1 - total_penalty)
        
        # ========== ブロック判定 ==========
        blocking = any(f in self.BLOCKING_FLAGS for f in flags)
        passed = not blocking
        
        return AuditResult(
            timestamp=datetime.now(),
            market_id=market_id,
            passed=passed,
            flags=flags,
            confidence_penalty=total_penalty,
            adjusted_confidence=adjusted_confidence,
            details=details,
        )
    
    def quick_check(
        self,
        liquidity: float,
        end_date: datetime = None,
    ) -> bool:
        """
        クイックチェック (ブロック条件のみ)
        
        Returns:
            True = OK, False = ブロック
        """
        # 流動性
        if liquidity < self.min_liquidity:
            return False
        
        # 解決時間
        if end_date:
            time_to_resolution = (end_date - datetime.now()).total_seconds() / 60
            if time_to_resolution < self.min_time_to_resolution:
                return False
        
        return True


# テスト
if __name__ == "__main__":
    print("🔍 Auditor テスト\n")
    
    auditor = Auditor()
    
    # テスト1: 正常なマーケット
    print("✅ テスト1: 正常なマーケット")
    result = auditor.audit(
        market_id="test1",
        question="Will BTC reach $100k?",
        liquidity=50000,
        end_date=datetime.now() + timedelta(days=7),
        spread=0.02,
    )
    print(f"  通過: {result.passed}")
    print(f"  フラグ: {[f.value for f in result.flags]}")
    
    # テスト2: 低流動性
    print("\n❌ テスト2: 低流動性")
    result = auditor.audit(
        market_id="test2",
        question="Some obscure market",
        liquidity=5000,
        end_date=datetime.now() + timedelta(days=7),
    )
    print(f"  通過: {result.passed}")
    print(f"  フラグ: {[f.value for f in result.flags]}")
    print(f"  詳細: {result.details}")
    
    # テスト3: 解決間近
    print("\n❌ テスト3: 解決間近")
    result = auditor.audit(
        market_id="test3",
        question="Will X happen in 5 minutes?",
        liquidity=50000,
        end_date=datetime.now() + timedelta(minutes=5),
    )
    print(f"  通過: {result.passed}")
    print(f"  フラグ: {[f.value for f in result.flags]}")
    
    # テスト4: ハルシネーション疑い
    print("\n⚠️ テスト4: ハルシネーション疑い")
    result = auditor.audit(
        market_id="test4",
        question="Test",
        liquidity=50000,
        llm_reasoning="私の予測では、これは絶対に起こるだろう。100%確実だ。",
        original_confidence=0.8,
    )
    print(f"  通過: {result.passed}")
    print(f"  フラグ: {[f.value for f in result.flags]}")
    print(f"  ペナルティ: {result.confidence_penalty:.0%}")
    print(f"  調整後信頼度: {result.adjusted_confidence:.0%}")
