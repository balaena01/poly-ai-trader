#!/usr/bin/env python3
"""
Crypto-specific ML Model Training Script

crypto マーケット（BTC/ETH/Solana等の価格予測系）のみを対象に
CryptoFeatures (36特徴量) で LightGBM を学習。
汎用モデル (lgb_model.pkl) とは完全に独立。

実行:
  python scripts/train_crypto_ml.py --days 180
  python scripts/train_crypto_ml.py --days 365 --limit 300 --min-volume 5000

注意:
  - crypto系マーケットは全体の数%程度のため --days を長めに設定推奨
  - 最低 50 件の学習データが必要 (実際は 100+ 件推奨)
"""
import asyncio
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import numpy as np

from data_fetcher import PriceHistoryFetcher
from analyst.crypto_features import CryptoFeatureExtractor, is_crypto_market
from analyst.crypto_ml_analyst import CryptoMLAnalyst
from analyst.ml_analyst import MLAnalyst

COINGECKO_API = "https://api.coingecko.com/api/v3"

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

MODEL_DIR = Path(__file__).parent.parent / "models"


# ──────────────────────────────────────────────────────────────────────────────
# ユーティリティ (train_ml.py から共有)
# ──────────────────────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s = s.strip().replace(" ", "T")
        s = re.sub(r'\.(\d+)', lambda m: '.' + m.group(1).ljust(6, '0')[:6], s)
        if s.endswith("+00"):
            s += ":00"
        elif not s.endswith("Z") and "+" not in s[10:] and s.count("-") <= 2:
            s += "+00:00"
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# crypto マーケット取得 (全体から is_crypto_market() でフィルタ)
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_crypto_markets(
    days: int,
    limit: int,
    min_volume: float,
) -> list[dict]:
    """
    Gamma API から解決済みcryptoマーケットを取得。

    - is_crypto_market() でフィルタリング (BTC/ETH/Solana等のキーワード)
    - 件数が揃うまでページネーション
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    offset = 0
    max_pages = 500  # cryptoは少ないので多めにページ取得
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    total_checked = 0
    print(f"🌐 Gamma API から crypto マーケットを取得中 (過去{days}日)...")
    print(f"   ※ 全マーケットをスキャンして crypto キーワードでフィルタ")

    async with httpx.AsyncClient(timeout=timeout) as client:
        pages = 0
        while len(result) < limit and pages < max_pages:
            resp = await client.get(
                f"{GAMMA_API}/markets",
                params={
                    "closed": "true",
                    "limit": 50,
                    "offset": offset,
                    "order": "closedTime",
                    "ascending": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break

            past_cutoff = False

            for m in data:
                total_checked += 1

                # ── 日付チェック ─────────────────────────────────────────────
                closed_time = _parse_dt(m.get("closedTime"))
                if closed_time and closed_time < cutoff:
                    past_cutoff = True
                    continue

                # ── crypto キーワードフィルタ ─────────────────────────────
                question = m.get("question", "")
                if not is_crypto_market(question):
                    continue

                # ── 短期マーケット除外 (< 2日) ───────────────────────────
                created_at = _parse_dt(m.get("createdAt"))
                if closed_time and created_at:
                    if (closed_time - created_at).total_seconds() < 172800:
                        continue

                # ── 解決結果 ─────────────────────────────────────────────
                outcome = None
                op_raw = m.get("outcomePrices", "[]")
                try:
                    op = json.loads(op_raw) if isinstance(op_raw, str) else op_raw
                    if op and len(op) >= 2:
                        p0, p1 = float(op[0]), float(op[1])
                        if p0 >= 0.99:
                            outcome = "YES"
                        elif p1 >= 0.99:
                            outcome = "NO"
                except Exception:
                    pass

                if outcome is None:
                    rs = str(
                        m.get("resolutionResult") or m.get("resolution") or ""
                    ).strip().upper()
                    if rs in ("1", "YES", "TRUE"):
                        outcome = "YES"
                    elif rs in ("0", "NO", "FALSE"):
                        outcome = "NO"

                if outcome is None:
                    continue

                # ── YES token ID ─────────────────────────────────────────
                clob_ids = m.get("clobTokenIds", "[]")
                try:
                    token_ids = json.loads(clob_ids) if isinstance(clob_ids, str) else clob_ids
                except Exception:
                    token_ids = []
                yes_token_id = token_ids[0] if token_ids else ""
                if not yes_token_id:
                    continue

                # ── 出来高フィルター ─────────────────────────────────────
                volume = float(m.get("volumeNum") or m.get("volume") or 0)
                if volume < min_volume:
                    continue

                end_date = _parse_dt(m.get("endDateIso") or m.get("endDate"))

                result.append({
                    "yes_token_id": yes_token_id,
                    "outcome": outcome,
                    "volume": volume,
                    "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
                    "end_date": end_date,
                    "question": question[:70],
                    "closed_time": closed_time,
                })

                if len(result) >= limit:
                    break

            if past_cutoff and pages > 5:
                break
            if len(data) < 50:
                break

            offset += 50
            pages += 1
            await asyncio.sleep(0.2)

            if pages % 10 == 0:
                print(f"   ... ページ{pages} 確認済み{total_checked}件 crypto発見{len(result)}件")

    print(f"   → crypto マーケット {len(result)} 件取得 (全体 {total_checked} 件チェック)")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# CoinGecko BTC/ETH ヒストリカル価格取得
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_btc_eth_history(days: int) -> tuple[dict, dict]:
    """
    CoinGecko から BTC/ETH の日足価格を取得し、
    日付 (date string "YYYY-MM-DD") → 24h変化率 の辞書を返す。

    戻り値: (btc_returns, eth_returns)
      btc_returns["2024-06-15"] = 0.032  # +3.2%
    """
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=10.0)

    async def _fetch_coin(coin_id: str) -> dict:
        """coin_id ("bitcoin" / "ethereum") → {date_str: return_24h}"""
        url = f"{COINGECKO_API}/coins/{coin_id}/market_chart"
        params = {
            "vs_currency": "usd",
            "days": str(days),
            "interval": "daily",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            # CoinGeckoは無料枠でrate limitがあるので1回だけ取得
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                print(f"   ⚠️ CoinGecko rate limit, 60秒待機...")
                await asyncio.sleep(60)
                resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        prices = data.get("prices", [])  # [[timestamp_ms, price], ...]
        if not prices:
            return {}

        result = {}
        for i in range(1, len(prices)):
            ts_ms, close = prices[i]
            ts_ms_prev, prev_close = prices[i - 1]
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            if prev_close > 0:
                result[date_str] = (close - prev_close) / prev_close
        return result

    print("📡 CoinGecko から BTC/ETH ヒストリカル価格を取得中...")
    btc_returns = await _fetch_coin("bitcoin")
    await asyncio.sleep(2)  # rate limit 対策
    eth_returns = await _fetch_coin("ethereum")
    print(f"   BTC: {len(btc_returns)} 日分 / ETH: {len(eth_returns)} 日分")
    return btc_returns, eth_returns


def _lookup_crypto_returns(
    analysis_dt: datetime,
    btc_returns: dict,
    eth_returns: dict,
) -> tuple[float | None, float | None]:
    """
    分析時点の日付に対応する BTC/ETH 24h変化率を返す。
    当日データがなければ前後1日を探索。
    """
    for delta in [0, -1, 1, -2, 2]:
        dt = analysis_dt + timedelta(days=delta)
        key = dt.strftime("%Y-%m-%d")
        btc = btc_returns.get(key)
        eth = eth_returns.get(key)
        if btc is not None or eth is not None:
            return btc, eth
    return None, None


# ──────────────────────────────────────────────────────────────────────────────
# 学習データ収集
# ──────────────────────────────────────────────────────────────────────────────

async def collect_training_data(
    markets: list[dict],
    btc_returns: dict,
    eth_returns: dict,
    analysis_point_pct: float = 0.60,
) -> tuple[np.ndarray, np.ndarray]:
    """
    各マーケットの「期間 analysis_point_pct 時点」スナップショットで
    CryptoFeatures (36特徴量) を生成。
    btc_returns / eth_returns は CoinGecko から取得した日付→変化率辞書。
    """
    fetcher = PriceHistoryFetcher()
    extractor = CryptoFeatureExtractor()
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    X_list, y_list = [], []
    btc_matched = 0  # BTC価格が取得できた件数

    async with httpx.AsyncClient(timeout=timeout) as hclient:
        for i, m in enumerate(markets):
            try:
                # 1. YES価格履歴
                price_points = await fetcher.fetch_prices(
                    token_id=m["yes_token_id"],
                    interval="max",
                    fidelity=60,
                )

                n = len(price_points)
                if n < 48:
                    continue

                # 2. 分析ポイント: 期間の analysis_point_pct 時点
                analysis_idx = int(n * analysis_point_pct)
                analysis_idx = max(24, min(analysis_idx, n - 24))

                history = [p.price for p in price_points[:analysis_idx]]
                yes_price = history[-1]

                if yes_price <= 0.15 or yes_price >= 0.85:
                    continue

                # 3. 分析時点の日時を特定 (BTC/ETH価格のlookupに使用)
                analysis_dt = price_points[analysis_idx - 1].t if hasattr(price_points[analysis_idx - 1], 't') else None
                if analysis_dt is None and m.get("closed_time"):
                    # closed_time × analysis_point_pct で概算
                    created = m.get("closed_time")
                    if created:
                        analysis_dt = created  # fallback: closed_time を使用

                btc_24h, eth_24h = None, None
                if analysis_dt:
                    btc_24h, eth_24h = _lookup_crypto_returns(analysis_dt, btc_returns, eth_returns)
                    if btc_24h is not None:
                        btc_matched += 1

                # 4. 取引履歴
                from analyst.orderflow import Trade as OFTrade
                trades = []
                try:
                    tr_resp = await hclient.get(
                        f"{CLOB_API}/trades",
                        params={"market": m["yes_token_id"], "limit": 500},
                    )
                    raw_trades = tr_resp.json()
                    if isinstance(raw_trades, dict):
                        raw_trades = raw_trades.get("data", [])
                    for t in raw_trades:
                        try:
                            ts = _parse_dt(
                                t.get("timestamp") or t.get("match_time") or ""
                            ) or datetime.now(timezone.utc)
                            trades.append(OFTrade(
                                timestamp=ts,
                                price=float(t.get("price", 0)),
                                size=float(t.get("size", 0)),
                                side=(t.get("side") or "").lower(),
                            ))
                        except Exception:
                            pass
                except Exception:
                    pass

                # 5. CryptoFeatures 抽出 (BTC/ETH変化率を注入)
                features = extractor.extract(
                    prices=history[-100:],
                    trades=trades if trades else None,
                    yes_price=yes_price,
                    market_volume=m["volume"],
                    market_liquidity=m["liquidity"],
                    end_date=m["end_date"],
                    btc_change_24h=btc_24h,
                    eth_change_24h=eth_24h,
                    btc_prices_1h=None,  # 時間足データは学習時は不可
                )

                X_list.append(features.to_list())
                y_list.append(1 if m["outcome"] == "YES" else 0)

                outcome_str = "YES✅" if m["outcome"] == "YES" else "NO ❌"
                btc_str = f"btc={btc_24h:+.1%}" if btc_24h is not None else "btc=N/A"
                print(
                    f"  [{i+1:3}/{len(markets)}] {m['question']:<50} "
                    f"price={yes_price:.3f} {btc_str} → {outcome_str}"
                )

            except Exception as e:
                print(f"  [{i+1:3}/{len(markets)}] スキップ: {e}")

            await asyncio.sleep(0.3)

    print(f"   BTC価格マッチ率: {btc_matched}/{len(X_list)} 件")

    X = np.array(X_list) if X_list else np.array([]).reshape(0, 0)
    y = np.array(y_list) if y_list else np.array([])
    print(f"\n📦 学習データ: {len(X_list)} 件 (YES={int(sum(y_list))}, NO={len(y_list)-int(sum(y_list))})")
    return X, y


# ──────────────────────────────────────────────────────────────────────────────
# 学習 & 保存
# ──────────────────────────────────────────────────────────────────────────────

def train_and_save(X: np.ndarray, y: np.ndarray, model_path: str) -> bool:
    """36特徴量で LightGBM を学習し保存"""
    if len(X) < 30:
        print(f"⚠️  データ不足 ({len(X)} 件 < 30 件必要)")
        print("   → より長い期間 (--days 365) で再試行してください")
        return False

    from sklearn.model_selection import train_test_split

    # crypto データは少ないので val 比率を小さめに
    val_ratio = 0.15 if len(X) >= 100 else 0.10

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=val_ratio, random_state=42,
        stratify=y if len(set(y)) > 1 else None,
    )

    print(f"\n🤖 Crypto LightGBM 学習中... (train={len(X_train)}, val={len(X_val)})")
    print(f"   特徴量数: {X.shape[1]} (28 generic + 8 crypto)")
    print(f"   ラベル分布: YES={int(y.sum())}, NO={int(len(y)-y.sum())}")

    # CryptoMLAnalyst (MLAnalystのサブクラス) を使い、36特徴量対応モデルを学習
    analyst = CryptoMLAnalyst(model_path=None)  # モデルなしで初期化
    result = analyst.train(X_train, y_train, X_val, y_val)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    analyst.save_model(model_path)

    print(f"\n✅ Crypto モデル保存: {model_path}")
    if result.get("valid_auc"):
        print(f"   Train AUC : {result.get('train_auc', 'N/A'):.4f}")
        print(f"   Valid AUC : {result['valid_auc']:.4f}")
    print(f"   木の数    : {result.get('n_estimators', 'N/A')}")

    # 特徴量重要度 TOP10
    if result.get("feature_importance"):
        sorted_imp = sorted(
            result["feature_importance"].items(),
            key=lambda x: x[1], reverse=True
        )[:10]
        print("\n📈 特徴量重要度 TOP10:")
        for name, imp in sorted_imp:
            bar = "█" * int(imp / max(v for _, v in sorted_imp) * 20)
            print(f"   {name:<30} {bar} {imp:.1f}")

    return True


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Crypto-specific ML Training (BTC/ETH market only)"
    )
    parser.add_argument("--days",           type=int,   default=180,  help="過去何日分を対象にするか")
    parser.add_argument("--limit",          type=int,   default=300,  help="最大マーケット数")
    parser.add_argument("--min-volume",     type=float, default=2000, help="最小出来高 ($)")
    parser.add_argument("--analysis-point", type=float, default=0.60, help="期間の何%%時点で分析するか")
    parser.add_argument("--output",
                        default=str(MODEL_DIR / "lgb_crypto_model.pkl"),
                        help="出力パス")
    args = parser.parse_args()

    print("🚀 Crypto ML Model Training\n")
    print(f"   対象期間      : 過去 {args.days} 日")
    print(f"   最大件数      : {args.limit} マーケット")
    print(f"   最小出来高    : ${args.min_volume:,.0f}")
    print(f"   分析ポイント  : 期間の {args.analysis_point:.0%} 時点")
    print(f"   出力          : {args.output}\n")

    # 1. crypto マーケット取得
    markets = await fetch_crypto_markets(
        days=args.days,
        limit=args.limit,
        min_volume=args.min_volume,
    )
    if not markets:
        print("❌ crypto マーケットが見つかりませんでした")
        print("   ヒント: --days を増やすか --min-volume を下げてください")
        return

    print(f"\n📋 対象マーケット ({len(markets)} 件):")
    for m in markets[:10]:
        print(f"   • {m['question']}")
    if len(markets) > 10:
        print(f"   ... 他 {len(markets) - 10} 件\n")

    # 2. CoinGecko から BTC/ETH ヒストリカル価格を取得
    btc_returns, eth_returns = await fetch_btc_eth_history(days=args.days + 5)  # 少し余裕を持たせる

    # 3. 特徴量 & ラベル収集
    X, y = await collect_training_data(
        markets,
        btc_returns=btc_returns,
        eth_returns=eth_returns,
        analysis_point_pct=args.analysis_point,
    )
    if len(X) == 0:
        print("❌ 学習データを収集できませんでした")
        return

    # 4. 学習 & 保存
    train_and_save(X, y, args.output)


if __name__ == "__main__":
    asyncio.run(main())
