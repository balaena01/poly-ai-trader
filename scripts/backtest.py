#!/usr/bin/env python3
"""
Backtest - エンドツーエンドバックテスト

過去の解決済みマーケットで戦略全体（シグナル生成〜サイジング〜PnL）を検証する。
LLM はデフォルト無効（コスト節約）。ML モデルは lgb_model.pkl があれば自動使用。

使い方:
  python scripts/backtest.py                           # デフォルト (過去90日, 100件)
  python scripts/backtest.py --days 30 --limit 50     # 期間・件数を絞る
  python scripts/backtest.py --use-llm                # LLM分析あり (API費用発生)
  python scripts/backtest.py --min-edge 0.15          # エッジ閾値を上げる
  python scripts/backtest.py --analysis-point 0.5    # 期間50%時点で分析
"""
import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from client import PolyClient
from analyst.features import FeatureExtractor
from analyst.ml_analyst import MLAnalyst
from analyst.bayesian import BayesianAggregator, SignalSource
from data_fetcher import PriceHistoryFetcher


# ===== データクラス =====

@dataclass
class BacktestConfig:
    days: int = 90                      # 過去何日分のマーケットを対象にするか
    limit: int = 100                    # 最大マーケット数
    min_volume: float = 10_000          # 最小 24h 出来高 ($)
    min_liquidity: float = 10_000       # 最小流動性 ($)
    use_llm: bool = False               # LLM 分析を使うか
    llm_model: str = "claude-haiku-4-5-20251001"
    min_edge: float = 0.10              # シグナルフィルター: 最小エッジ
    min_confidence: float = 0.60        # シグナルフィルター: 最小信頼度
    initial_balance: float = 1000.0     # バックテスト開始時の残高 (USDC)
    kelly_fraction: float = 0.25        # Quarter Kelly
    max_position_pct: float = 0.10      # 最大ポジションサイズ (残高比)
    analysis_point_pct: float = 0.60    # マーケット期間の何%時点で分析するか


@dataclass
class TradeRecord:
    market_id: str
    question: str
    side: str                           # BUY_YES / BUY_NO
    entry_price: float                  # 分析時点の YES 価格
    resolution: float                   # 1.0 = YES 解決, 0.0 = NO 解決
    size: float                         # ポジションサイズ (USDC)
    pnl: float
    edge: float
    confidence: float
    predicted_prob: float
    days_held: float                    # 分析時点〜解決までの日数 (概算)


@dataclass
class BacktestSummary:
    markets_fetched: int
    markets_skipped: int
    signals_generated: int
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    roi: float                          # total_pnl / initial_balance
    avg_pnl_per_trade: float
    avg_edge: float
    max_drawdown: float
    sharpe_ratio: float
    initial_balance: float
    final_balance: float


# ===== バックテスター =====

class Backtester:

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.price_fetcher = PriceHistoryFetcher()
        self.feature_extractor = FeatureExtractor()
        self.aggregator = BayesianAggregator()

        # ML モデル (lgb_model.pkl が存在すれば読み込む)
        self.ml_analyst: Optional[MLAnalyst] = None
        ml_path = Path(__file__).parent.parent / "models" / "lgb_model.pkl"
        if ml_path.exists():
            try:
                self.ml_analyst = MLAnalyst(model_path=str(ml_path))
                print(f"   📂 ML モデル: {ml_path.name}")
            except Exception as e:
                print(f"   ⚠️ ML モデル読み込み失敗: {e}")
        else:
            print("   ℹ️  ML モデルなし (LLM / 市場価格のみで Bayesian 統合)")

        # LLM (--use-llm 時のみ)
        self.llm_analyst = None
        if config.use_llm:
            from analyst.llm_analyst import LLMAnalyst
            self.llm_analyst = LLMAnalyst(model=config.llm_model)
            print(f"   🤖 LLM: {config.llm_model}")

    # --------- メインフロー ---------

    async def run(self) -> Optional[BacktestSummary]:
        print("\n" + "=" * 60)
        print("📊 バックテスト開始")
        print(f"   期間        : 過去 {self.config.days} 日")
        print(f"   最大件数    : {self.config.limit} マーケット")
        print(f"   最小エッジ  : {self.config.min_edge:.0%}")
        print(f"   分析ポイント: 期間の {self.config.analysis_point_pct:.0%} 時点")
        print(f"   LLM         : {'有効' if self.config.use_llm else '無効'}")
        print(f"   ML          : {'有効' if self.ml_analyst else '無効'}")
        print("=" * 60 + "\n")

        # 1. 解決済みマーケットを取得
        markets = await self._fetch_resolved_markets()
        if not markets:
            print("❌ 対象マーケットが見つかりません")
            return None
        print(f"✅ 対象マーケット: {len(markets)} 件\n")

        # 2. 各マーケットでバックテスト
        trades: List[TradeRecord] = []
        skipped = 0
        signals_generated = 0

        for i, market in enumerate(markets, 1):
            q = getattr(market, "question", "")[:55]
            print(f"[{i:3}/{len(markets)}] {q}")

            result = await self._backtest_market(market)
            await asyncio.sleep(0.3)  # レート制限

            if result == "skip":
                skipped += 1
                print("         → スキップ (価格履歴不足)")
            elif result == "no_signal":
                print("         → シグナルなし")
            elif result is not None:
                signals_generated += 1
                trades.append(result)
                emoji = "✅" if result.pnl > 0 else "❌"
                print(
                    f"         → {result.side:<8} entry={result.entry_price:.3f} "
                    f"edge={result.edge:+.1%} pnl={result.pnl:+.2f} {emoji}"
                )

        # 3. サマリー計算・表示・保存
        summary = self._compute_summary(len(markets), skipped, signals_generated, trades)
        self._print_summary(summary, trades)
        self._save_results(summary, trades)

        return summary

    # --------- マーケット取得 ---------

    async def _fetch_resolved_markets(self) -> list:
        try:
            client = PolyClient()
            client.connect(read_only=True)
            raw = client.get_markets(limit=500, active=False)
            if not raw:
                return []

            cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.days)
            result = []

            for m in raw:
                # 解決済み (YES / NO) のみ
                outcome = str(getattr(m, "outcome", "")).upper()
                if outcome not in ("YES", "NO"):
                    continue

                # YES token 必須
                if not getattr(m, "yes_token_id", None):
                    continue

                # 出来高・流動性フィルター
                if getattr(m, "volume", 0) < self.config.min_volume:
                    continue
                if getattr(m, "liquidity", 0) < self.config.min_liquidity:
                    continue

                # 期間フィルター (解決日が cutoff より新しいもの)
                end_date = getattr(m, "end_date", None)
                if end_date:
                    if isinstance(end_date, str):
                        try:
                            end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        except Exception:
                            end_date = None
                    if isinstance(end_date, datetime):
                        if end_date.tzinfo is None:
                            end_date = end_date.replace(tzinfo=timezone.utc)
                        if end_date < cutoff:
                            continue

                result.append(m)
                if len(result) >= self.config.limit:
                    break

            return result

        except Exception as e:
            print(f"❌ マーケット取得エラー: {e}")
            return []

    # --------- 単一マーケットのバックテスト ---------

    async def _backtest_market(self, market):
        """
        Returns:
            TradeRecord  - シグナルあり・約定
            "no_signal"  - フィルターで除外
            "skip"       - データ不足
        """
        try:
            # 価格履歴取得 (解決済みマーケットなので全期間)
            price_points = await self.price_fetcher.fetch_prices(
                token_id=market.yes_token_id,
                interval="max",
                fidelity=60,
            )

            # 最低 48 ポイント (2 日分の時間足) 必要
            if len(price_points) < 48:
                return "skip"

            n = len(price_points)

            # 分析ポイント: 期間の analysis_point_pct 時点
            # 最低 24 ポイント後 & 解決前 24 ポイント以上残す
            analysis_idx = int(n * self.config.analysis_point_pct)
            analysis_idx = max(24, min(analysis_idx, n - 24))

            # 分析時点以前の価格のみ使用 (lookahead 防止)
            history = [p.price for p in price_points[:analysis_idx]]
            entry_price = history[-1]

            # 価格が 0 か 1 に張り付いていたらスキップ (解決直前のデータ汚染)
            if entry_price <= 0.01 or entry_price >= 0.99:
                return "skip"

            # 解決結果
            outcome = str(getattr(market, "outcome", "")).upper()
            resolution = 1.0 if outcome == "YES" else 0.0

            # 解決まで何時間あったか (概算)
            hours_to_resolution = n - analysis_idx
            days_held = hours_to_resolution / 24.0

            # シグナル生成
            signal = await self._generate_signal(market, history, entry_price)
            if signal is None:
                return "no_signal"

            edge = signal["edge"]
            confidence = signal["confidence"]
            predicted_prob = signal["probability"]

            # フィルター
            if abs(edge) < self.config.min_edge:
                return "no_signal"
            if confidence < self.config.min_confidence:
                return "no_signal"

            # ポジションサイズ (Quarter Kelly)
            size = self._calc_size(edge, confidence, entry_price)

            # 方向決定
            side = "BUY_YES" if edge > 0 else "BUY_NO"

            # PnL 計算 (position_tracker と同じロジック)
            if side == "BUY_YES":
                pnl = (1 - entry_price) * size if resolution >= 0.5 else -entry_price * size
            else:  # BUY_NO
                pnl = entry_price * size if resolution < 0.5 else -(1 - entry_price) * size

            return TradeRecord(
                market_id=getattr(market, "condition_id", ""),
                question=getattr(market, "question", "")[:80],
                side=side,
                entry_price=round(entry_price, 6),
                resolution=resolution,
                size=round(size, 2),
                pnl=round(pnl, 4),
                edge=round(edge, 4),
                confidence=round(confidence, 4),
                predicted_prob=round(predicted_prob, 4),
                days_held=round(days_held, 1),
            )

        except Exception:
            return "skip"

    # --------- シグナル生成 ---------

    async def _generate_signal(
        self,
        market,
        prices: List[float],
        yes_price: float,
    ) -> Optional[dict]:
        """ML + (任意) LLM → Bayesian 統合でシグナルを生成"""
        signals: List[SignalSource] = []

        # ML シグナル
        if self.ml_analyst:
            features = self.feature_extractor.extract(
                prices=prices,
                yes_price=yes_price,
                market_volume=getattr(market, "volume", 0),
                market_liquidity=getattr(market, "liquidity", 0),
                end_date=getattr(market, "end_date", None),
            )
            ml_pred = self.ml_analyst.predict(features)
            signals.append(SignalSource(
                name="LightGBM",
                probability=ml_pred.probability,
                confidence=ml_pred.confidence,
                accuracy=0.55,
            ))

        # LLM シグナル (オプション)
        if self.llm_analyst:
            try:
                llm_result = await self.llm_analyst.analyze_market(
                    question=getattr(market, "question", ""),
                    current_price=yes_price,
                )
                if llm_result:
                    signals.append(SignalSource(
                        name="LLM",
                        probability=llm_result.get("probability", 0.5),
                        confidence=llm_result.get("confidence", 0.5),
                        accuracy=0.65,
                    ))
            except Exception:
                pass

        # シグナルが1つもない場合は Bayesian の結果が market_price のみになる
        # それでも一応実行して edge = 0 → no_signal に落ちる
        result = self.aggregator.aggregate(
            market_price=yes_price,
            signals=signals,
            market_liquidity=getattr(market, "liquidity", 0),
        )

        return {
            "probability": result.final_probability,
            "edge": result.edge,
            "confidence": result.confidence,
        }

    # --------- サイジング ---------

    def _calc_size(self, edge: float, confidence: float, market_price: float) -> float:
        """Quarter Kelly でポジションサイズを計算"""
        if edge > 0:
            win_return = (1 - market_price) / market_price
        else:
            win_return = market_price / (1 - market_price) if market_price < 1 else 1.0

        win_prob = min(0.95, max(0.5, 0.5 + abs(edge) / 2))
        b = win_return
        raw_kelly = (win_prob * b - (1 - win_prob)) / b if b > 0 else 0
        raw_kelly = max(0.0, raw_kelly)

        applied = raw_kelly * self.config.kelly_fraction * confidence
        applied = min(applied, self.config.max_position_pct)

        amount = self.config.initial_balance * applied
        return round(max(1.0, min(amount, self.config.initial_balance * self.config.max_position_pct)), 2)

    # --------- サマリー計算 ---------

    def _compute_summary(
        self,
        markets_fetched: int,
        markets_skipped: int,
        signals_generated: int,
        trades: List[TradeRecord],
    ) -> BacktestSummary:
        n = len(trades)
        if n == 0:
            return BacktestSummary(
                markets_fetched=markets_fetched,
                markets_skipped=markets_skipped,
                signals_generated=signals_generated,
                trades=0,
                wins=0, losses=0, win_rate=0,
                total_pnl=0, roi=0,
                avg_pnl_per_trade=0, avg_edge=0,
                max_drawdown=0, sharpe_ratio=0,
                initial_balance=self.config.initial_balance,
                final_balance=self.config.initial_balance,
            )

        wins = sum(1 for t in trades if t.pnl > 0)
        total_pnl = sum(t.pnl for t in trades)

        # 最大ドローダウン (トレード順)
        balance = self.config.initial_balance
        peak = balance
        max_dd = 0.0
        for t in trades:
            balance += t.pnl
            peak = max(peak, balance)
            dd = (peak - balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Sharpe比 (トレードごとのリターン率ベース)
        returns = [t.pnl / self.config.initial_balance for t in trades]
        if n > 1:
            mean_r = statistics.mean(returns)
            std_r = statistics.stdev(returns)
            sharpe = (mean_r / std_r * (n ** 0.5)) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        return BacktestSummary(
            markets_fetched=markets_fetched,
            markets_skipped=markets_skipped,
            signals_generated=signals_generated,
            trades=n,
            wins=wins,
            losses=n - wins,
            win_rate=round(wins / n, 4),
            total_pnl=round(total_pnl, 2),
            roi=round(total_pnl / self.config.initial_balance, 4),
            avg_pnl_per_trade=round(total_pnl / n, 2),
            avg_edge=round(sum(t.edge for t in trades) / n, 4),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 3),
            initial_balance=self.config.initial_balance,
            final_balance=round(self.config.initial_balance + total_pnl, 2),
        )

    # --------- 表示 ---------

    def _print_summary(self, summary: BacktestSummary, trades: List[TradeRecord]):
        print("\n" + "=" * 60)
        print("📊 バックテスト結果サマリー")
        print("=" * 60)
        print(f"  マーケット数      : {summary.markets_fetched} "
              f"(スキップ: {summary.markets_skipped}, シグナル: {summary.signals_generated})")
        print(f"  約定トレード数    : {summary.trades}")
        print()
        if summary.trades == 0:
            print("  ⚠️  約定トレードなし (エッジ・信頼度の閾値を下げてみてください)")
            print("=" * 60)
            return

        win_bar = "█" * int(summary.win_rate * 20) + "░" * (20 - int(summary.win_rate * 20))
        print(f"  勝率              : {summary.win_rate:.1%}  [{win_bar}]  "
              f"({summary.wins}勝 / {summary.losses}敗)")
        print(f"  総 PnL            : ${summary.total_pnl:+,.2f}")
        print(f"  ROI               : {summary.roi:+.1%}")
        print(f"  平均 PnL / トレード: ${summary.avg_pnl_per_trade:+.2f}")
        print(f"  平均エッジ        : {summary.avg_edge:+.1%}")
        print()
        print(f"  最大ドローダウン  : {summary.max_drawdown:.1%}")
        print(f"  Sharpe 比         : {summary.sharpe_ratio:.2f}")
        print()
        print(f"  初期残高          : ${summary.initial_balance:,.0f}")
        print(f"  最終残高 (試算)   : ${summary.final_balance:,.2f}")
        print("=" * 60)

        if trades:
            print("\n📋 全トレード (PnL 順):")
            print(f"  {'質問':<42} {'方向':<8} {'Entry':>6} {'Edge':>7} {'PnL':>8}  {'保有'}")
            print("  " + "-" * 80)
            for t in sorted(trades, key=lambda x: x.pnl, reverse=True):
                emoji = "✅" if t.pnl > 0 else "❌"
                print(
                    f"  {t.question[:40]:<40} {emoji} "
                    f"{t.side:<8} {t.entry_price:>6.3f} "
                    f"{t.edge:>+7.1%} {t.pnl:>+8.2f}  {t.days_held:.1f}日"
                )

    # --------- 保存 ---------

    def _save_results(self, summary: BacktestSummary, trades: List[TradeRecord]):
        out_path = Path(__file__).parent.parent / "data" / "backtest_results.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "days": self.config.days,
                "limit": self.config.limit,
                "min_volume": self.config.min_volume,
                "min_edge": self.config.min_edge,
                "min_confidence": self.config.min_confidence,
                "use_llm": self.config.use_llm,
                "ml_enabled": self.ml_analyst is not None,
                "initial_balance": self.config.initial_balance,
                "analysis_point_pct": self.config.analysis_point_pct,
            },
            "summary": asdict(summary),
            "trades": [asdict(t) for t in trades],
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n💾 結果を保存: {out_path}")


# ===== CLI =====

def main():
    parser = argparse.ArgumentParser(
        description="Poly AI Trader - エンドツーエンドバックテスト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/backtest.py                           # デフォルト設定
  python scripts/backtest.py --days 90 --limit 100    # 過去90日 最大100件
  python scripts/backtest.py --use-llm                # LLM 分析あり (API費用注意)
  python scripts/backtest.py --min-edge 0.15          # エッジ閾値15%
  python scripts/backtest.py --analysis-point 0.5    # 期間50%時点で分析
        """,
    )
    parser.add_argument("--days",             type=int,   default=90,    help="過去何日分を対象にするか")
    parser.add_argument("--limit",            type=int,   default=100,   help="最大マーケット数")
    parser.add_argument("--min-volume",       type=float, default=10000, help="最小 24h 出来高 ($)")
    parser.add_argument("--min-liquidity",    type=float, default=10000, help="最小流動性 ($)")
    parser.add_argument("--min-edge",         type=float, default=0.10,  help="最小エッジ")
    parser.add_argument("--min-confidence",   type=float, default=0.60,  help="最小信頼度")
    parser.add_argument("--use-llm",          action="store_true",       help="LLM 分析を有効化 (API費用発生)")
    parser.add_argument("--llm-model",        default="claude-haiku-4-5-20251001", help="LLM モデル名")
    parser.add_argument("--balance",          type=float, default=1000.0, help="初期残高 (USDC)")
    parser.add_argument("--analysis-point",   type=float, default=0.60,
                        help="マーケット期間の何%%時点で分析するか (0.0〜1.0, デフォルト: 0.60)")

    args = parser.parse_args()

    config = BacktestConfig(
        days=args.days,
        limit=args.limit,
        min_volume=args.min_volume,
        min_liquidity=args.min_liquidity,
        use_llm=args.use_llm,
        llm_model=args.llm_model,
        min_edge=args.min_edge,
        min_confidence=args.min_confidence,
        initial_balance=args.balance,
        analysis_point_pct=args.analysis_point,
    )

    backtester = Backtester(config)
    asyncio.run(backtester.run())


if __name__ == "__main__":
    main()
