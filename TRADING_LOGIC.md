# Trading Logic — Poly AI Trader

最終更新: 2026-03-21

---

## エントリー条件

### 1. マーケットフィルター (スキャン時)

| 条件 | 値 |
|---|---|
| 流動性 | ≥ $5,000 |
| 出来高 | ≥ $10,000 |
| YES価格範囲 | 15% ～ 85% |
| 解決まで | 1時間 ～ 30日 |
| スポーツ市場 | スキップ (Brier記録のみ) |
| 相関ポジション | スキップ (LLM が is_correlated: true と判定した場合) |

> YES価格が15%未満・85%超は「確信度が高すぎる市場」として除外。
> 相関チェック: 保有中ポジション一覧を LLM に渡し、同一イベントの別条件・排他的結果を検出。

### 2. シグナル生成 (LLM + Ensemble)

| 条件 | 値 |
|---|---|
| 最小エッジ | ±5% (`LLM予測確率 - 市場価格`) |
| 最小信頼度 | 50% (Audit penalty 適用後) |
| 方向 | BUY_YES / BUY_NO |

- エッジ = `final_probability - market_price`
- プラスなら BUY_YES、マイナスなら BUY_NO

### 3. LLM へのコンテキスト注入

| コンテキスト | 内容 | 更新頻度 |
|---|---|---|
| 関連ニュース | DDG検索→Scrapling本文取得。上位5件は日時+ソース+本文(800字)、6-15件目はヘッドライン。質問カテゴリ(crypto/politics/regulation/geopolitics/tech)自動判定でキーワード補強+優先ソースソート | 毎回 |
| 前回判断 | 同マーケットの前回 LLM 予測 (prob/conf/reasoning) | 毎回 |
| パフォーマンス実績 | 過去30件の勝率・カテゴリ別精度・直近外れ5件 | 30分キャッシュ |
| 保有ポジション一覧 | 相関チェック用 (新規エントリー時のみ) | 毎回 |

### 4. ポジションサイジング (Quarter Kelly)

| 状態 | Kelly 分率 |
|---|---|
| LLM skill 未計測 (解決済み < 20件) | base × **0.5** (半Kelly) |
| skill > 0.10 (正のスキル) | base × **1.0** (通常) |
| skill 0.0 ～ 0.10 | base × **0.5** |
| skill -0.05 ～ 0.0 | base × **0.25** |
| skill < **-0.05** (明確に劣後) | **シグナルブロック** (全エントリー停止) |

- base = **Quarter Kelly (25%)**
- さらに `× confidence` で調整
- 1ポジション上限: 残高の **10%**
- 総エクスポージャー上限: 残高の **50%**

---

## クローズ条件 (優先順位順)

### 損切り

| 優先度 | 名前 | 条件 | 理由 |
|---|---|---|---|
| **1** | 確率崩壊ストップ | BUY_NO: YES確率 ≥ **88%** | 市場の集合知が YES に収束 → NO thesis 崩壊 |
| | | BUY_YES: YES確率 ≤ **12%** | 市場が NO に収束 → YES thesis 崩壊 |
| **2** | 近解決損切り | 残り ≤ **7日** かつ 含み損 ≤ **-40%** | 残り時間が少なく回復見込みなし |
| **4** | LLM逆転クローズ | 再分析でエッジが逆方向 ≥ 5% かつ 信頼度 ≥ 50% | 自分の分析が変わった = 根拠消滅 |
| **5** | 価格ベース損切り | 含み損 ≤ **-80%** | 最終保険のみ |

### 利確

| 優先度 | 名前 | 条件 | 14日制約 | 理由 |
|---|---|---|---|---|
| **3** | エッジ消失利確 | `current_edge < 5%` かつ `entry_edge` 記録済み | **なし** | thesis 消滅 = 残り日数に関係なく撤退 |
| **4** | 価格ベース利確 | 含み益 ≥ **+40%** | **あり** | セカンダリ (LLM再分析が遅い場合のバックアップ) |

### 追加制約

| 制約 | 対象 | 内容 |
|---|---|---|
| 解決まで ≤ 14日 | 価格ベース利確のみ | スキップ → HOLD (GTC コスト > 残存期待値) |
| 残存価値 < $2 | すべて | GTC売り省略 → 直接クローズ (流動性枯渇ループ防止) |

---

## GTC 売り注文のライフサイクル

```
_exit_position() 呼び出し
    │
    ├─ 残存価値 < $2 → 直接クローズ (CLOB売りなし)
    │
    ▼
execute_order() → GTC SELL 発注
    │
    ├─ order_id 取得成功 → mark_pending_sell()
    └─ order_id なし     → mark_needs_manual_sale()

_check_pending_gtc_orders() (毎サイクル)
    │
    ▼ get_order(pending_sell_order_id)
    ├─ MATCHED/FILLED → close_position() ✅
    ├─ CANCELLED      → cancel_pending_sell() (ACTIVE復帰)
    ├─ LIVE (60分超)  → cancel_order() → ACTIVE復帰
    └─ None (取得失敗) → get_token_balance() fallback
                          残高 == 0 → FILLED として close_position() ✅
                          残高 > 0  → スキップ (次サイクルで再確認)
```

---

## 全体フロー

```
マーケットスキャン (最大10件/サイクル)
    │
    ├─ 流動性・価格範囲・期限フィルター
    │
    ▼
LLM + Ensemble 分析
    │  ├─ LLM (Claude Haiku): 確率・信頼度・スポーツ判定・相関判定
    │  ├─ Orderflow: 板情報・約定履歴
    │  └─ Bayesian 統合: 各シグナルを重み付け合成
    │
    ├─ edge < ±5% or confidence < 50% → スキップ
    ├─ スポーツ市場 (キーワード or LLM判定) → スキップ
    ├─ 相関ポジション (LLM: is_correlated=true) → スキップ
    │
    ▼
Audit チェック → confidence penalty
    │
    ▼
Quarter Kelly サイジング
    │
    ▼
GTC BUY 発注 → 約定待ち (order_filled=False)
    │
    ▼ 約定確認 (_check_pending_gtc_orders)
    │
    ▼ FILLED → open position

━━━━━━━━ 保有中 (毎分チェック) ━━━━━━━━

    ├─ [1] 確率崩壊?             → 直接クローズ (<$2) / GTC SELL
    ├─ [2] 近解決 × 含み損?      → GTC SELL
    ├─ [3] エッジ消失? (14日制約なし) → GTC SELL
    ├─ [4] 価格+40%? (14日超のみ) → GTC SELL
    ├─ [4] LLM逆転?              → GTC SELL
    ├─ [5] 含み損-80%?           → GTC SELL
    └─ マーケット解決             → 自動 PnL 確定
```

---

## 設定値一覧 (OrchestratorConfig)

```python
# エントリー
min_edge: float = 0.05           # 最小エッジ ±5%
min_confidence: float = 0.50     # 最小信頼度 50%
min_liquidity: float = 5_000     # 最低流動性 $5k
min_volume: float = 10_000       # 最低出来高 $10k
max_position_pct: float = 0.10   # 1ポジション最大 10%

# クローズ
take_profit_pct: float = 0.40             # 価格ベース利確 +40%
take_profit_min_days: int = 14            # 価格ベース利確は残り14日超のみ
edge_take_profit_threshold: float = 0.05  # エッジ消失利確 <5% (14日制約なし)
stop_loss_pct: float = -0.80              # 価格ベース損切り -80%
collapse_threshold: float = 0.88          # 確率崩壊閾値 88%
stop_loss_near_expiry_days: int = 7       # 近解決損切り: 残りN日
stop_loss_near_expiry_pct: float = -0.40  # 近解決損切り: 含み損閾値 -40%
```

---

## 設計思想

- **エッジベース**: 「価格が動いたか」ではなく「自分の確率推定 vs 市場価格の乖離」が本質
- **GTC 指値**: 相手がいないと約定しない。残存価値 < $2 は直接クローズ
- **二値解決**: 市場は最終的に 0 か 1 に解決する。損切りは「thesis が崩壊したとき」であって「価格が動いたとき」ではない
- **LLM 自己学習**: 過去の勝敗実績・カテゴリ別精度・直近外れパターンをフィードバック context として毎分析に注入
- **相関防止**: 保有ポジション一覧を LLM に渡し、同一イベントへの矛盾したポジションを排除
