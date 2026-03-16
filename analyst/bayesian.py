"""
Bayesian Aggregator
- 複数シグナルの確率的統合
- 単純多数決ではなく、Bayes則による統合
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
import math


@dataclass
class SignalSource:
    """シグナルソース"""
    name: str
    probability: float      # 予測確率 (0-1)
    confidence: float       # 信頼度 (0-1)
    accuracy: float = 0.6   # 過去精度 (デフォルト60%)
    
    @property
    def weight(self) -> float:
        """重み (信頼度 × 精度)"""
        return self.confidence * self.accuracy


@dataclass
class BayesianResult:
    """Bayesian統合結果"""
    timestamp: datetime
    
    # 入力
    market_price: float             # マーケット価格 (事前確率)
    signals: List[SignalSource]     # シグナルリスト
    
    # 出力
    posterior: float                # 事後確率
    final_probability: float        # 最終確率 (調整済み)
    edge: float                     # エッジ (final - market)
    confidence: float               # 統合信頼度
    
    def to_dict(self) -> Dict:
        return {
            "market_price": f"{self.market_price:.1%}",
            "signals": [
                {"name": s.name, "prob": f"{s.probability:.1%}", "conf": f"{s.confidence:.0%}"}
                for s in self.signals
            ],
            "posterior": f"{self.posterior:.1%}",
            "final": f"{self.final_probability:.1%}",
            "edge": f"{self.edge:+.1%}",
            "confidence": f"{self.confidence:.0%}",
        }


class BayesianAggregator:
    """Bayesian シグナル統合"""
    
    def __init__(
        self,
        market_weight: float = 0.3,     # マーケット価格の重み
        signal_weight: float = 0.7,     # シグナルの重み
        min_confidence: float = 0.1,    # 最小信頼度 (ML confidence = abs(prob-0.5)*2 なので0.5は高すぎる)
    ):
        """
        初期化
        
        Args:
            market_weight: マーケット価格の重み (事前確率)
            signal_weight: シグナルの重み
            min_confidence: 最小信頼度閾値
        """
        self.market_weight = market_weight
        self.signal_weight = signal_weight
        self.min_confidence = min_confidence
    
    def aggregate(
        self,
        market_price: float,
        signals: List[SignalSource],
        market_liquidity: float = 0,
    ) -> BayesianResult:
        """
        Bayesian統合
        
        例:
            Market: 53% UP
            LLM: 64%
            LightGBM: 69%
            Orderflow: 72%
            
            → Posterior: 81%
            → Final: 76.9%
            → Edge: 23.9%
        
        Args:
            market_price: マーケットのYES価格 (事前確率)
            signals: シグナルリスト
        
        Returns:
            BayesianResult
        """
        if not signals:
            return BayesianResult(
                timestamp=datetime.now(),
                market_price=market_price,
                signals=[],
                posterior=market_price,
                final_probability=market_price,
                edge=0,
                confidence=0,
            )
        
        # 流動性に応じて market_weight を動的調整
        # 高流動性 ($500k+) → 市場価格を50%信頼、低流動性 ($10k) → 20%
        if market_liquidity > 0:
            liq_factor = min(1.0, market_liquidity / 500000)
            effective_market_weight = 0.2 + 0.3 * liq_factor   # [0.2, 0.5]
        else:
            effective_market_weight = self.market_weight
        effective_signal_weight = 1.0 - effective_market_weight

        # 信頼度フィルター
        valid_signals = [s for s in signals if s.confidence >= self.min_confidence]
        
        if not valid_signals:
            return BayesianResult(
                timestamp=datetime.now(),
                market_price=market_price,
                signals=signals,
                posterior=market_price,
                final_probability=market_price,
                edge=0,
                confidence=0,
            )
        
        # ========== Bayesian Update ==========
        # P(H|E) = P(E|H) * P(H) / P(E)
        # 
        # ここでは簡略化:
        # - P(H) = market_price (事前確率)
        # - 各シグナルをエビデンスとして順次更新
        
        prior = market_price
        
        for signal in valid_signals:
            # シグナルの精度に基づく尤度
            # P(signal_says_yes | actually_yes) = signal.accuracy
            # P(signal_says_yes | actually_no) = 1 - signal.accuracy
            
            if signal.probability > 0.5:
                # シグナルが YES と言っている
                likelihood_yes = signal.accuracy * signal.probability
                likelihood_no = (1 - signal.accuracy) * (1 - signal.probability)
            else:
                # シグナルが NO と言っている
                likelihood_yes = (1 - signal.accuracy) * signal.probability
                likelihood_no = signal.accuracy * (1 - signal.probability)
            
            # Bayes更新
            # posterior = (likelihood_yes * prior) / 
            #             (likelihood_yes * prior + likelihood_no * (1 - prior))
            
            numerator = likelihood_yes * prior
            denominator = likelihood_yes * prior + likelihood_no * (1 - prior)
            
            if denominator > 0:
                prior = numerator / denominator
            
            # 重みで調整
            prior = self._apply_weight(prior, signal.weight)
        
        posterior = prior
        
        # ========== 最終調整 ==========
        # マーケット価格とシグナルの加重平均
        signal_avg = sum(s.probability * s.weight for s in valid_signals) / sum(s.weight for s in valid_signals)

        final = (
            effective_market_weight * market_price +
            effective_signal_weight * (0.5 * posterior + 0.5 * signal_avg)
        )
        
        # 0-1 にクリップ
        final = max(0.01, min(0.99, final))
        
        # ========== 信頼度計算 ==========
        # シグナルの一致度が高いほど信頼度が高い
        signal_probs = [s.probability for s in valid_signals]
        signal_std = self._std(signal_probs) if len(signal_probs) > 1 else 0
        
        # 標準偏差が小さい = 一致度が高い = 信頼度が高い
        agreement_score = max(0, 1 - signal_std * 4)  # std 0.25 で信頼度 0
        
        # 平均信頼度
        avg_confidence = sum(s.confidence for s in valid_signals) / len(valid_signals)
        
        confidence = (agreement_score * 0.5 + avg_confidence * 0.5)
        
        return BayesianResult(
            timestamp=datetime.now(),
            market_price=market_price,
            signals=signals,
            posterior=posterior,
            final_probability=final,
            edge=final - market_price,
            confidence=confidence,
        )
    
    def _apply_weight(self, prob: float, weight: float) -> float:
        """重みに応じて確率を調整"""
        # weight が低い場合、0.5 に近づける
        return 0.5 + (prob - 0.5) * weight
    
    def _std(self, values: List[float]) -> float:
        """標準偏差"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)


# テスト
if __name__ == "__main__":
    print("📊 Bayesian Aggregator テスト\n")
    
    aggregator = BayesianAggregator()
    
    # シグナル例 (ツイートの例)
    signals = [
        SignalSource(name="LLM", probability=0.64, confidence=0.8, accuracy=0.65),
        SignalSource(name="LightGBM", probability=0.69, confidence=0.7, accuracy=0.60),
        SignalSource(name="Orderflow", probability=0.72, confidence=0.6, accuracy=0.55),
    ]
    
    market_price = 0.53
    
    result = aggregator.aggregate(market_price, signals)
    
    print(f"📈 入力:")
    print(f"  マーケット価格: {market_price:.0%}")
    for s in signals:
        print(f"  {s.name:12}: {s.probability:.0%} (信頼度: {s.confidence:.0%})")
    
    print(f"\n🎯 出力:")
    print(f"  事後確率:   {result.posterior:.1%}")
    print(f"  最終確率:   {result.final_probability:.1%}")
    print(f"  エッジ:     {result.edge:+.1%}")
    print(f"  信頼度:     {result.confidence:.0%}")
    
    # 期待値の例
    print(f"\n💰 シミュレーション:")
    print(f"  マーケット: 53% UP")
    print(f"  予測:       {result.final_probability:.1%} UP")
    print(f"  エッジ:     {result.edge:.1%}")
    print(f"  → {result.edge * 100:.1f}% のエッジで BUY YES")
