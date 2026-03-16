"""
Ensemble Analyst
- LLM + LightGBM + Orderflow を統合
- Bayesian Aggregation で最終判断
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

from .llm_analyst import LLMAnalyst, Signal, Action
from .ml_analyst import MLAnalyst, MLPrediction
from .orderflow import OrderflowDetector, OrderflowSignal, Trade
from .bayesian import BayesianAggregator, BayesianResult, SignalSource
from .features import FeatureExtractor


@dataclass
class EnsembleSignal:
    """アンサンブルシグナル"""
    market_id: str
    token_id: str
    question: str

    # 各シグナル
    llm_prob: float
    llm_conf: float
    ml_prob: float
    ml_conf: float
    orderflow_signal: float
    orderflow_conf: float

    # Bayesian統合結果
    bayesian_result: BayesianResult

    # 最終判断
    action: Action
    final_probability: float
    edge: float
    confidence: float

    # LLM推論テキスト (Auditorのハルシネーション検出に使用)
    llm_reasoning: str = ""
    
    @property
    def is_tradeable(self) -> bool:
        """取引可能か"""
        return abs(self.edge) > 0.10 and self.confidence > 0.6
    
    def to_dict(self) -> Dict:
        return {
            "question": self.question[:50],
            "llm": f"{self.llm_prob:.1%} ({self.llm_conf:.0%})",
            "ml": f"{self.ml_prob:.1%} ({self.ml_conf:.0%})",
            "orderflow": f"{self.orderflow_signal:+.2f} ({self.orderflow_conf:.0%})",
            "final": f"{self.final_probability:.1%}",
            "edge": f"{self.edge:+.1%}",
            "confidence": f"{self.confidence:.0%}",
            "action": self.action.value,
            "tradeable": self.is_tradeable,
        }


class EnsembleAnalyst:
    """アンサンブル分析"""
    
    def __init__(
        self,
        llm_model: str = "claude-haiku-4-5-20251001",
        ml_model_path: str = None,
        use_ml: bool = True,
        use_orderflow: bool = True,
    ):
        """
        初期化
        
        Args:
            llm_model: LLMモデル
            ml_model_path: 学習済みMLモデルのパス
            use_ml: MLを使用するか
            use_orderflow: Orderflowを使用するか
        """
        # LLM Analyst
        self.llm_analyst = LLMAnalyst(model=llm_model)
        
        # ML Analyst
        self.use_ml = use_ml
        self.ml_analyst = None
        if use_ml:
            try:
                self.ml_analyst = MLAnalyst(model_path=ml_model_path)
            except Exception as e:
                print(f"⚠️ ML Analyst 初期化失敗: {e}")
                self.use_ml = False
        
        # Orderflow Detector
        self.use_orderflow = use_orderflow
        self.orderflow_detector = OrderflowDetector() if use_orderflow else None
        
        # Feature Extractor
        self.feature_extractor = FeatureExtractor()
        
        # Bayesian Aggregator
        self.aggregator = BayesianAggregator()
        
        print(f"🤖 Ensemble Analyst 初期化")
        print(f"   LLM: {llm_model}")
        print(f"   ML: {'✓' if self.use_ml else '✗'}")
        print(f"   Orderflow: {'✓' if self.use_orderflow else '✗'}")

    def reload_ml_model(self, path: str):
        """実行中のMLモデルをホットスワップ (再学習後に呼び出す)"""
        try:
            new_analyst = MLAnalyst(model_path=path)
            self.ml_analyst = new_analyst
            self.use_ml = True
            print(f"🔁 MLモデルをホットスワップ: {path}")
        except Exception as e:
            print(f"⚠️ MLモデルリロード失敗: {e}")
    
    async def analyze(
        self,
        market,  # MarketData
        prices: List[float] = None,
        volumes: List[float] = None,
        trades: List[Trade] = None,
        bids: List[Dict] = None,
        asks: List[Dict] = None,
        btc_price: float = None,
        btc_change: float = None,
        eth_price: float = None,
        eth_change: float = None,
        news_context: str = None,
    ) -> EnsembleSignal:
        """
        マーケットを分析
        
        Args:
            market: MarketData
            prices: 価格履歴
            volumes: ボリューム履歴
            trades: 取引履歴
            bids: 買い注文板
            asks: 売り注文板
            btc_price: BTC価格
            btc_change: BTC 24h変化率
            eth_price: ETH価格
            eth_change: ETH 24h変化率
        
        Returns:
            EnsembleSignal
        """
        signals = []
        
        # ========== LLM 分析 ==========
        context = {}
        if btc_price:
            context["btc_price"] = btc_price
        if btc_change:
            context["btc_change"] = btc_change
        if eth_price:
            context["eth_price"] = eth_price
        if eth_change:
            context["eth_change"] = eth_change
        if news_context:
            context["news"] = news_context
        
        llm_result = await self.llm_analyst.analyze_market(
            question=market.question,
            current_price=market.yes_price,
            context=context if context else None,
        )
        
        llm_prob = llm_result.get("probability", 0.5) if llm_result else 0.5
        llm_conf = llm_result.get("confidence", 0.5) if llm_result else 0.5
        llm_reasoning = llm_result.get("reasoning", "") if llm_result else ""
        
        signals.append(SignalSource(
            name="LLM",
            probability=llm_prob,
            confidence=llm_conf,
            accuracy=0.65,  # LLMの過去精度
        ))
        
        # ========== ML 分析 ==========
        ml_prob = 0.5
        ml_conf = 0.0
        
        if self.use_ml and self.ml_analyst and prices:
            features = self.feature_extractor.extract(
                prices=prices,
                volumes=volumes,
                bids=bids,
                asks=asks,
                trades=trades,
                yes_price=market.yes_price,
                market_volume=market.volume,
                market_liquidity=market.liquidity,
                end_date=market.end_date,
                # llm_pred / llm_conf は渡さない: LLM は Bayesian で独立シグナルとして扱う
            )
            
            ml_result = self.ml_analyst.predict(features)
            ml_prob = ml_result.probability
            ml_conf = ml_result.confidence
            
            signals.append(SignalSource(
                name="LightGBM",
                probability=ml_prob,
                confidence=ml_conf,
                accuracy=0.72,  # Valid AUC に合わせて設定
            ))
        
        # ========== Orderflow 分析 ==========
        orderflow_signal = 0.0
        orderflow_conf = 0.0
        
        if self.use_orderflow and self.orderflow_detector:
            if trades:
                self.orderflow_detector.add_trades(trades)
            
            of_result = self.orderflow_detector.analyze(trades)
            orderflow_signal = of_result.composite_signal
            orderflow_conf = of_result.confidence
            
            # Orderflow を確率に変換 (-1 to 1 → 0 to 1)
            of_prob = 0.5 + orderflow_signal * 0.5
            
            signals.append(SignalSource(
                name="Orderflow",
                probability=of_prob,
                confidence=orderflow_conf,
                accuracy=0.55,
            ))
        
        # ========== Bayesian 統合 ==========
        bayesian_result = self.aggregator.aggregate(
            market_price=market.yes_price,
            signals=signals,
            market_liquidity=getattr(market, "liquidity", 0),
        )
        
        # ========== 最終判断 ==========
        final_prob = bayesian_result.final_probability
        edge = bayesian_result.edge
        confidence = bayesian_result.confidence
        
        if edge > 0:
            action = Action.BUY_YES
            token_id = market.yes_token_id
        elif edge < 0:
            action = Action.BUY_NO
            token_id = market.no_token_id or market.yes_token_id
        else:
            action = Action.HOLD
            token_id = market.yes_token_id
        
        return EnsembleSignal(
            market_id=market.market_id,
            token_id=token_id,
            question=market.question,
            llm_prob=llm_prob,
            llm_conf=llm_conf,
            ml_prob=ml_prob,
            ml_conf=ml_conf,
            orderflow_signal=orderflow_signal,
            orderflow_conf=orderflow_conf,
            bayesian_result=bayesian_result,
            action=action,
            final_probability=final_prob,
            edge=edge,
            confidence=confidence,
            llm_reasoning=llm_reasoning,
        )
    
    async def analyze_markets(
        self,
        markets: list,
        btc_price: float = None,
        btc_change: float = None,
        eth_price: float = None,
        eth_change: float = None,
        max_markets: int = 5,
    ) -> List[EnsembleSignal]:
        """
        複数マーケットを分析
        """
        signals = []
        
        for market in markets[:max_markets]:
            print(f"  📊 分析中: {market.question[:40]}...")
            
            signal = await self.analyze(
                market=market,
                btc_price=btc_price,
                btc_change=btc_change,
                eth_price=eth_price,
                eth_change=eth_change,
            )
            
            signals.append(signal)
            
            # レート制限
            await asyncio.sleep(0.5)
        
        # エッジでソート
        signals.sort(key=lambda x: abs(x.edge), reverse=True)
        
        return signals


# テスト
async def _test():
    from scanner import MarketScanner
    
    print("🎯 Ensemble Analyst テスト\n")
    
    # スキャン
    scanner = MarketScanner()
    scan_result = await scanner.scan()
    
    # アンサンブル分析 (MLなし、簡易版)
    analyst = EnsembleAnalyst(
        llm_model="claude-haiku-4-5-20251001",
        use_ml=False,  # 学習済みモデルなし
        use_orderflow=False,  # 取引データなし
    )
    
    signals = await analyst.analyze_markets(
        markets=scan_result.markets[:2],
        btc_price=scan_result.btc_price.price if scan_result.btc_price else None,
        btc_change=scan_result.btc_price.change_24h if scan_result.btc_price else None,
    )
    
    print(f"\n🎯 アンサンブルシグナル ({len(signals)}件):")
    for s in signals:
        print(f"\n  {s.question[:50]}")
        print(f"    LLM: {s.llm_prob:.0%} | ML: {s.ml_prob:.0%} | OF: {s.orderflow_signal:+.2f}")
        print(f"    Final: {s.final_probability:.0%} | Edge: {s.edge:+.1%} | Conf: {s.confidence:.0%}")
        print(f"    Action: {s.action.value} | Tradeable: {s.is_tradeable}")


if __name__ == "__main__":
    asyncio.run(_test())
