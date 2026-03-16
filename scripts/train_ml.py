#!/usr/bin/env python3
"""
ML Model Training Script

解決済みマーケットの「期間60%時点」スナップショットで学習。
lookahead bias なし。

実行:
  python scripts/train_ml.py --days 90
  python scripts/train_ml.py --days 90 --min-volume 1000 --limit 300
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
from analyst.features import FeatureExtractor
from analyst.ml_analyst import MLAnalyst

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

MODEL_DIR = Path(__file__).parent.parent / "models"


# ──────────────────────────────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────────────────────────────

def _parse_dt(s: str) -> datetime | None:
    """各種 ISO 形式の日時文字列を UTC datetime に変換。失敗時は None。"""
    if not s:
        return None
    try:
        s = s.strip().replace(" ", "T")
        # 小数秒を6桁に正規化
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
# マーケット取得 (backtest.py と同じロジック)
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_resolved_markets(
    days: int,
    limit: int,
    min_volume: float,
) -> list[dict]:
    """
    Gamma API から解決済みマーケットを取得。

    - closedTime 降順: 最近解決されたものから取得
    - outcomePrices でYES/NO判定 (resolutionResult は null が多い)
    - createdAt〜closedTime < 2日のマーケットは除外 (短期バイナリ)
    - lookahead 防止: 価格データは後で fetch するため yes_price を含めない
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = []
    offset = 0
    max_pages = 200
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    print(f"🌐 Gamma API から解決済みマーケットを取得中 (過去{days}日)...")

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
                # ── 解決日時チェック ─────────────────────────────────────
                closed_time = _parse_dt(m.get("closedTime"))
                if closed_time and closed_time < cutoff:
                    past_cutoff = True
                    continue

                # ── 短期マーケット除外 (createdAt〜closedTime < 2日) ─────
                created_at = _parse_dt(m.get("createdAt"))
                if closed_time and created_at:
                    if (closed_time - created_at).total_seconds() < 172800:
                        continue

                # ── 解決結果: outcomePrices 優先 ─────────────────────────
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

                # end_date は特徴量 (残り期間) 計算に使う
                end_date = _parse_dt(m.get("endDateIso") or m.get("endDate"))

                result.append({
                    "yes_token_id": yes_token_id,
                    "outcome": outcome,
                    "volume": volume,
                    "liquidity": float(m.get("liquidityNum") or m.get("liquidity") or 0),
                    "end_date": end_date,
                    "question": m.get("question", "")[:60],
                })

                if len(result) >= limit:
                    break

            if past_cutoff and not result and pages > 0:
                break
            if len(data) < 50:
                break

            offset += 50
            pages += 1
            await asyncio.sleep(0.2)

    print(f"   → {len(result)} 件取得")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 学習データ収集
# ──────────────────────────────────────────────────────────────────────────────

async def collect_training_data(
    markets: list[dict],
    analysis_point_pct: float = 0.60,
) -> tuple[np.ndarray, np.ndarray]:
    """
    各マーケットの「期間 analysis_point_pct 時点」スナップショットで特徴量を生成。
    lookahead bias なし。
    """
    fetcher = PriceHistoryFetcher()
    extractor = FeatureExtractor()
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    X_list, y_list = [], []

    async with httpx.AsyncClient(timeout=timeout) as hclient:
        for i, m in enumerate(markets):
            try:
                # 1. 価格履歴取得
                price_points = await fetcher.fetch_prices(
                    token_id=m["yes_token_id"],
                    interval="max",
                    fidelity=60,  # 1時間足
                )

                n = len(price_points)
                if n < 48:
                    continue  # 最低2日分必要

                # 2. 分析ポイント: 期間の analysis_point_pct 時点
                #    解決前24h 以上残す & 最低24h 後
                analysis_idx = int(n * analysis_point_pct)
                analysis_idx = max(24, min(analysis_idx, n - 24))

                # 3. 分析時点以前のデータのみ使用 (lookahead 防止)
                history = [p.price for p in price_points[:analysis_idx]]
                yes_price = history[-1]  # 分析時点の YES 価格

                # 価格が既に0/1に張り付いていたらスキップ (解決直前データ汚染)
                if yes_price <= 0.01 or yes_price >= 0.99:
                    continue

                # 4. 取引履歴 (buy_volume_ratio / order_flow_imbalance 用)
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

                # 5. 特徴量抽出 (分析時点の yes_price を使用)
                features = extractor.extract(
                    prices=history[-100:],
                    trades=trades if trades else None,
                    yes_price=yes_price,
                    market_volume=m["volume"],
                    market_liquidity=m["liquidity"],
                    end_date=m["end_date"],
                )

                X_list.append(features.to_list())
                y_list.append(1 if m["outcome"] == "YES" else 0)

                outcome_str = "YES✅" if m["outcome"] == "YES" else "NO ❌"
                print(
                    f"  [{i+1:3}/{len(markets)}] {m['question']:<45} "
                    f"price={yes_price:.3f} → {outcome_str}"
                )

            except Exception as e:
                print(f"  [{i+1:3}/{len(markets)}] スキップ: {e}")

            await asyncio.sleep(0.3)

    X = np.array(X_list) if X_list else np.array([]).reshape(0, 0)
    y = np.array(y_list) if y_list else np.array([])
    print(f"\n📦 学習データ: {len(X_list)} 件")
    return X, y


# ──────────────────────────────────────────────────────────────────────────────
# 学習 & 保存
# ──────────────────────────────────────────────────────────────────────────────

def train_and_save(X: np.ndarray, y: np.ndarray, model_path: str) -> bool:
    if len(X) < 50:
        print(f"⚠️  データ不足 ({len(X)} 件 < 50 件必要)")
        return False

    from sklearn.model_selection import train_test_split

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
    )

    print(f"\n🤖 LightGBM 学習中... (train={len(X_train)}, val={len(X_val)})")
    print(f"   ラベル分布: YES={int(y.sum())}, NO={int(len(y)-y.sum())}")

    analyst = MLAnalyst()
    result = analyst.train(X_train, y_train, X_val, y_val)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    analyst.save_model(model_path)

    print(f"\n✅ モデル保存: {model_path}")
    if result.get("valid_auc"):
        print(f"   Train AUC : {result.get('train_auc', 'N/A')}")
        print(f"   Valid AUC : {result['valid_auc']:.4f}")
    else:
        print(f"   木の数    : {result.get('n_estimators', 'N/A')}")

    return True


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="ML Model Training (lookahead-free)")
    parser.add_argument("--days",             type=int,   default=90,   help="過去何日分を対象にするか")
    parser.add_argument("--limit",            type=int,   default=500,  help="最大マーケット数")
    parser.add_argument("--min-volume",       type=float, default=1000, help="最小出来高 ($)")
    parser.add_argument("--analysis-point",   type=float, default=0.60, help="期間の何%%時点で分析するか (0-1)")
    parser.add_argument("--output",           default=str(MODEL_DIR / "lgb_model.pkl"), help="出力パス")
    args = parser.parse_args()

    print("🚀 ML Model Training (lookahead-free)\n")
    print(f"   期間          : 過去 {args.days} 日")
    print(f"   最大件数      : {args.limit} マーケット")
    print(f"   最小出来高    : ${args.min_volume:,.0f}")
    print(f"   分析ポイント  : 期間の {args.analysis_point:.0%} 時点\n")

    # 1. 解決済みマーケット取得
    markets = await fetch_resolved_markets(
        days=args.days,
        limit=args.limit,
        min_volume=args.min_volume,
    )
    if not markets:
        print("❌ 解決済みマーケットが見つかりませんでした")
        return

    # 2. 特徴量 & ラベル収集
    X, y = await collect_training_data(markets, analysis_point_pct=args.analysis_point)
    if len(X) == 0:
        print("❌ 学習データを収集できませんでした")
        return

    # 3. 学習 & 保存
    train_and_save(X, y, args.output)


if __name__ == "__main__":
    asyncio.run(main())
