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

import httpx

from analyst.features import FeatureExtractor
from analyst.ml_analyst import MLAnalyst
from analyst.bayesian import BayesianAggregator, SignalSource
from data_fetcher import PriceHistoryFetcher

GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class ResolvedMarket:
    """バックテスト用: 解決済みマーケット"""
    condition_id: str
    question: str
    yes_token_id: str
    outcome: str          # "YES" or "NO"
    volume: float
    liquidity: float
    end_date: Optional[datetime]


# ===== データクラス =====

@dataclass
class BacktestConfig:
    days: int = 90                      # 過去何日分のマーケットを対象にするか
    limit: int = 100                    # 最大マーケット数
    min_volume: float = 1_000           # 最小出来高 ($) ※closed後はliquidityが0になるためvolumeのみでフィルター
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
            q = market.question[:55]
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

    async def _fetch_resolved_markets(self) -> List[ResolvedMarket]:
        """Gamma API から解決済みマーケットを直接取得"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.days)
        result: List[ResolvedMarket] = []
        offset = 0
        fetch_limit = 50
        max_pages = 200  # 安全弁 (10,000件まで)
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

        print("🌐 Gamma API から解決済みマーケットを取得中...")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                pages = 0
                while len(result) < self.config.limit and pages < max_pages:
                    print(f"   ページ取得中 (offset={offset}, 取得済み={len(result)})...")
                    resp = await client.get(
                        f"{GAMMA_API}/markets",
                        params={
                            "closed": "true",
                            "limit": fetch_limit,
                            "offset": offset,
                            # closedTime降順: 直近に解決されたマーケットから取得
                            "order": "closedTime",
                            "ascending": "false",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    if not data:
                        break

                    past_cutoff = False  # このページに cutoff より古いマーケットがあった

                    for m in data:
                        # ── 解決日時フィルター (closedTime を使用) ──────────
                        closed_time = None
                        ct_str = m.get("closedTime")
                        if ct_str:
                            try:
                                # "2026-03-16 02:50:25+00" → "2026-03-16T02:50:25+00:00"
                                ct_norm = ct_str.strip().replace(" ", "T")
                                if ct_norm.endswith("+00"):
                                    ct_norm += ":00"
                                elif not ct_norm.endswith("Z") and "+" not in ct_norm[10:] and "-" not in ct_norm[10:]:
                                    ct_norm += "+00:00"
                                closed_time = datetime.fromisoformat(ct_norm)
                            except Exception:
                                pass
                        if closed_time:
                            if closed_time.tzinfo is None:
                                closed_time = closed_time.replace(tzinfo=timezone.utc)
                            if closed_time < cutoff:
                                past_cutoff = True
                                continue

                        # ── 解決済み判定: outcomePrices を最優先 ──────────
                        outcome = None
                        op_raw = m.get("outcomePrices", "[]")
                        try:
                            op = json.loads(op_raw) if isinstance(op_raw, str) else op_raw
                            if op and len(op) >= 2:
                                p0 = float(op[0])
                                p1 = float(op[1])
                                if p0 >= 0.99:
                                    outcome = "YES"
                                elif p1 >= 0.99:
                                    outcome = "NO"
                        except Exception:
                            pass

                        # テキストフィールドでフォールバック
                        if outcome is None:
                            res_raw = (
                                m.get("resolutionResult")
                                or m.get("resolution")
                                or m.get("winner")
                                or ""
                            )
                            rs = str(res_raw).strip().upper()
                            if rs in ("1", "YES", "TRUE"):
                                outcome = "YES"
                            elif rs in ("0", "NO", "FALSE"):
                                outcome = "NO"

                        if outcome is None:
                            continue  # 未解決 / 無効 / 引き分けはスキップ

                        # ── 短期マーケット除外 ────────────────────────────
                        # createdAt〜closedTime が1日未満 → 5分足/短期バイナリ → スキップ
                        created_str = m.get("createdAt")
                        if created_str and closed_time:
                            try:
                                # 小数秒を6桁に正規化 (Pythonのfromisoformatは3/6桁のみ対応)
                                import re as _re
                                ca_norm = _re.sub(r'\.(\d+)', lambda x: '.' + x.group(1).ljust(6,'0')[:6], created_str)
                                ca_norm = ca_norm.replace("Z", "+00:00")
                                created_at = datetime.fromisoformat(ca_norm)
                                if created_at.tzinfo is None:
                                    created_at = created_at.replace(tzinfo=timezone.utc)
                                if (closed_time - created_at).total_seconds() < 172800:
                                    continue  # 存続2日未満はスキップ (5分〜24h短期バイナリ除外)
                            except Exception:
                                pass

                        # ── YES token ID ──────────────────────────────────
                        clob_ids = m.get("clobTokenIds", "[]")
                        try:
                            token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                        except Exception:
                            token_ids = []
                        yes_token_id = token_ids[0] if token_ids else ""
                        if not yes_token_id:
                            continue

                        # ── 出来高フィルター (liquidityNum は closed後 null になるので無視) ──
                        volume = float(m.get("volumeNum") or m.get("volume") or 0)
                        if volume < self.config.min_volume:
                            continue

                        # end_date は参考値として保持 (バックテスト期間計算用)
                        end_date = None
                        ed_str = m.get("endDateIso") or m.get("endDate")
                        if ed_str:
                            try:
                                end_date = datetime.fromisoformat(
                                    ed_str.replace("Z", "+00:00")
                                )
                                if end_date.tzinfo is None:
                                    end_date = end_date.replace(tzinfo=timezone.utc)
                            except Exception:
                                pass

                        result.append(ResolvedMarket(
                            condition_id=m.get("conditionId") or m.get("condition_id", ""),
                            question=m.get("question", ""),
                            yes_token_id=yes_token_id,
                            outcome=outcome,
                            volume=volume,
                            liquidity=0.0,  # closed後は0になるため除外
                            end_date=closed_time or end_date,
                        ))

                        if len(result) >= self.config.limit:
                            break

                    # closedTime降順でページ全体が期間外なら終了
                    if past_cutoff and len(result) == 0 and pages > 0:
                        print("   期間外マーケットのみ — 探索終了")
                        break

                    if len(data) < fetch_limit:
                        break  # 最終ページ

                    offset += fetch_limit
                    pages += 1
                    await asyncio.sleep(0.3)

        except Exception as e:
            print(f"❌ マーケット取得エラー: {e}")

        return result

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

            # 価格が極端な場合はスキップ (解決直前のデータ汚染 / 長射程マーケット)
            if entry_price <= 0.05 or entry_price >= 0.95:
                return "skip"

            # 解決結果 (ResolvedMarket.outcome は既に "YES"/"NO" に正規化済み)
            resolution = 1.0 if market.outcome == "YES" else 0.0

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
                market_id=market.condition_id,
                question=market.question[:80],
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
                market_volume=market.volume,
                market_liquidity=market.liquidity,
                end_date=market.end_date,
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
                    question=market.question,
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
            market_liquidity=market.liquidity,
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
    parser.add_argument("--min-volume",       type=float, default=1000,  help="最小出来高 ($)")
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
