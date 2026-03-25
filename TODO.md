# Poly AI Trader - TODO

コード変更の都度更新すること。compact後の文脈復元にも使う。

---

## 直近の作業履歴

| コミット | 内容 |
|---|---|
| `676deba` | fix: pending_sell チェックが BUY未約定なしで早期リターンするバグを修正 |
| `prev` | fix: pending_sell get_order失敗時にトークン残高で約定確認 (fallback) |
| `prev` | fix: edge_take_profit を14日制約から除外 (reason分離: take_profit / edge_take_profit) |
| `prev` | fix: 残存価値$2未満ポジションを直接クローズ (CLOB GTC売りループ防止) |
| `prev` | feat: ㉔ LLM相関ポジション検出実装 — is_correlated フラグ + 新規エントリースキップ |
| `prev` | feat: ㉓ LLMへのパフォーマンスフィードバック実装 (自己学習コンテキスト注入) |
| `prev` | feat: ㉒ 利確再設計 — エッジ消失利確(entry_edge + _last_signals キャッシュ) |
| `prev` | feat: ㉑ 損切りロジック再設計 — 確率崩壊ストップ(88%) + 近解決×含み損(-40%/7日) |
| `prev` | fix: exit_signals ループの堅牢性改善 (needs_manual_sale スキップ + 各イテレーションのtry/except) |
| `18c9536` | fix: GTC売り注文を即CLOSEDにせずPENDING_SELL状態で約定確認後にCLOSED |
| `5093cf3` | feat: 手動売却アラートの解除ボタン実装 (2クリック確認 + dismiss_manual_sale API) |
| `0838cf6` | feat: LLMにスポーツ市場判定 (is_sport) を追加し二重チェックを実装 |
| `7a3bf11` | feat: positions_loop に判断結果ログを追加 (PENDING継続/HOLD継続/サイクルサマリ) |
| `332cc76` | perf: ポジション更新ループを5分→1分に短縮 (PnL更新頻度改善) |
| `4a058dc` | refactor: ダッシュボードをトリガー廃止後の仕様に再構成 (Pending tile / LLM Calibration パネル) |
| `837200a` | feat: スポーツ系マーケットのトレードをスキップ (Brier記録は継続) |
| `ebc923a` | fix: LLM skill未計測期間 (20件未満) を半Kelly運用に変更 |
| `95c44f6` | fix: CoinGecko → Binance Public API に切り替え (APIキー不要) |
| `b59a3a6` | fix: train_crypto_ml.py に CoinGecko BTC/ETH ヒストリカル価格取得を追加 |
| `43e9c91` | feat: backtest.py に CryptoMLAnalyst 対応を追加 |
| `112660d` | feat: Crypto専用MLモデル設計・実装 (CryptoFeatures 36特徴量 + 学習スクリプト) |
| `2e8d41c` | feat: MLをデフォルト無効化 (LLMのみ運用、--use-ml で再有効化可) |
| `5cba375` | feat: Brier Score / LLM skill_score フィードバックループ実装 |
| `6fdd155` | feat: ポジション更新を分析ループから独立 (30秒ごと、_positions_loop) |
| `8318853` | fix: GTC約定誤検出を修正 - order取得失敗時はスキップ (None→filled 誤判定廃止) |
| `09ae87b` | design: Closed Positions パネルを Active 側に合わせてリデザイン |
| `7deb154` | fix: 解決済み判定を closed=True + last_trade_price に切り替え |
| `a0bf808` | debug: get_market / get_market_resolution に詳細ログ追加 (調査中) |
| `a02b449` | fix: get_market を CLOB API /markets/{conditionId} に切り替え |
| `83fafc7` | fix: 自動解決ロジックを明確な勝敗のみに限定 (outcomePrices=[0,0] は無視) |
| `4567d77` | fix: orderbook 404 のポジションのみ解決判定 (active=True マーケット誤クローズ修正) |
| `028355e` | fix: outcomePrices=[0,0] のVOIDマーケットを正しくクローズ |
| `6002274` | fix: active=True マーケットを解決済み判定から除外 (一時的対応、後続で改善) |
| `ccd8657` | feat: 解決済みマーケットの自動クローズ実装 (PolyClient.get_market_resolution追加) |
| `184e624` | fix: get_market を conditionId クエリパラメータで取得するよう修正 |
| `7c0e5c4` | feat: Closed Positions をダッシュボードに表示 (WIN/LOSS/VOID バッジ・累計PnL) |
| `9799d69` | fix: orderbook 404 エラーの静音化 + 警告を1回のみ表示 |
| `506c233` | fix: 旧レコードの誤格納NOトークンをヒューリスティックで検出・反転 |
| `6b99222` | fix: Position に yes_token_id 追加でスキャン外現在価格を正確に取得 |
| `588e3b1` | fix: ANTHROPIC_API_KEY を CLI サブプロセス env から除外 (Invalid API key 修正) |
| `d85e40b` | fix: BUY_YES trigger に YES token を正しく割り当て (大文字小文字不一致バグ) |
| `e46993a` | feat: LLM判断ログ表示 + トリガー時キャッシュ + 再分析時に前回判断をコンテキスト追加 |
| `dcce1ee` | feat: backtest --use-llm 時にニュース取得を追加 (orchestrator と同じ動作) |
| `f7147ca` | feat: backtest LLMシグナルのログ表示追加 (prob/conf/reasoning) |
| `07cfb25` | fix: Claude CLI コマンド修正 (-p引数渡し/--dangerously-skip-permissions/--output-format json) |
| `9bfc5eb` | refactor: LLM呼び出しをlitellm→Claude Code CLIサブプロセスに移行 (ANTHROPIC_API_KEY不要化) |
| `b7c33e1` | fix: ダッシュボードメモリリーク2件修正 (JS setInterval重複 + Python ゾンビWS接続) |
| `e4f376e` | fix: ポートフォリオ集計からPENDINGポジションを除外 (未約定GTC注文の phantom PnL修正) |
| `fb17676` | feat: ポートフォリオ表示追加 (Portfolio/Unrealized PnL/Exposure を stats bar に) |
| `c86751c` | fix: GTC約定検出の改善 (get_orders()不在検出 + None=約定済み + FILLED対応) |
| `01d390f` | fix: BUY_NO entry_price が NO価格で保存されPnL計算が壊れるバグ修正 |
| `f10f6bd` | fix: ポジション含み損益がスキャン外マーケットで$0になるバグ修正 (CLOB midpoint直接取得) |
| `347aed2` | feat: ダッシュボード完全リデザイン "Operator Terminal" + GTC Pending/Active 分離表示 |
| `913776f` | fix: 再起動時に既存ポジションをRiskManagerに復元 (エクスポージャー誤認防止) |
| `685cc91` | fix: エクスポージャースキップを can_add_position ベースに変更 |
| `c5b4090` | fix: エクスポージャー上限時にLLM分析をスキップ (コスト削減) |
| `0540b28` | feat: GTC未約定注文の自動キャンセル機能実装 (60分超でキャンセル+ポジション削除) |
| `07916ff` | fix: サイクルごとにCLOB残高を再取得してRiskManagerに反映 |
| `13022e3` | fix: FOK→GTC + BUY_NO異常検知ログ修正 (live_price vs expected比較に修正) |
| `f309fc7` | fix: allowance表示を allowances辞書から取得するよう修正 (allowance=∞表示) |
| `a7eb267` | fix: update_balance_allowance → get の順で呼び出し (allowance同期+正確なログ) |
| `50304a2` | fix: 接続ログを get_balance_allowance に修正 (実残高表示) |
| (最新) | fix: ensemble アクション閾値0.10→0 (HOLDバグ修正、BUY_YES/BUY_NO正常化) |
| | fix: run デフォルト最大マーケット数 10→50 |
| | fix: _analyze_market スキップ理由ログ追加 |
| | fix: near_resolution誤検知修正 (end_date過去→スキップ + market_idフィールド名修正) |
| | refactor: スキャナーをキーワード検索→全件取得+フィルタリング方式に変更 |
| | fix: main.py CLIデフォルト修正 (model→sonnet-4-6, min-edge→0.05) |
| | fix: LLM JSON解析エラー対策 (_parse_llm_json で正規表現フォールバック追加) |
| | fix: LightGBM 正則化パラメータ追加 (num_leaves/reg/min_child_samples) |
| | feat: ニュース取得をDDG+Scrapling本文フェッチに刷新 |
| | chore: min_edge 0.10→0.05、min_confidence 0.60→0.50 をデフォルトに変更 |
| `dafcd85` | fix: Action.value大文字小文字不一致によるトリガー誤発火・エッジ再検証スキップ修正 |
| `be459ab` | fix: CLOB価格異常検出(0.20超乖離フォールバック) + エッジ再検証ログ強化 |
| `465db87` | chore: requirements.txt scikit-learn追加 + TODO.md更新 |
| `a77478c` | fix: ML学習データ lookahead bias修正 + マーケット取得ロジック統一 |
| `d012a76` | fix: バックテスト マーケット取得ロジック全面修正 |
| `406f552` | fix: バックテスト マーケット取得が0件のまま無限ループする問題を修正 |
| `1049ba2` | fix: BUY_NO価格逆転バグ修正 (NOトークンask→YES換算) |
| `51fc0af` | fix: CLOB残高取得 + FOK注文 + ask/bid実価格取得 |
| `7bedd32` | fix: Whale動的閾値 + executor RiskManager二重計算修正 |
| `97bffae` | fix: トリガー発火時エッジ再検証 + exit後の再エントリー修正 |
| `1a2fa78` | feat: Open Positions パネルのデザインを刷新 |
| `f2d743e` | feat: ダッシュボード Open Positions パネル追加 |
| `6b23e62` | fix: ML再学習 volume データ修正 + Gamma API 直接取得 |
| `4b2fdbd` | feat: エンドツーエンドバックテスト基盤実装 |
| `aa70b41` | 設計レベル2件修正: ML独立化 + 構造化ログ |
| `fdf5dc4` | トレードロジック 高・中バグ8件修正 |
| `c343fc6` | 深刻度「中」バグ4件修正 (Auditor/タイムゾーン等) |
| `ebc5957` | README・ROADMAP 全面更新 |
| `9a7a8e8` | ML自動再学習 + ホットスワップ実装 |
| `a4f6ef8` | 学習層 (Factor Manager) の機能不全修正 |
| `48501f7` | ドキュメント齟齬修正 + バグ修正 |

---

## ✅ 解決済み: GTC未約定注文の放置問題

GTC注文は約定するまでオーダーブックに残り続けるため、放置すると古い注文が溜まる。

**対応:** 各サイクルで CLOB の注文ステータスを確認し、60分超の未約定注文を自動キャンセル。
- Position に `order_id` / `order_filled` フィールドを追加
- `_check_pending_gtc_orders()` を各サイクルで実行
- MATCHED → mark_order_filled / CANCELLED → ポジション削除 / LIVE+60分超 → 自動キャンセル

**既存ポジション（実装前に記録されたもの）:** `order_filled=True`（デフォルト）で読み込まれ自動キャンセル対象外。マーケット解決時に通常通り処理される。

---

## ✅ 解決済み: 本番注文 FOK失敗

本番live初回トリガー発火時に FOK orders are fully filled or killed が3回連続で出た。

**原因:** FOK注文は全量即時約定できないとKillされる。Polymarketは流動性が薄いマーケットも多く、FOKでは約定できないケースが多い。

**対応:** `client/polymarket.py` の `buy()`/`sell()` デフォルトを FOK→GTC に変更。GTC指値でオーダーブックに積み、流動性が来た時点で約定。

---

## ✅ 解決済み: 接続時 allowance=$0.00 誤表示

`update_balance_allowance` は None を返すため残高表示が $0.00 になっていた。
`get_balance_allowance` で実際の値を取得。レスポンスのキーは `allowances`（複数辞書）だったため `allowance`（単数）で取得できていなかった。
対応後: `balance=$61.04 allowance=∞` と正しく表示。

---

## ✅ 解決済み: SIGNATURE_TYPE 設定確認

Polymarketをメールログイン(Magic Link)で使っているが、POLY_SIGNATURE_TYPE=2 + MetaMaskの秘密鍵が正解。
Magic Linkの鍵(reveal.magic.link)は別アドレス(0x345F...)で残高なし。
`POLY_FUNDER_ADDRESS=0x322a...`(Polymarket proxy) + `POLY_PRIVATE_KEY=MetaMask鍵` + `SIGNATURE_TYPE=2` が正しい設定。

---

## ✅ 解決済み: 本番注文失敗

live初回起動時に `❌ 失敗: 注文失敗 (3回試行)` が出た。失敗理由が握りつぶされていたため原因不明。

**対応済み:** `executor/trade_executor.py` に失敗理由ログ追加 (`⚠️ 試行N 失敗: {message}`)

**原因:** `size = amount / price` の小数点桁数オーバー (maker: 2桁, taker: 4桁制限)
**対応:** `client/polymarket.py` で `amount=round(2)`, `size=round(4)` に修正済み

---

## ✅ 解決済み: 自動解決 (market resolution)

### 最終実装

- CLOB API `GET /markets/{conditionId}` で `closed` フィールドを確認
- `closed=True` かつ orderbook 404 → マーケット終了とみなす
- `get_last_trade_price(token_id)` でトークン最終取引価格を取得して勝敗判定
  - BUY_NO: `resolution = 1.0 - no_token_price`
  - BUY_YES: `resolution = yes_token_price`
- Miami Open (buy_no, NO token last_price=0.001) → resolution=0.999 → YES勝ち → PnL $-1.77 で正常クローズ確認済み

### 調査過程で判明したこと

- Gamma API `conditionId` クエリフィルタは**無視される** (別マーケットを返す)
- CLOB `/markets/{conditionId}` は8フィールドのみ (`outcomePrices`/`resolutionResult` なし)
- `active=True` は未解決を意味しない (Miami Open も `active=True` だった)
- `closed=True` + orderbook 404 の組み合わせが最も信頼できる終了シグナル

---

## 未対応バグ・懸念点

### 高優先度

- [ ] **㉛ Brier Tracker の記録スコープが間違っている（skill score が実取引精度を反映しない）**

  ### 症状
  ```
  Skill score (全体・現在):       -9.76%
  Skill score (非取引 edge<5%):   -1.74%  ← 32件中26件がこれ
  Skill score (実取引 edge>=5%):  -37.45% ← 本当の姿
  Win rate 全体: 40.6% / 実取引のみ: 33.3%
  ```

  ### 原因
  `record_prediction()` が `analyze()` 直後（edge/スポーツ/Audit フィルターの前）に呼ばれている。
  Brier log に以下が混入:
  1. edge < min_edge 予測 (32件中26件 = 81%) → 実際には取引しない
  2. スポーツ市場の予測 → "Brier記録のみ" と意図的にしていたが誤り
  3. Audit 失敗の予測 → 取引しない

  skill score は「取引判断のゲート」なのに 9 割が「取引しない予測」で構成され、
  実取引精度が完全に希釈されている。

  ### 修正方針
  `record_prediction()` を **全フィルター通過後** (confidence チェック通過直後) に移動。
  スポーツコメントも "Brier記録のみ" → "トレード対象外" に修正。
  brier_log.json をリセット（混入データが残ると skill score が不正確なまま）。

  ### 実装箇所
  - `runner/orchestrator.py`: `record_prediction()` 呼び出し位置を移動、スポーツコメント修正
  - `data/brier_log.json`: リセット

- [ ] **㉚ GTC約定時に entry_price / size が実約定データで更新されない**

  ### 症状
  ```
  UI:         BUY_NO entry=42.3¢, size=$5.12, PnL=-2.7%
  Polymarket: cost=$12.26, 46.07 tokens @ 26.6¢, PnL=+54.65%
  ログ:       sell size補正: $5.12 → $19.30 (実残高46.07 tokens)
  ```
  ダッシュボードの entry_price / size / PnL が Polymarket と大幅に乖離。

  ### 原因
  GTC注文の約定確認時 (`_check_pending_gtc_orders`) で `mark_order_filled(pos.id)` を呼ぶが、
  これは **`order_filled=True` フラグを立てるだけ** で、実約定データを反映しない。

  ```python
  # 現在: フラグのみ更新
  def mark_order_filled(self, pos_id):
      self.positions[pos_id].order_filled = True
      self._save()
  ```

  GTC注文は発注時の指値と異なる価格で部分/全約定するため:
  - `entry_price`: 発注時の市場価格のまま → 実約定価格と乖離
  - `size`: 発注時のUSDC額のまま → 実約定額と乖離
  - PnL計算: 間違った entry_price/size で計算 → 全く信用できない

  ### 修正方針

  **A. `mark_order_filled` に実約定データを渡す**

  CLOB API `get_order(order_id)` のレスポンスから約定情報を取得:
  - `size_matched`: 約定トークン数 (文字列)
  - `price`: 注文価格 (トークンネイティブ単位, 文字列)
  - `original_size`: 発注トークン数 (文字列)

  実約定額 = `float(size_matched) * float(price)`

  **B. `position_tracker.py` に `update_fill_data()` を追加**

  ```python
  def update_fill_data(self, pos_id: str, fill_price: float, fill_size: float):
      """GTC約定後に実約定データで更新"""
      pos = self.positions.get(pos_id)
      if not pos:
          return
      pos.entry_price = fill_price  # YES価格ベース
      pos.size = fill_size          # USDC額
      pos.order_filled = True
      self._save()
  ```

  **C. `_check_pending_gtc_orders` で約定情報を取得して渡す**

  ```python
  if status in ("MATCHED", "FILLED"):
      # 実約定データで entry_price / size を更新
      fill_price_raw = float(order.get("price", 0))
      size_matched = float(order.get("size_matched", 0))
      if fill_price_raw > 0 and size_matched > 0:
          fill_size = size_matched * fill_price_raw  # USDC額
          # BUY_NO: price はNOトークン価格 → YES価格に変換
          if "NO" in pos.side.upper():
              fill_price_yes = 1.0 - fill_price_raw
          else:
              fill_price_yes = fill_price_raw
          self.position_tracker.update_fill_data(pos.id, fill_price_yes, fill_size)
      else:
          self.position_tracker.mark_order_filled(pos.id)  # フォールバック
  ```

  ### 注意点
  - `price` はトークンネイティブ単位 (BUY_NO なら NO価格)
  - `size_matched` はトークン数 (USDC額ではない)
  - 実USDC額 = `size_matched * price`
  - BUY_NO の場合 entry_price は YES 価格に変換して保存 (既存の計算ロジックとの互換性)
  - RiskManager の open_positions["amount"] も実約定額で更新すべき

  ### 実装箇所
  - `tracker/position_tracker.py`: `update_fill_data()` 追加
  - `runner/orchestrator.py`: `_check_pending_gtc_orders()` 内の MATCHED/FILLED 分岐 (2箇所)

- [ ] **㉙ Brier Tracker の Win/Loss 判定が実トレード方向と不一致** — 対応済み (`df6a2e9`)

  ### 症状
  ダッシュボードの Win Rate が実際のトレード勝率と合わない。

  ### 原因
  `brier_tracker.py` `get_stats()` (L130-133) の win/loss 判定:
  ```python
  # 現在のロジック: 確率0.5基準の「方向当て」
  pred_yes = r["llm_prob"] >= 0.5
  actual_yes = r["outcome"] >= 0.5
  if pred_yes == actual_yes:
      wins += 1
  ```

  これは「LLMがYES寄りの確率を出して実際YESだったか」を見ているだけ。
  実際のトレードでは **edge方向 (llm_prob vs market_price)** で BUY_YES/BUY_NO を決めるので、
  win/loss は以下であるべき:

  ```
  例1: market=0.70, llm=0.80 → BUY_YES → outcome=YES(1.0) → WIN ✓
  例2: market=0.70, llm=0.60 → BUY_NO  → outcome=YES(1.0) → LOSS ✗
  例3: market=0.70, llm=0.60 → BUY_NO  → outcome=NO(0.0)  → WIN ✓
  ```

  現在のロジックでは例2を「llm=0.60 → pred_yes=True → actual_yes=True → WIN」と誤判定する。

  ### 修正方針
  edge 方向 = `llm_prob > market_price` (YES方向) or `llm_prob < market_price` (NO方向) で判定:
  ```python
  bought_yes = r["llm_prob"] > r["market_price"]
  actual_yes = r["outcome"] >= 0.5
  if bought_yes == actual_yes:
      wins += 1
  else:
      losses += 1
  ```

  ### 影響範囲
  - `get_stats()` の wins/losses のみ（ダッシュボード表示用）
  - **Brier Score, skill_score の計算には影響なし**（これらは確率値ベースで正しく算出されている）

  ### 実装箇所
  - `tracker/brier_tracker.py` `get_stats()` L129-135

- [x] **㉘ ダッシュボード Portfolio 表示が Polymarket と $41 乖離** — 対応済み (`1e3f9cc`)

  ### 症状
  ```
  Polymarket: Portfolio $443.90
  UI:         Portfolio $402.82 (balance + positions)
  差額: $41.08
  ```

  ### 原因分析

  **① 計算式が間接的で誤差が蓄積しやすい**

  現在の計算 (`_push_positions_to_dashboard`, L1845):
  ```python
  portfolio = current_balance + total_exposure + total_unrealized
  #         = USDC残高      + ポジション原価  + 含み損益
  ```

  数学的には `原価 + 含み損益 = 時価` なので Polymarket と一致するはずだが、
  以下のケースで乖離が発生する:

  - `current_prices.get(pos.market_id, pos.entry_price)` で価格取得失敗時に
    entry_price にフォールバック → unrealized_pnl=0 → 時価が原価扱いになる
  - `needs_manual_sale=true` のポジション (`8dd075a6`, Denmark選挙, $8.62) が
    `status=closed` で UI 計算から除外されているが、Polymarket 上はトークンが残っている
    → Polymarket は時価に含むが UI は含まない

  **② needs_manual_sale のトークン残存**

  `8dd075a6` (Mette Frederiksen / Denmark):
  - `status: closed`, `needs_manual_sale: true`, `pnl: -0.93`
  - UI は closed なのでポートフォリオ計算から除外
  - Polymarket 上でトークンが未売却のまま残っている場合、
    Polymarket の portfolio にはその時価が含まれる → 差額の主因

  ### 修正方針

  **A. Portfolio 計算をシンプル化 (本質的な修正)**

  間接計算 (`原価 + 含み損益`) を廃止し、Polymarket と同じ計算に統一:
  ```python
  # 変更後:
  # portfolio = USDC残高 + Σ(ポジション時価)
  # ポジション時価 = トークン数 × 現在価格

  total_market_value = 0.0
  for p in filled_data:
      size = p["size"]              # エントリーコスト (USDC)
      entry = p["entry_price"]      # YES価格
      current = p["current_price"]  # 現在のYES価格
      side = p["side"].upper()

      if "NO" in side:
          # BUY_NO: entry_price はYES価格で保存されている
          entry_no = 1.0 - entry
          current_no = 1.0 - current
          tokens = size / entry_no
          market_value = tokens * current_no
      else:
          # BUY_YES
          tokens = size / entry
          market_value = tokens * current
      total_market_value += market_value

  portfolio = current_balance + total_market_value
  ```

  **B. needs_manual_sale ポジションの扱い**

  `needs_manual_sale=true` かつ `status=closed` のポジションは、
  CLOB でトークンが残存している可能性がある。
  これらを portfolio 計算に含める (もしくは status を open に戻す) べき。

  → 対応: closed でも `needs_manual_sale=true` のポジションは
    `open_positions` と同様に時価計算に含める。

  ### 実装箇所
  - `runner/orchestrator.py` `_push_positions_to_dashboard()` L1841-1848

- [x] **㉕ pending_sell タイムアウト判定が pos.created_at を使っており古いポジションが即キャンセルループする** — 対応済み

  ### 症状
  ```
  ↩️ 売り注文タイムアウトキャンセル (1980分) → ACTIVE復帰: Will Russia capture Kostyantynivka...
  ```
  毎チェック(5分)ごとに売り注文発注 → 即キャンセル → 再発注 を繰り返す。

  ### 原因
  `_check_pending_gtc_orders()` のタイムアウト判定が `pos.created_at`（ポジション作成時刻）を使っていた。
  ポジションが古いほど売り注文を出した直後に 60分超と判定されてキャンセルされる。

  ### 修正
  - `Position` に `pending_sell_placed_at: Optional[datetime]` フィールドを追加
  - `mark_pending_sell()` 呼び出し時に `datetime.now(timezone.utc)` をセット
  - `cancel_pending_sell()` でリセット
  - タイムアウト判定を `pending_sell_placed_at or pos.created_at` に変更（既存ポジション互換）

- [x] **㉖ pending_sell の get_order 失敗時に resolved マーケットを検出できず、分析ループまで待つ必要がある** — 対応済み

  ### 症状
  ```
  ⚠️ get_order失敗・残高確認不可 → スキップ: US escorts commercial ship through Hormu
  ```
  `get_order()` が None → `get_token_balance()` が None → スキップ → positions_loop では永遠に閉じられない。
  `_check_resolved_markets()` は分析ループ（最大数時間間隔）でしか動かないため、その間ずっと OPEN のまま。

  ### 原因
  フォールバックが2段しかない:
  1. `get_order(order_id)` → None
  2. `get_token_balance(token_id)` → None
  3. (なし) → スキップ

  マーケットが解決済みの場合、CLOB 注文は自動消滅・トークン残高 API も動かないため、両方 None になる。

  ### 修正方針
  3段目のフォールバックとして、`get_market(market_id)` で `closed=True` を検出した場合:
  - `cancel_pending_sell(pos.id)` で pending_sell をクリア → ACTIVE 復帰
  - `_check_resolved_markets()` が次のサイクル (positions_loop は5分) で解決処理を実行

  ```python
  # get_order 失敗 → get_token_balance 失敗 → 3段目: マーケット解決チェック
  market_data = client.get_market(pos.market_id)
  if market_data and market_data.get("closed"):
      self.position_tracker.cancel_pending_sell(pos.id)
      print(f"   🏁 市場解決済み → pending_sell クリア (resolve待ち): {pos.question[:40]}")
  else:
      print(f"   ⚠️ get_order失敗・残高確認不可 → スキップ: {pos.question[:40]}")
      continue
  ```

  ### 実装箇所
  `runner/orchestrator.py` `_check_pending_gtc_orders()` の sell セクション fallback 内

- [x] **⑯ PENDING経過時間がマイナスになり60分タイムアウトが永遠に発動しない** — 対応済み (`3543e04`)

  ### 症状
  ```
  ⏳ PENDING継続 (-539分経過 / 60分でキャンセル): Will Israel strike...
  ```
  -539分 ≈ -9時間 = JST と UTC の差そのもの。

  ### 原因
  - `Position.created_at` のデフォルトは `datetime.now()` → **ナイーブなローカル時刻 (JST)**
  - `position_tracker.py` の `from_dict` でも `datetime.fromisoformat(...)` → ナイーブで復元
  - `_check_pending_gtc_orders` 内: `now = datetime.now(timezone.utc)` → **UTC aware**
  - ナイーブ datetime を `created.replace(tzinfo=timezone.utc)` で UTC として扱う
    → JST 時刻を UTC だと誤認 → `created` が9時間先になる → elapsed がマイナス
  - 60分タイムアウトが永遠に発動せず、古いGTC注文が蓄積し続ける

  ### 修正方針
  **① `tracker/position_tracker.py`**
  - `created_at: datetime = field(default_factory=datetime.now)`
    → `field(default_factory=lambda: datetime.now(timezone.utc))` に変更
  - `from_dict` の `datetime.fromisoformat(data["created_at"])` はそのままで良い
    (UTC aware な isoformat で保存されれば正しく復元される)

  **② `runner/orchestrator.py` — `_check_pending_gtc_orders()`**
  - 既存ポジション (ファイルに保存済みのナイーブ datetime) との互換性のため:
    `if created.tzinfo is None: created = created.astimezone(timezone.utc)`
    (`.replace()` ではなく `.astimezone()` で正しくローカル→UTC変換)

- [x] **⑰ `_check_position_exits` で `_last_markets` にないポジションの PnL が 0% になる** — 対応済み (`3543e04`)

  ### 症状
  ```
  ⏸️ HOLD: Will Solana reach $100 in March? (pnl=+0.0%)
  ```
  スキャン対象外のマーケットを持つポジションの含み損益が常に0%。

  ### 原因
  - `_check_position_exits` は `current_prices` を `self._last_markets` から構築
  - `_last_markets` に含まれないマーケット（古いポジション・スキャン範囲外）は
    `current_prices.get(pos.market_id, pos.entry_price)` でエントリー価格にフォールバック
  - `get_unrealized_pnl_pct(entry_price)` = 0% → 利確・損切り判定が正しく機能しない
  - `_push_positions_to_dashboard` は `_pc.get_midpoint(pos.yes_token_id)` で直接CLOB取得して正しく表示

  ### 修正方針
  **`runner/orchestrator.py` — `_check_position_exits()`**
  - `current_prices` を `_last_markets` から構築した後、
    ACTIVE ポジションで `market_id` が `current_prices` にないものを CLOB midpoint で補完
  ```python
  from client import PolyClient
  _pc = PolyClient()
  for pos in open_positions:
      if pos.order_filled and pos.market_id not in current_prices:
          tok = pos.yes_token_id or pos.token_id
          mid = _pc.get_midpoint(tok)
          if mid is not None:
              current_prices[pos.market_id] = mid
  ```

- [ ] **⑮ Brier Score の解決チェックがポジションありのマーケットのみ対象になっている**

  ### 問題
  - `brier_log.json` への予測記録は **約定関係なく全分析マーケット** に対して実施
  - しかし解決チェック (`_check_resolved_markets`) は
    `position_tracker.get_open_market_ids()` = **ポジションを持つマーケットのみ** を対象
  - 結果: 「予測は記録したが買わなかった」マーケットの `outcome` が永遠に `null` のまま
  - Brier Score の 20 件サンプルがなかなか溜まらない

  ### 修正方針
  **① `tracker/brier_tracker.py`**
  - `get_unresolved_market_ids() → List[str]` を追加
    - `outcome=None` のエントリの `market_id` 一覧を返す

  **② `runner/orchestrator.py` — `_check_resolved_markets()`**
  - チェック対象を「ポジションあり」だけでなく
    「brier_tracker に未解決予測がある market_id」も含める
  - ポジションなしマーケットは PnL 確定は不要、`brier_tracker.record_outcome()` だけ呼ぶ
  - CLOB `get_market(market_id)` + `get_last_trade_price()` で解決判定は同じロジック
  - ただしポジションなしマーケットは `token_id` が brier_log に保存されていないため、
    Gamma API で `conditionId → yes_token_id` を逆引きする必要あり

  ### 注意
  - brier_log の `market_id` は `conditionId` 形式で保存されているはず
  - Gamma API: `GET /markets?conditionId={id}` で token_id を取得可能
  - ポジションありマーケットは従来通り PnL 確定まで実施 (変更なし)

- [x] **⑭ LLM と ML の方向対立時に誤トレードが発生する** (`analyst/ensemble.py`) — 対応済み
  - **問題:** LLM が「割高 (市場価格より低い予測)」、ML が「割安 (市場価格より高い予測)」と真逆の方向を示すとき、
    Bayesian 集計で中間値が出て BUY/SELL シグナルが発生する。
    実際には「どちらが正しいか不明」= エッジなし の局面なのにトレードしてしまう。
  - **根本原因:** 確率の 0/1 方向が割れている時点で、数値を平均化しても意味がない。
    LLM=12%・ML=35%・市場=16% → LLM は「売り方向」、ML は「買い方向」で相殺。
    混ぜた結果の中間値は「どちらの根拠もない数字」にすぎない。
  - **対策:** `ensemble.py` の `analyze()` 内で LLM・ML 両方が揃っている場合のみ方向チェックを実施。
    `llm_bullish = llm_prob > market_price`、`ml_bullish = ml_prob > market_price` が不一致なら
    シグナルを **HOLD / no_signal** として返す (confidence を 0 にして Bayesian 閾値を下回らせる)。
  - **注意:** ML が未ロードの場合は LLM のみで判断 (チェックなし)。
  - **実装場所:** `analyst/ensemble.py` `analyze()` ML シグナル処理後

- [x] **⑫ 発火時のエッジ再検証なし** (`runner/orchestrator.py` `_execute_trigger`) — 対応済み
  - シグナル生成 → トリガー発火まで数時間経過し、相場が動いてエッジが消えても約定していた
  - 対策: `TriggerCondition` に `signal_probability` を追加。発火時に現在価格と比較し、エッジが `min_edge × 0.5` 未満なら `trigger_cancelled` ログを出してキャンセル

- [x] **⑬ exit後の再エントリー不可** (`runner/orchestrator.py` `executed_markets`) — 対応済み
  - take-profit/stop-loss でポジションをクローズ後も `executed_markets` に残り続け、同マーケットへの再エントリーが永久にブロックされていた
  - 対策: `_check_position_exits()` で `close_position()` 成功時に `executed_markets` から当該 `market_id` を削除

### 低優先度

- [x] **⑩ Whale閾値の絶対値固定** (`analyst/orderflow.py`) — 対応済み
  - `whale_threshold_usd = $10,000` ハードコードで、流動性の小さいマーケットでは全トレードがwhale判定される問題
  - 対策: `detect_whales()` 内でウィンドウ内総取引量の1%を動的閾値として計算、`max(絶対下限, 総取引量×1%)` でフロアを保持

- [x] **⑪ ポジションサイズの二重計算・上書きバグ** (`runner/orchestrator.py`) — 対応済み
  - オーケストレーターが Kelly 計算した `size` を `executor.execute_order()` に渡しても、
    `TradeExecutor` 内の RiskManager がダミー値 (edge=0.1, confidence=0.8) で再計算し上書きしていた
  - 対策: `TradeExecutor(use_risk_manager=False)` に変更。リスク管理はオーケストレーターの `self.risk_manager` が一元担う

### 設計レベル

- [x] **Bayesian二重カウントの根本解決** — 対応済み
  - `llm_prediction` / `llm_confidence` を Features から削除 (28特徴量に)
  - ML は価格・ボリューム・オーダーブックのみで予測。LLM は Bayesian で独立シグナル
  - `generate_sample_data()` のラベル生成ロジックも LLM 依存を除去

- [x] **トリガー約定率・スリッページ監視** — 対応済み
  - `data/trade_log.jsonl` への構造化ログ実装
  - `signal_generated` / `trigger_set` / `trigger_fired` / `trigger_expired` / `market_resolved` を記録
  - `trigger_fired` にスリッページ (絶対値・%) と発火までの秒数を記録

---

## 🚀 本番切り替えチェックリスト (dry run → live)

```bash
# 1. dry run のポジション・ログをリセット
rm data/positions.json
rm data/trade_log.jsonl

# 2. .env を本番設定に変更
#    POLY_SIGNATURE_TYPE=2
#    POLY_PRIVATE_KEY=0x...  (プロキシウォレットの秘密鍵)
#    POLY_PROXY_ADDRESS=...  (Polymarket UI のウォレットアドレス)

# 3. ML学習済みモデルがあることを確認
ls models/lgb_model.pkl

# 4. 本番起動
python main.py run --live
# ※ --enable-exit は不要 (Polymarketは解決まで持つのが基本戦略。
#    途中売却はスプレッド二重払い+流動性リスクあり)
```

> ⚠️ `data/positions.json` を消さずに `--live` にすると dry run のポジションが引き継がれ、
> 存在しないポジションのexit注文が出る可能性あり。

---

## 今後やりたいこと (バックログ)

- [ ] **㉜ LLMによるポジション定期レビュー（出口判断の脱ルールベース化）**

  ### 概要
  現在の出口ロジックはすべてルールベース（edge消失・価格+40%・損切り-80%等）。
  ポジション保有中にLLMが「今クローズすべきか？」を能動的に評価する仕組みを追加する。

  ### 動作イメージ
  ```
  _positions_loop()（毎分）
    ↓
  _llm_position_review() を追加呼び出し
    ↓
  FILLED かつ pending_sell なし のポジションを列挙
    ↓ ポジションごとに last_review から5分以上経過していれば
  LLM に問う:
    - question / side / entry_price / current_price / PnL% / days_left
    - 直近ニュース (GoogleNewsFetcher、最大3件ヘッドライン)
    - 価格推移 (直近7日、_price_history_cache から)
    - エントリー時のthesis (_load_llm_judgment から)
  LLM出力: should_exit: bool / reason: str
    ↓ should_exit == true
  _exit_position(pos, "llm_review", current_price)
  ```

  ### LLMへの質問フォーマット
  ```
  あなたは保有ポジションの出口判断を行うトレーダーです。
  以下の情報をもとに、**今すぐクローズすべきか**を判断してください。

  [ポジション]
  問い: {question}
  方向: {side} (エントリー価格: {entry_price:.1%})
  現在: {current_price:.1%} (PnL: {pnl_pct:+.1%}, 残り{days_left:.0f}日)

  [エントリー時の根拠]
  {entry_thesis}

  [直近ニュース]
  {news_headlines}

  [価格推移 (直近7日)]
  {price_chart}

  JSON形式で回答:
  {"should_exit": true/false, "reason": "理由を1文で"}
  ```

  ### クールダウン管理
  - `_llm_review_cooldowns: Dict[str, datetime]` をオーケストレーターに追加
  - ポジションIDをキーに最終レビュー日時を保存
  - 5分未満のものはスキップ

  ### 実装箇所
  - `analyst/llm_analyst.py`: `review_position()` メソッド追加
    - 入力: question, side, entry_price, current_price, pnl_pct, days_left, entry_thesis, news, price_chart
    - 出力: `PositionReview(should_exit: bool, reason: str)`
  - `runner/orchestrator.py`:
    - `_llm_review_cooldowns: Dict[str, datetime]` 追加
    - `_llm_position_review()` メソッド追加
    - `_positions_loop()` 内で `await self._llm_position_review()` 呼び出し
    - OrchestratorConfig に `llm_review_interval_min: int = 5` 追加

  ### 注意点
  - ドライランでも LLM は呼ぶが `_exit_position()` は実行しない（ログのみ）
  - ポジション数が多い場合は並列呼び出し (asyncio.gather)
  - ニュース取得失敗時はニュースなしで続行（クラッシュしない）
  - エントリー時thesis が `_load_llm_judgment` で取れない場合は空文字

- [x] **MLを一時無効化してLLMのみで運用** — 対応済み (`2e8d41c`)

  ### 判断理由
  - 予測市場は価格テクニカル特徴量（ボリューム・オーダーブック）ではなくニュースイベントで動くため、
    LightGBMによる価格パターン学習は予測力を持ちにくい
  - 各マーケットが全く異なるトピック（スポーツ・政治・crypto）→ 特徴量の意味が市場ごとに変わり汎化しない
  - データが薄く過学習リスクが高い
  - 方向対立ガードでMLの悪影響はある程度防げているが、ノイズ増加・設計複雑化のコストが大きい
  - **方針: まずLLMのみで20件以上解決して実績を積む。その後MLが本当に必要か実データで判断する**

  ### 実装内容
  - `OrchestratorConfig` に `use_ml: bool = False` を追加（デフォルトOFF）
  - `EnsembleAnalyst` の `use_ml` を `False` で初期化
  - `main.py` に `--use-ml` フラグを追加（明示的に有効化したい場合用）
  - ML関連コード（`ml_analyst.py`, `train_ml.py`, `backtest.py`）は削除せず保持
  - ログに「ML無効 (LLMのみ運用中)」と表示

  ### 再有効化の条件
  - LLMのBrier skill_score が 20件以上の実績で確認できた後
  - MLを追加することで skill_score が改善するか検証してから判断

- [x] **ニュース取得の改善 (Scrapling + DDG検索)** — 対応済み
  - 現状: Google News RSSのタイトルだけをLLMに渡している (内容なし・クエリ精度低い)
  - 対策: DDG HTML検索で実記事URLを取得 → Scrapling Fetcherで本文フェッチ → LLMに本文渡す
  - キーワード抽出を汎用化 (固有名詞・大文字語・金額を抽出、crypto専用から脱却)
  - JSレンダリング必要なサイトはタイトルのみにフォールバック
  - 変更ファイル: `data_fetcher/news_fetcher.py`, `runner/orchestrator.py`, `requirements.txt`

- [x] **LLMキャリブレーション追跡 + Brier Scoreフィードバック** — 対応済み (`5cba375`)

  ### 背景・動機
  LLMの確率推定（例:「60%」）は実際に60%の確率で当たる保証がない（過大評価しやすい）。
  現状はLLMの推定を固定の強さでBayesian統合しているため、LLMが市場より劣っていても
  そのままKelly計算されて資金を溶かすリスクがある。
  Brier Scoreで実績を計測し、LLMの精度に応じてシグナル強度・Kellyを動的に調整する。

  ### Brier Score計算式
  ```
  brier_llm    = mean((llm_prob - outcome)²)    # LLMの精度
  brier_market = mean((market_price - outcome)²) # 市場ベースライン
  skill_score  = 1 - (brier_llm / brier_market)
    > 0  → LLMが市場より優れている（使う価値あり）
    = 0  → 互角（市場に勝てていない）
    < 0  → LLMが市場より劣っている（有害）
  ```

  ### 実装内容

  **① 新規モジュール: `tracker/brier_tracker.py`**
  - `record_prediction(market_id, llm_prob, market_price)` — シグナル生成時に記録
  - `record_outcome(market_id, outcome)` — マーケット解決時に記録
  - `get_skill_score(window=30) → float` — 直近N件のskill_score
  - データ永続化: `data/brier_log.json`
  - サンプル数 < 20 の間は skill_score = None（統計的に意味がないため）

  **② `analyst/bayesian.py` — LLMシグナルの動的減衰**
  ```python
  attenuation = clip(skill_score * 2, 0.0, 1.0)  # skill=0.5→100%, skill=0→0%
  effective_llm_prob = market_price + (llm_prob - market_price) * attenuation
  ```

  **③ `risk/risk_manager.py` — Kelly分率の動的調整** (`ebc923a` で更新)
  ```python
  if skill_score is None:  kelly_fraction = 0.125  # 未計測(20件未満) → 半Kelly
  elif skill_score > 0.10: kelly_fraction = 0.25   # 通常
  elif skill_score >= 0.0: kelly_fraction = 0.125  # 半分
  else:                    kelly_fraction = 0.0625 # 1/4（LLM有害期）
  ```
  - 起動時に即時適用 (orchestrator.__init__ で `update_llm_skill(get_skill_score())` を呼ぶ)

  **④ `runner/orchestrator.py` — 呼び出しポイント**
  - LLMシグナル生成後 → `brier_tracker.record_prediction()`
  - `_check_resolved_markets()` 解決後 → `brier_tracker.record_outcome()`
  - skill_score を Bayesian・RiskManager に渡す
  - skill_score < **-0.05** かつ サンプル数 >= 20 → LLMシグナルをブロック（HOLD返却）
    - 当初は `skill < 0` でブロックしていたが、-0.5% 程度のマイナスは市場とほぼ互角であり
      ブロックは厳しすぎるため、5%マージンを設けた

  **⑤ ダッシュボード表示**
  - stats bar に `LLM Skill` を追加（例: `+0.12` なら緑、`-0.05` なら赤）

- [x] **Crypto専用MLモデルの設計・実装** — 設計完了、学習待ち

  ### 実装内容

  **① `analyst/crypto_features.py`** — CryptoFeatures (36特徴量 = 28汎用 + 8crypto固有)
  - 追加8特徴量: `btc_return_1h`, `btc_return_24h`, `eth_return_24h`, `btc_eth_corr`,
    `market_btc_corr`, `btc_vol_regime`, `crypto_momentum_align`, `yes_price_distance`
  - `is_crypto_market(question)`: BTC/ETH/Solana等のキーワード判定
  - `CryptoFeatureExtractor`: 通常特徴量を内包し、BTC/ETHコンテキストを追加

  **② `analyst/crypto_ml_analyst.py`** — CryptoMLAnalyst (MLAnalystのサブクラス)
  - モデルパス: `models/lgb_crypto_model.pkl` (汎用モデルとは完全分離)
  - `predict_crypto()`: btc_change_24h/eth_change_24h を受け取り CryptoFeatures で予測
  - `is_available()`: モデルファイルの存在確認

  **③ `scripts/train_crypto_ml.py`** — Crypto専用学習スクリプト
  - Gamma API から `is_crypto_market()` フィルタで解決済みcryptoマーケットを収集
  - 36特徴量で LightGBM 学習 → `models/lgb_crypto_model.pkl` に保存
  ```bash
  python scripts/train_crypto_ml.py --days 365 --limit 300
  ```

  **④ `analyst/ensemble.py`** — 条件分岐ルーティング
  - crypto市場 + Crypto MLモデルあり → `CryptoMLAnalyst` を使用 (36特徴量)
  - 非crypto市場 + `--use-ml` → 汎用 `MLAnalyst` を使用 (28特徴量)
  - Crypto MLは `--use-ml` フラグ不要 (モデルがあれば自動適用)
  - 方向対立ガード: crypto ML / 汎用 ML 両方に適用

  ### 学習手順
  1. crypto解決済みマーケットが30件以上蓄積されるのを待つ
  2. `python scripts/train_crypto_ml.py --days 365 --min-volume 2000`
  3. `models/lgb_crypto_model.pkl` が生成されれば次回起動時から自動適用

  ### 注意
  - 学習時は btc_change_24h 等を None (→ 0) として扱う (ヒストリカルデータなし)
  - 実推論時は orchestrator から btc_change が渡されるため問題なし

- [ ] **Crypto ML: データ品質問題の修正 (棚上げ中)**

  ### 現状
  - Binance API で BTC/ETH 価格取得は実装済み (`95c44f6`)
  - 再学習結果: Train AUC=0.505, Valid AUC=0.677 (木1本でearly stopping)
  - **特徴量重要度が依然 `market_volume_24h` のみ**
  - 原因: 学習データに非cryptoマーケットが混入している
    - "Avalanche vs. Jets" (NHLホッケー) が "avalanche" キーワードにマッチ
    - "Up or Down" 1時間バイナリ (price=0.500 の50/50コインフリップ) が大量混入
  - モデルファイルは削除済み (`lgb_crypto_model.pkl`)、現在LLMのみで運用中

  ### 修正が必要な内容 (着手前)
  1. `is_crypto_market()` のキーワード精度向上 — "Avalanche"→"AVAX"のみ等
  2. 学習データから "Up or Down" 短期バイナリを除外
  3. 十分なデータ品質が確認できてから再学習

- [x] **スポーツ系マーケットのトレードスキップ** — 対応済み (`837200a`)
  - `is_sports_market()`: NFL/NBA/UFC等のキーワードで判定
  - トレードはスキップするがBrier記録は継続 (skill_score蓄積に活用)
  - 誤検知対策: "beat/win" 等の汎用語は除外しスポーツ固有語のみ使用

- [x] **LLMへの価格推移インプット (日足スナップショット)** — 対応済み
  - `analyst/ensemble.py` の `analyze()` 内で prices (1分足) を 1440 本おきにサンプリング
  - 最大 14 日分を `"3/12=0.41, 3/13=0.43, ..."` 形式で `context["price_history"]` に追加
  - `analyst/llm_analyst.py` 側も `price_history` キー対応済み
  - 1440 本未満 (マーケット開始直後等) は price_history を送らない

- [x] **ポジション管理ループの独立化 (利確・PENDING確認を分析間隔から切り離す)** — 対応済み (`0176c18`)

  ### 問題
  現在 `_check_pending_gtc_orders()` と `_check_position_exits()` は分析ループ内で実行されている。
  分析間隔は解決まで7日以上のマーケットが多いと **240分 (4時間)** になるため:
  - GTC注文の約定確認が最大4時間遅れる
  - 含み益40%超えても利確チェックが4時間後
  - 60分タイムアウトキャンセルが発動しない (キャンセル対象なのに4時間放置)
  という問題がある。

  ### 方針: `_positions_loop` を拡張して売買判断も担わせる

  **Before:**
  ```
  _positions_loop (30秒ごと)
   └── ダッシュボード表示のみ

  分析ループ (最大4時間ごと)
   ├── _analyze_market()             ← LLM分析・発注・LLM逆転クローズ
   ├── _check_pending_gtc_orders()   ← PENDING約定確認・60分キャンセル
   ├── _check_resolved_markets()     ← 解決済みPnL確定
   └── _check_position_exits()       ← 利確・損切り
  ```

  **After:**
  ```
  _positions_loop (5分ごと)           ← LLM不要の判断を高頻度で実行
   ├── _check_pending_gtc_orders()   ← PENDING約定確認・60分キャンセル
   ├── _check_position_exits()       ← 利確・損切り
   └── ダッシュボード表示

  分析ループ (最大4時間ごと)          ← LLMコールが必要な判断のみ
   ├── _analyze_market()             ← LLM分析・発注・LLM逆転クローズ
   └── _check_resolved_markets()     ← 解決済みPnL確定
  ```

  ### 実装詳細

  **`_positions_loop()` の変更 (`runner/orchestrator.py`):**
  - sleep を 30秒 → 300秒 (5分) に変更
  - `_check_pending_gtc_orders()` を追加
  - `_check_position_exits()` を追加 (markets は `self._last_markets` を使用)
  - ダッシュボード更新は末尾に維持

  **分析ループ (`_analysis_loop()`) から削除:**
  - `await self._check_pending_gtc_orders()` を削除
  - `await self._check_position_exits(markets)` を削除

  ### 注意
  - `_check_position_exits()` が使う `markets` は `self._last_markets` で代替
    (スキャン最新結果。価格が多少古くても利確判断には十分)
  - `_positions_loop` の初回 sleep は 10秒のまま維持 (起動直後は分析ループ優先)
  - LLM逆転クローズ (`_analyze_market` 内) は分析ループに残す
    (LLMコールが必要なため高頻度化はコスト的に不適切)

- [x] **約定済みポジションの早期クローズ戦略 (条件付きHOLD)** — 対応済み (`898225b`)

  ### 背景・判断
  現在は約定後は解決まで無条件HOLD (`enable_exit=False`)。
  しかしエッジの源泉は「情報非対称性」であり、時間とともに市場に織り込まれる。
  含み益があるうちに売ることで確定利益に変え、資金を次の機会に回すほうが期待値が高い局面がある。
  一方で流動性が薄いマーケットでのスプレッドコストは大きく、無条件の途中売却は逆効果になる。
  → **「条件付きHOLD」** が正解。

  ### 実装する2つの早期クローズ条件

  **① 利確 (Take Profit) — 残り日数考慮**
  - 現状: `take_profit_pct=0.50` 固定、`enable_exit=False` で無効
  - 新条件:
    - 含み益 ≥ +40% **かつ** 解決まで14日超 → 売却
    - 解決まで7日以内はスプレッドコストが割に合わないためHOLD継続
  - 実装箇所: `_check_position_exits()` に `days_to_resolution` チェックを追加
  - `enable_exit` フラグは廃止して常時有効化 (条件で制御するため)

  **② LLM逆転クローズ — 根拠崩壊による損切り**
  - 現状: 再分析でLLMが逆方向を出してもフィルド済みポジションは何もしない
  - 新条件:
    - 約定済み (FILLED) ポジションを持つマーケットも再分析対象にする
    - LLMシグナルが逆方向 **かつ** edge > min_edge の強い逆シグナル → 売却
    - 弱い逆シグナル (edge < min_edge) や信頼度不足はHOLD継続 (ノイズ扱い)
  - 実装箇所: `_analyze_market()` の冒頭スキップロジックを変更
    - 現在: `executed_markets` にありPENDINGでなければ即return
    - 変更後: FILLEDポジションも分析を通過し、逆シグナル強ければ売却

  ### 実装詳細

  **`_analyze_market()` の変更:**
  ```
  if market_id in executed_markets:
      pending → 既存通りエッジ再検証
      filled  → _check_reversal_exit=True で分析継続 (逆シグナル確認のみ)
      なし    → return (完了済み)
  ```
  分析後、`_check_reversal_exit=True` かつ逆方向エッジ十分なら `_exit_position()` を呼ぶ。

  **`_check_position_exits()` の変更:**
  ```
  利確: pnl_pct >= 0.40 かつ days_to_resolution > 14 → 売却
        days_to_resolution <= 7 → HOLD (スプレッドコスト回避)
  損切り: pnl_pct <= -0.50 → 売却 (既存維持)
  ```

  **`_exit_position(pos, reason, current_price)` ヘルパー追加:**
  - 売却注文発注 + position_tracker.close_position() + risk_manager更新 + executed_markets.discard()
  - `_check_position_exits` と `_analyze_market` (逆転クローズ) の両方から呼ぶ

  ### 設定変更
  - `enable_exit` フラグ廃止 (常時有効、条件で制御)
  - `take_profit_pct: float = 0.40` (50% → 40%に引き下げ)
  - `take_profit_min_days: int = 14` 追加 (これより残り日数が多いときのみ利確)
  - `stop_loss_pct: float = -0.50` 維持
  - `llm_reversal_exit: bool = True` 追加 (LLM逆転クローズのON/OFF)

  ### 注意
  - LLM逆転クローズは再分析コスト (LLM呼び出し) が増える → 分析間隔が長い時間帯は許容範囲
  - 売却注文は GTC (既存インフラ流用)
  - スポーツ市場のポジションも逆転クローズ対象にする

- [x] **トリガー機構を廃止して即時GTC発注に移行** — 対応済み (`6e70fb9`)

  ### 問題
  現在のトリガーは `BUY_YES: price <= target_price (= 分析時現在価格)` で発火する。
  LLMが正しい（= 市場が価格を上げる）ときほどトリガーが発火せず期限切れになる逆説がある。
  予測市場はニュース駆動で情報優位の窓が短いため、発火遅延はエッジの損失に直結する。

  ### 方針: 分析直後に即 GTC 指値発注
  - 分析完了 → 即 `client.buy()` で CLOB に GTC 指値を投げる
  - 指値価格 = 分析時の YES 価格 (現状と同じ、追いかけない)
  - 注文は CLOB のブックに乗り、カウンターパーティが来れば約定
  - **エッジ消失時キャンセル**: 次サイクルの再分析でエッジが `min_edge * 0.5` を下回ったら
    `client.cancel_order(order_id)` を呼んでキャンセル
  - 60分タイムアウト自動キャンセルは現状通り維持

  ### 削除するもの
  - `TriggerCondition` クラス
  - `active_triggers` dict
  - `_set_trigger()` / `_check_triggers()` / `_execute_trigger()`
  - WebSocket の `_check_triggers` 呼び出し

  ### 追加・変更するもの
  - `_analyze_market()` 内で直接 `executor.execute_order()` を呼ぶ
  - `Position` に `order_id` が既にあるので、キャンセルは `client.cancel_order(order_id)` で可能
  - 再分析時に既存ポジション (PENDING) を検出 → エッジ再検証 → 消失でキャンセル
  - `_check_pending_gtc_orders()` の既存 60分キャンセルロジックはそのまま流用

  ### 注意
  - 最小注文サイズチェック (5 tokens) は発注前に必須 (既存ロジック流用)
  - エクスポージャーチェックも発注前に必須 (既存ロジック流用)
  - `executed_markets` の管理は現状通り (再エントリー防止)

- [x] **⑲ sell時のサイズ不一致による "not enough balance" エラー** — 対応済み

  ### 症状
  ```
  ⏭️ トークン未保有またはアローワンス不足のためスキップ: not enough balance / allowance
  ```
  Polymarket上でトークンを保有しているにもかかわらずSELL注文が失敗する。

  ### 原因
  - `pos.size` はシステムが意図したUSDC投資額 ($6.65)
  - GTC買い注文が**部分約定**した場合、実際のトークン数は少ない (例: 6.7トークン = $1.95)
  - `_place_order` 内で `size = amount / price` → USDC投資額÷NO価格 = トークン数に変換
  - 売却時: `amount = pos.size = $6.65`, `price = NO価格 = 0.61` → `size = 10.9トークン`
  - 実残高6.7トークン < 要求10.9トークン → "not enough balance"

  ### 修正
  - `PolyClient.get_token_balance(token_id)`: `get_balance_allowance(AssetType.CONDITIONAL, token_id)` で実残高を取得
  - `_exit_position()`: 売却前に実トークン残高を照会し、`sell_size = actual_tokens × sell_price` に補正
  - 残高差が$0.50以上のときログ出力
  - 取得失敗時は従来の `pos.size` にフォールバック

- [x] **⑱ GTC売り注文を即CLOSEDにするバグ** — 対応済み

  ### 症状
  利確・損切りトリガー後「クローズ完了」と表示されるが、Polymarket上では依然トークンを保有中。
  次の positions_loop でも CLOSED 扱いのため再チェックされず放置。

  ### 原因
  `_exit_position()` が `executor.execute_order()` の成功（= 注文発注成功）を約定完了と誤解し、
  即 `close_position()` を呼んでいた。GTC なので約定するまでは未成立。

  ### 修正
  - `Position` に `pending_sell_order_id / pending_sell_price` フィールドを追加
  - `_exit_position()`: 売り注文発注成功時 → `mark_pending_sell()` のみ (CLOSED にしない)
  - `_check_pending_gtc_orders()`: GTC買い注文と同様に売り注文も CLOB 確認
    - MATCHED/FILLED → `close_position()` + RiskManager 更新
    - CANCELLED → `cancel_pending_sell()` で ACTIVE 復帰
    - LIVE 60分超 → 自動キャンセル → ACTIVE 復帰 → 次ループで再判断
  - `_check_position_exits()`: `pending_sell_order_id` があるポジションをスキップ (再発注防止)

- [x] **㉑ 損切りロジックの再設計 — 価格ベース→確率崩壊ベース**

  ### 問題 (トレーダー③の指摘)
  現在の `stop_loss_pct = -0.50` は「価格が-50%動いたら売る」という設計。
  予測市場の本質は **「自分の確率推定 vs 市場価格の乖離」** であって価格変動幅ではない。
  - BUY_NO at 0.29 (YES=0.71)。YES が 0.87 になっても「NO がまだ勝つ」と信じるなら持ち続けるべき
  - 逆に YES が 0.72 に微動しただけでも「LLM が完全に間違っていた」なら即座に撤退すべき
  - しかも GTC 指値 → 相手がいないと刺さらない。深いドローダウン時は流動性も薄い
  - 二値解決なので -50% で止めても -100% になる可能性は排除できない

  ### 新しい損切り設計

  **① 確率崩壊ストップ (メイン)**
  - BUY_NO ポジション: `current_yes_price >= collapse_threshold (例: 0.88)` → ほぼ YES 確定 → 損切り
  - BUY_YES ポジション: `current_yes_price <= (1 - collapse_threshold)` → ほぼ NO 確定 → 損切り
  - 根拠: 市場参加者の集合知が一方に収束したとき「自分の thesis が崩壊した」と判断
  - デフォルト閾値: `collapse_threshold = 0.88`

  **② 残り日数 × 含み損 複合チェック (セーフティネット)**
  - `days_to_resolution <= 7 AND pnl_pct <= -0.40` → 時間切れ前の傷口縮小
  - 解決まで1週間以内かつ-40%なら回復見込みが薄い → 撤退

  **③ 価格ベース損切りは撤廃 or 大幅緩和**
  - `stop_loss_pct = -0.50` → 撤廃、または `-0.80` に緩和 (ほぼ全損時の最終保険のみ)
  - LLM逆転クローズ (`llm_reversal_exit`) が「根拠崩壊」の主要な損切りとして機能

  ### 設定値追加
  ```python
  # OrchestratorConfig に追加
  collapse_threshold: float = 0.88   # 確率崩壊ストップ (YES確率がここを超えたらBUY_NOを損切り)
  stop_loss_near_expiry_days: int = 7   # 残りN日以内
  stop_loss_near_expiry_pct: float = -0.40  # 残り日数少なく含み損がここ以下なら損切り
  ```

  ### 実装箇所
  - `tracker/position_tracker.py` `check_exit_conditions()`:
    - 確率崩壊チェック追加 (BUY_NO: yes_price >= collapse_threshold)
    - 近解決 × 含み損チェック追加
    - 価格ベース stop_loss_pct は緩和または削除
  - `runner/orchestrator.py` `_check_position_exits()`:
    - collapse_threshold を config から渡す
    - near_expiry 損切りのログを追加

  ### 注意
  - LLM逆転クローズ (既存) との棲み分け:
    - LLM逆転 = 「自分の分析が変わった」= 根拠消滅による売却
    - 確率崩壊ストップ = 「市場が圧倒的多数決を出した」= 強制撤退
    - 両方とも GTC SELL なので流動性リスクは残る

- [x] **㉒ 利確トリガーの再設計 — 価格上昇%→エッジ消失ベース**

  ### 問題 (トレーダー⑨の指摘)
  現在の `take_profit_pct = 0.40` は「含み益+40%で売る」という設計。
  しかし予測市場の利確の本質は **「エッジが消えた（市場が自分の thesis を織り込んだ）ときに売る」**。
  - LLM が「NO確率 = 85%」と予測、市場が「NO = 71%」→ エッジ = +14%。持ち続けるべき。
  - 市場が「NO = 83%」まで動く → エッジ = +2%。もはや優位性なし → 売るべき。
  - 価格が+40%上昇したかどうかは副次的情報で、エッジが残っているかどうかが本質。

  ### 新しい利確設計

  **① エッジ消失利確 (メイン)**
  - ポジション開始時のエッジ (`entry_edge`) を Position に記録
  - 各ループで最新 LLM シグナルのエッジを確認
  - `current_edge < edge_take_profit_threshold (例: 0.05)` → 市場が thesis を織り込んだ → 利確
  - 前提: 分析ループで `market_id → 最新シグナル` のキャッシュを保持

  **② 価格ベース利確は残す (セカンダリ・大きく動いた時の保険)**
  - `pnl_pct >= take_profit_pct (0.40)` は維持
  - 理由: LLM再分析の間隔が長い場合、価格が大きく動いてもエッジ更新が遅れる可能性
  - ① と ② の OR 条件で利確

  ### Position への entry_edge 追加
  ```python
  # Position dataclass に追加
  entry_edge: Optional[float] = None  # エントリー時の LLM エッジ (例: +0.14)
  ```
  - `record_trade()` 呼び出し時に signal.edge を渡して保存
  - from_dict / to_dict に追加

  ### LLMシグナルキャッシュ
  ```python
  # Orchestrator に追加
  self._last_signals: Dict[str, Signal] = {}  # market_id → 最新シグナル
  ```
  - `_analyze_market()` で LLM シグナル生成後に `self._last_signals[market_id] = signal` で更新
  - `_check_position_exits()` でポジションの market_id に対応するシグナルを参照

  ### 実装箇所
  - `tracker/position_tracker.py`:
    - `Position` に `entry_edge: Optional[float]` 追加
    - `record_trade()` の引数に `entry_edge` 追加
    - `check_exit_conditions()` の引数に `last_signals: Dict[str, Any]` を追加し、エッジ消失チェックを追加
  - `runner/orchestrator.py`:
    - `self._last_signals = {}` を `__init__` に追加
    - `_analyze_market()` でシグナル生成後にキャッシュ更新
    - `_check_position_exits()` で `_last_signals` を渡す
    - 既存のポジション発注時 (`_execute_order`) で `entry_edge=signal.edge` を記録

  ### 設定値追加
  ```python
  # OrchestratorConfig に追加
  edge_take_profit_threshold: float = 0.05  # エッジがこれ以下になったら利確
  ```

  ### ログ出力
  ```
  💰 エッジ消失利確: Will Solana reach $100 in March? (entry_edge=+14.2% → current_edge=+2.1%)
  ```

  ### 注意
  - LLM 再分析間隔 (最大数時間) の間はキャッシュが古くなる → 価格ベース利確がバックアップとして機能
  - スキャン対象外のポジションは `_last_signals` に載らない → 価格ベース利確のみ適用
  - entry_edge が null の既存ポジションはエッジ消失チェックをスキップ (価格ベースのみ)

- [x] **㉓ LLM へのパフォーマンスフィードバック — 自己学習コンテキスト注入**

  ### 問題
  現状 LLM は各マーケットの分析ごとに「同マーケットの前回判断」(`previous_judgment`) しか受け取らない。
  自分の過去の予測がどう解決したか、どんな傾向でミスしているかを知らないため、
  同じバイアスを繰り返しても修正できない。
  - Brier スコアはポジションサイジングには使われているが、LLM の推論には未フィードバック
  - 「暗号資産系を楽観視しすぎる」「政治系は堅実」といったパターンを LLM 自身が把握できていない

  ### 追加するフィードバック情報 (LLM prompt に context として注入)

  **① 総合トラックレコード (直近N件)**
  ```
  あなたの過去30件の予測実績:
  - 勝率: 63% (19勝/11敗)
  - 平均PnL: +$2.1/件
  - 予測確率の平均乖離: +8% (市場より強気傾向)
  ```

  **② カテゴリ別精度**
  ```
  カテゴリ別:
  - 暗号資産: 勝率40% (過信傾向 +15%) ← 注意
  - 地政学: 勝率70% (堅実)
  - 選挙・政治: 勝率65%
  ```
  カテゴリは `question` のキーワードから簡易分類 (crypto / geopolitical / election / other)

  **③ 直近の外れパターン (最大5件)**
  ```
  直近の外れ予測:
  - "Will BTC reach $100k in March?" BUY_YES (予測70%) → 負け (NO確定)
  - "Sharks vs. Oilers" BUY_YES (予測60%) → 負け
  ```
  連続ミスや特定パターンへの過集中を自己認識させる

  ### データソース
  - `data/positions.json`: 解決済みポジション (`status: resolved/closed`) から勝敗・PnL・サイドを集計
  - `data/trade_log.jsonl`: 補助 (重複する場合は positions.json を優先)

  ### カテゴリ分類ロジック
  ```python
  def _classify_market(question: str) -> str:
      q = question.lower()
      if any(k in q for k in ["btc", "bitcoin", "eth", "crypto", "solana", "doge"]): return "crypto"
      if any(k in q for k in ["election", "president", "prime minister", "vote", "poll"]): return "election"
      if any(k in q for k in ["war", "ceasefire", "troops", "military", "russia", "ukraine", "israel"]): return "geopolitical"
      return "other"
  ```

  ### 実装箇所
  - `analyst/llm_analyst.py`:
    - `analyze()` の引数に `performance_context: str = ""` を追加
    - システムプロンプトまたはユーザープロンプトの冒頭に注入
  - `runner/orchestrator.py`:
    - `_build_performance_context()` メソッドを新規追加
      - `position_tracker.get_closed_positions()` から直近30件を集計
      - 総合勝率・平均PnL・カテゴリ別精度・直近外れ5件を文字列生成
    - `_analyze_market()` で `performance_context=self._build_performance_context()` を渡す
    - パフォーマンス context はキャッシュして毎サイクル1回だけ生成 (`self._perf_context_cache`)

  ### キャッシュ戦略
  ```python
  self._perf_context_cache: str = ""
  self._perf_context_updated_at: Optional[datetime] = None
  # 30分ごとに再生成 (閉じたポジションが増えたタイミングで自動更新)
  ```

  ### ログ出力例
  ```
  📊 LLM context: 過去23件 勝率61% | crypto注意(40%) | 直近外れ2件
  ```

  ### 注意
  - 解決済みポジションが10件未満のときはフィードバックなし (データ不足で逆効果)
  - prompt が長くなりすぎないよう context は最大500文字程度に制限
  - `previous_judgment` (同マーケット前回判断) との併用で、マクロ傾向 + 個別文脈の両方を提供

- [x] **㉔ LLM による相関ポジション検出 — 同一イベント二重エントリー防止** — 対応済み

  ### 問題 (実例)
  "Will Israel strike 2 countries in March 2026?" → BUY_YES
  "Will Israel strike ≥4 countries in March 2026?" → BUY_YES
  → 両方 YES を買うのは論理的に矛盾 (片方が YES なら必ずもう片方は NO)。
  LLM が各マーケットを**独立して**分析するため、保有済みポジションとの相関を見落とす。
  キーワードマッチでは "2 countries" vs "≥4 countries" の相関は取れないが、LLM なら意味的に判断できる。

  ### 解決策: LLM に保有ポジション一覧を渡して相関フラグを出力させる

  **JSON 出力スキーマに `is_correlated` を追加**
  ```json
  {"probability": 0.65, "confidence": 0.7, "reasoning": "...", "is_sport": false, "is_correlated": false, "correlation_reason": ""}
  ```
  - `is_correlated: true` → このマーケットは保有済みポジションと相関あり → 発注スキップ
  - `correlation_reason`: 相関理由 (ログ用)

  **システムプロンプトへの追記**
  ```
  ## 保有中のポジション (相関チェック用)
  以下はすでにオープンしているポジションです:
  - "Will Israel strike ≥4 countries in March 2026?" (BUY_YES)
  - "Will Trump visit China by May 31?" (BUY_NO)

  分析対象マーケットが上記のいずれかと「同一または強く相関するイベント」に関する場合、
  is_correlated: true を返してください。
  相関の例:
  - 同じ試合・大会の別条件 ("チームA が勝つ" と "チームA が10点以上取る")
  - 同じ選挙の別候補 ("A が当選" と "B が当選" で排他的)
  - 同じ資産の別閾値 ("BTC が$80k超" と "BTC が$100k超" は正相関)
  - 同じ地政学イベントの別スケール ("2カ国攻撃" と "≥4カ国攻撃" は排他的)
  保有ポジションがない場合、または明確に無関係な場合は is_correlated: false。
  ```

  ### 実装箇所

  **`analyst/llm_analyst.py`**
  - `SYSTEM_PROMPT` に保有ポジション context のプレースホルダーを追加
  - `analyze_market()` に `open_positions_context: str = ""` 引数を追加
  - context に注入: `if open_positions_context: ctx_text += f"\n\n{open_positions_context}"`
  - `_parse_llm_json()` で `is_correlated` / `correlation_reason` を取得

  **`analyst/ensemble.py`**
  - `analyze()` に `open_positions_context: str = ""` 引数を追加
  - `llm_analyst.analyze_market()` に渡す
  - 戻り値 `EnsembleSignal` に `llm_is_correlated: Optional[bool]` フィールドを追加

  **`runner/orchestrator.py`**
  - `_analyze_market()` で発注直前に保有ポジション一覧を文字列生成:
    ```python
    def _build_open_positions_context(self) -> str:
        positions = self.position_tracker.get_open_positions()
        filled = [p for p in positions if p.order_filled]
        if not filled:
            return ""
        lines = ["## 保有中のポジション (相関チェック用)"]
        for p in filled:
            lines.append(f'- "{p.question}" ({p.side.upper()})')
        return "\n".join(lines)
    ```
  - `analyst.analyze()` に `open_positions_context=self._build_open_positions_context()` を渡す
  - シグナル取得後: `if getattr(signal, 'llm_is_correlated', False): print(...); return`

  ### ログ出力例
  ```
  🔗 相関ポジション検出: Will Israel strike 2 countries in March 2026?
     → 保有中: "Will Israel strike ≥4 countries in March 2026?" (BUY_YES) と排他的
     ⏭️ 発注スキップ
  ```

  ### 注意
  - LLM が過剰検出するリスク: `correlation_reason` をログに出して様子見。誤検出が多ければ閾値調整
  - 保有ポジションが0件の場合は context を渡さない (prompt を短く保つ)
  - PENDING (order_filled=False) のポジションも相関対象に含める (約定前でも同じリスク)

- [ ] **同一イベントへの集中リスク対策 (相関グループ管理)**
  - 現状: "GTA VI before X?" 系マーケットが複数トリガーに並ぶと実質1ポジション分のリスクになる
  - 対策案: マーケットの `question` からイベントキーワードを抽出し、同一グループへのエクスポージャーをグループ単位で上限管理
  - 例: "GTA VI" グループは最大1件、または合計サイズ上限を設ける
  - 実装場所: `runner/orchestrator.py` の `_analyze_and_set_triggers()` でシグナルをグループ化してフィルタリング



- [x] **実運用ログの整備** — 対応済み (`data/trade_log.jsonl`)

- [x] **バックテスト基盤** — 対応済み (`scripts/backtest.py`)
  - 解決済みマーケットを取得し、分析ポイント以前の価格のみでシグナル生成 (lookahead 防止)
  - ML + (optional LLM) + Bayesian 統合 → Quarter Kelly サイジング → PnL 計算
  - メトリクス: 勝率, ROI, Sharpe, 最大ドローダウン / `data/backtest_results.json` 保存
  - `python scripts/backtest.py --days 90 --limit 100 [--use-llm] [--min-edge 0.15]`

- [x] **ポジション管理 UI の強化** — 対応済み
  - 「Open Positions」パネルをダッシュボードに追加
  - エントリー価格・現在価格・含み損益 ($・%) をリアルタイム表示
  - 分析サイクルごとに orchestrator から WebSocket でプッシュ

- [x] **ML特徴量の volume データ改善** — 対応済み
  - `_retrain_ml_model` で CLOB `/trades` エンドポイントから取引履歴を取得
  - `buy_volume_ratio` / `order_flow_imbalance` が実データで学習されるように
  - 合わせて Gamma API 直接呼び出しに変更 (closed=false バグも修正)

- [ ] **㉗ ニュース→LLM入力の品質改善 (優先度S+A)**

  ### 背景・動機
  プロトレーダー10人の視点でレビューした結果、現在のニュース取得→LLM入力パイプラインに
  重大な情報欠落が多数見つかった。LLMが受け取る情報の質が予測精度のボトルネックになっている。

  ### 現状の問題点
  ```
  現在LLMに渡される形式:
  関連ニュース:
  - Bitcoin jumps as oil prices slip
    Article body text truncated to 300 chars...
  - Crypto market sheds $100 billion...
    Body text...

  問題:
  1. 公開日時なし → 3日前の記事と今日の記事が区別不能
  2. ソース名なし → CoinDeskもランダムブログも同列扱い
  3. 最大5件 → コンセンサス方向が見えない
  4. 本文300文字 → 核心情報（データ・数値・引用）に到達しない
  5. 質問タイプを問わず一律DDG検索 → 政治系・規制系で的外れな記事を拾う
  ```

  ---

  ### 改善① (S) 公開日時をLLMに渡す

  #### 目的
  LLMが情報の鮮度を判断でき、古い記事に基づく誤判断を防ぐ。

  #### 実装

  **A. `data_fetcher/news_fetcher.py` — `GoogleNewsFetcher.search()`**
  DDG検索結果から日付を直接取得するのは難しいため、記事本文フェッチ時にメタデータを抽出する。

  ```python
  # Scraplingで記事ページをフェッチした後:
  published = None

  # 1. <meta> タグから取得 (最も信頼性が高い)
  meta_selectors = [
      'meta[property="article:published_time"]',
      'meta[name="publish-date"]',
      'meta[name="date"]',
      'meta[property="og:article:published_time"]',
  ]
  for sel in meta_selectors:
      el = page.css_first(sel)
      if el:
          published = el.attrib.get("content", "")
          break

  # 2. <time> タグから取得
  if not published:
      time_el = page.css_first("time[datetime]")
      if time_el:
          published = time_el.attrib.get("datetime", "")

  # 3. パース
  if published:
      from dateutil.parser import parse as dateparse
      try:
          article.published = dateparse(published)
      except Exception:
          pass
  ```

  **B. `runner/orchestrator.py` — ニュースフォーマット部分 (L516-523)**
  ```python
  # 変更前:
  line = f"- {a.title}"
  if a.summary:
      line += f"\n  {a.summary[:300]}"

  # 変更後:
  date_str = a.published.strftime('%Y-%m-%d %H:%M') if a.published else "日時不明"
  line = f"- [{date_str}] {a.title}"
  if a.summary:
      line += f"\n  {a.summary[:300]}"
  ```

  **LLMに渡される改善後の形式:**
  ```
  関連ニュース:
  - [2026-03-21 14:30] Bitcoin jumps as oil prices slip
    Article body...
  - [2026-03-20 09:15] Crypto market sheds $100 billion...
    Body text...
  - [日時不明] Another headline...
  ```

  ---

  ### 改善② (S) ソース名をLLMに渡す

  #### 目的
  LLMがソースの信頼度を考慮して判断できるようにする。
  CoinDesk / Reuters と個人ブログでは情報の重みが異なる。

  #### 実装

  **A. `data_fetcher/news_fetcher.py` — `GoogleNewsFetcher.search()`**
  現在 `source=url` でURL全体を入れている。ドメイン名を抽出してクリーンにする。

  ```python
  import re
  from urllib.parse import urlparse

  def _extract_source_name(self, url: str) -> str:
      """URLからソース名を抽出"""
      try:
          domain = urlparse(url).netloc
          # www. を除去
          domain = re.sub(r'^www\.', '', domain)
          # 既知ソースのマッピング
          known = {
              "coindesk.com": "CoinDesk",
              "cointelegraph.com": "CoinTelegraph",
              "theblock.co": "The Block",
              "decrypt.co": "Decrypt",
              "reuters.com": "Reuters",
              "bloomberg.com": "Bloomberg",
              "cnbc.com": "CNBC",
              "bbc.com": "BBC",
              "nytimes.com": "NYT",
              "washingtonpost.com": "WaPo",
              "theguardian.com": "The Guardian",
              "apnews.com": "AP News",
              "forbes.com": "Forbes",
              "yahoo.com": "Yahoo Finance",
              "finance.yahoo.com": "Yahoo Finance",
          }
          return known.get(domain, domain)
      except Exception:
          return url
  ```

  **B. `runner/orchestrator.py` — フォーマット部分**
  ```python
  source_name = a.source if len(a.source) < 30 else a.source.split('/')[2]  # ドメイン抽出
  date_str = a.published.strftime('%Y-%m-%d %H:%M') if a.published else "日時不明"
  line = f"- [{date_str} | {source_name}] {a.title}"
  ```

  **LLMに渡される形式:**
  ```
  - [2026-03-21 14:30 | CoinDesk] Bitcoin jumps as oil prices slip
  - [2026-03-20 09:15 | The Block] Crypto market sheds $100 billion...
  - [日時不明 | decrypt.co] Another headline...
  ```

  ---

  ### 改善③ (A) 記事数を10-15件に増やす (タイトルのみ追加分)

  #### 目的
  報道のコンセンサス方向（強気何件/弱気何件）をLLMが把握できるようにする。
  5件では偏ったソースの意見しか拾えないリスクがある。

  #### 設計方針
  - 上位5件: タイトル + ソース + 日時 + 本文サマリー（従来通り）
  - 6-15件目: タイトル + ソース + 日時のみ（トークン節約）
  - これにより追加トークンは最小限（タイトル10件 ≈ 500トークン程度）

  #### 実装

  **A. `runner/orchestrator.py` — `OrchestratorConfig`**
  ```python
  # 変更前:
  news_limit: int = 5

  # 変更後:
  news_limit: int = 15            # 総取得件数
  news_detail_limit: int = 5      # 本文付きで渡す件数
  ```

  **B. `runner/orchestrator.py` — ニュースフォーマット部分 (L516-523)**
  ```python
  if articles:
      lines = []
      for i, a in enumerate(articles[:self.config.news_limit]):
          source_name = self.news_fetcher._extract_source_name(a.url) if hasattr(a, 'url') else a.source
          date_str = a.published.strftime('%Y-%m-%d %H:%M') if a.published else "日時不明"

          if i < self.config.news_detail_limit:
              # 上位N件: タイトル + 本文
              line = f"- [{date_str} | {source_name}] {a.title}"
              if a.summary:
                  line += f"\n  {a.summary[:500]}"
          else:
              # 残り: タイトルのみ
              line = f"- [{date_str} | {source_name}] {a.title}"

          lines.append(line)
      news_context = "\n".join(lines)
  ```

  **C. `data_fetcher/news_fetcher.py` — `GoogleNewsFetcher.search()`**
  - `limit` パラメータのデフォルトを `15` に変更
  - 本文フェッチ (Scrapling) は上位5件のみに制限（速度とリソース節約）
  - 6件目以降はDDG検索結果のタイトルだけ使い、本文フェッチをスキップ

  ```python
  # search() 内のフェッチループ:
  for i, (title, url) in enumerate(raw_results[:limit]):
      if self._should_skip(url):
          articles.append(NewsArticle(title=title, url=url, source=url))
          continue

      body = ""
      if scrapling_ok and i < 5:  # ★ 上位5件だけ本文フェッチ
          try:
              page = await _asyncio.get_event_loop().run_in_executor(...)
              # ... 本文抽出 + published抽出
          except Exception:
              pass

      articles.append(NewsArticle(
          title=title, url=url, source=self._extract_source_name(url),
          summary=body, published=published,
      ))
  ```

  ---

  ### 改善④ (A) 本文を500-800文字に拡大

  #### 目的
  ニュースの核心情報（データ、数値、引用、具体的事実）は通常500文字目以降にある。
  300文字では導入部のみで分析に使えないことが多い。

  #### 実装

  **A. `data_fetcher/news_fetcher.py` — `GoogleNewsFetcher.search()`**
  ```python
  # 変更前:
  body = " ".join(
      p.text for p in paras
      if p.text and len(p.text) > 60
  )[:1000]

  # 変更後:
  body = " ".join(
      p.text for p in paras
      if p.text and len(p.text) > 60
  )[:2000]  # フェッチ時は2000文字まで取得
  ```

  **B. `runner/orchestrator.py` — フォーマット部分**
  ```python
  # 変更前:
  line += f"\n  {a.summary[:300]}"

  # 変更後:
  line += f"\n  {a.summary[:800]}"
  ```

  #### トークン影響
  - 5件 × 800文字 ≈ 4000文字 ≈ 1500トークン
  - 5件 × 300文字 ≈ 1500文字 ≈ 600トークン
  - 増分: 約900トークン（LLM入力全体の5-10%程度、許容範囲）

  ---

  ### 改善⑤ (A) 質問カテゴリ別のソース選択・キーワード戦略

  #### 目的
  Polymarketは「BTC $100k到達」「Trump大統領」「SEC ETF承認」など全く異なるジャンルが混在。
  一律DDG検索では政治系・規制系で的外れな記事を拾う。
  質問カテゴリを判定し、カテゴリに応じたキーワード補強を行う。

  #### 設計方針
  - LLMを使ったカテゴリ分類は**しない**（コスト増・遅延）
  - キーワードベースのルール判定で十分（高速・無料）
  - カテゴリに応じて**検索キーワードに補助語を追加**する方式

  #### カテゴリ定義
  ```python
  MARKET_CATEGORIES = {
      "crypto_price": {
          "keywords": ["bitcoin", "btc", "ethereum", "eth", "solana", "sol",
                       "price", "reach", "above", "below", "$"],
          "search_suffix": "price prediction analysis",
          "priority_sources": ["coindesk.com", "theblock.co", "cointelegraph.com"],
      },
      "politics": {
          "keywords": ["president", "election", "trump", "biden", "vote",
                       "republican", "democrat", "senate", "congress", "governor"],
          "search_suffix": "poll latest news",
          "priority_sources": ["reuters.com", "apnews.com", "bbc.com"],
      },
      "regulation": {
          "keywords": ["sec", "etf", "regulation", "approve", "ban", "law",
                       "bill", "federal", "reserve", "fed", "fomc", "rate"],
          "search_suffix": "regulation decision update",
          "priority_sources": ["reuters.com", "bloomberg.com", "coindesk.com"],
      },
      "geopolitics": {
          "keywords": ["war", "invasion", "ceasefire", "sanctions", "nato",
                       "russia", "ukraine", "china", "taiwan", "iran", "israel"],
          "search_suffix": "conflict update latest",
          "priority_sources": ["reuters.com", "apnews.com", "bbc.com"],
      },
      "tech": {
          "keywords": ["ai", "openai", "google", "apple", "microsoft", "launch",
                       "release", "product", "spacex", "tesla"],
          "search_suffix": "announcement latest news",
          "priority_sources": ["techcrunch.com", "theverge.com", "reuters.com"],
      },
      "general": {
          "keywords": [],
          "search_suffix": "latest news",
          "priority_sources": [],
      },
  }
  ```

  #### 実装

  **A. `data_fetcher/news_fetcher.py` — カテゴリ判定メソッド追加**
  ```python
  def _detect_category(self, question: str) -> str:
      """質問文からカテゴリを判定"""
      q_lower = question.lower()
      scores = {}
      for cat, config in MARKET_CATEGORIES.items():
          if cat == "general":
              continue
          score = sum(1 for kw in config["keywords"] if kw in q_lower)
          if score > 0:
              scores[cat] = score
      if not scores:
          return "general"
      return max(scores, key=scores.get)
  ```

  **B. `data_fetcher/news_fetcher.py` — `_extract_keywords` にカテゴリ補強**
  ```python
  def _extract_keywords(self, question: str) -> str:
      # ... 既存のキーワード抽出ロジック ...
      base_keywords = " ".join(unique[:6])

      # カテゴリに応じた検索補助語を追加
      category = self._detect_category(question)
      suffix = MARKET_CATEGORIES[category]["search_suffix"]

      return f"{base_keywords} {suffix}"
  ```

  **C. `runner/orchestrator.py` — ソース優先度の表示（オプション）**
  カテゴリの `priority_sources` に合致する記事を上位にソートする。
  ```python
  if articles:
      category = self.news_fetcher._detect_category(question)
      priority = MARKET_CATEGORIES.get(category, {}).get("priority_sources", [])

      def sort_key(a):
          domain = urlparse(a.url).netloc.replace("www.", "")
          is_priority = 0 if domain in priority else 1
          return (is_priority, 0 if a.published else 1)

      articles.sort(key=sort_key)
  ```

  ---

  ### 実装順序

  ```
  Step 1: 改善②ソース名 + 改善①日時 (S) — news_fetcher.py + orchestrator.py
          → 最小限の変更で最大の情報品質向上
  Step 2: 改善④本文拡大 (A) — news_fetcher.py + orchestrator.py
          → 数値変更だけ、即完了
  Step 3: 改善③記事数増加 (A) — config + orchestrator.py + news_fetcher.py
          → フォーマットロジック変更
  Step 4: 改善⑤カテゴリ別ソース (A) — news_fetcher.py 新規メソッド + orchestrator.py
          → 最も工数が大きいが効果も大きい
  ```

  ### 完成後のLLMプロンプト例
  ```
  関連ニュース:

  ■ 詳細 (上位5件):
  - [2026-03-21 14:30 | CoinDesk] Bitcoin jumps past $95k as oil prices slip
    Bitcoin surged 3.2% to $95,400 on Thursday after Brent crude fell below $70,
    easing inflation concerns. Analysts at JPMorgan noted the inverse correlation
    between energy costs and risk assets has strengthened since Q4 2025. The move
    also followed dovish comments from Fed Governor Waller suggesting rate cuts
    remain on the table for the June FOMC meeting...

  - [2026-03-21 09:15 | The Block] Crypto market sheds $100B as Fed holds rates
    The total crypto market cap dropped from $3.2T to $3.1T following the Federal
    Reserve's decision to maintain rates at 4.25-4.50%. Chair Powell emphasized
    persistent core inflation at 2.8% and signaled fewer cuts in 2026 than
    previously expected. Bitcoin dropped 5% to $88,200 before recovering...

  - [2026-03-20 22:00 | Reuters] Fed holds rates steady, signals cautious approach
    The U.S. Federal Reserve kept its benchmark rate unchanged at 4.25%-4.50% as
    expected, but the updated dot plot showed only one rate cut projected for 2026,
    down from two in the December projection...

  ■ ヘッドライン (6-15件目):
  - [2026-03-21 11:00 | Bloomberg] Bitcoin Mining Difficulty Hits All-Time High
  - [2026-03-21 08:45 | CNBC] Spot Bitcoin ETFs See $200M Outflows After Fed
  - [2026-03-20 19:30 | Decrypt] Whale Alert: 5,000 BTC Moved to Coinbase
  - [2026-03-20 16:00 | CoinTelegraph] On-Chain Data Shows Long-Term Holders Accumulating
  - [2026-03-20 14:20 | Yahoo Finance] BlackRock CEO: Bitcoin Is 'Digital Gold'
  - [2026-03-20 10:00 | AP News] US Treasury Announces New Crypto Reporting Rules
  - [2026-03-19 23:00 | Forbes] MicroStrategy Buys Another $500M in Bitcoin
  ```

---

## システム構成メモ (compact後参照用)

```
poly-ai-trader/
├── main.py              # CLI エントリポイント
├── runner/
│   └── orchestrator.py  # 3層統合ランナー (メインロジック)
├── analyst/
│   ├── llm_analyst.py   # LLM分析 (Claude Code CLI サブプロセス)
│   ├── ml_analyst.py    # LightGBM
│   ├── orderflow.py     # クジラ/流動性/クラスタ検出
│   ├── bayesian.py      # Bayesian統合 (market_liquidity対応済み)
│   ├── ensemble.py      # 全シグナル統合
│   └── features.py      # 28特徴量 (LLM特徴量除去済み・buy_volume_ratio等)
├── risk/
│   ├── risk_manager.py  # Kelly/ドローダウン/連敗管理
│   └── auditor.py       # ハルシネーション/流動性チェック
├── factor/
│   ├── miner.py         # LLM仮説生成
│   ├── backtester.py    # バックテスト
│   └── manager.py       # ファクター管理 (auto_kill修正済み)
├── tracker/
│   └── position_tracker.py  # ポジション永続化
├── executor/
│   └── trade_executor.py    # 注文実行
├── scanner/             # Polymarket + Binance スキャン
├── client/              # py-clob-client ラッパー
├── data_fetcher/
│   ├── history.py       # 過去価格
│   ├── websocket_client.py  # リアルタイム
│   └── news_fetcher.py  # Google News RSS
├── dashboard/
│   └── server.py        # FastAPI + WebSocket UI
├── scripts/
│   ├── train_ml.py      # 手動ML学習
│   └── backtest.py      # エンドツーエンドバックテスト
└── models/
    └── lgb_model.pkl    # 学習済みモデル (自動再学習で上書き)
```

### 主要な設定値

| 設定 | 値 | 場所 |
|---|---|---|
| 最小エッジ | 10% | `OrchestratorConfig.min_edge` |
| 最小信頼度 | 60% | `OrchestratorConfig.min_confidence` |
| Quarter Kelly | 25% | `RiskManager.kelly_fraction` |
| 最大ポジション | 10% | `RiskManager.max_position_pct` |
| 総エクスポージャー上限 | 30% | `RiskManager.max_total_exposure` |
| ドローダウン停止 | 15% | `RiskManager.max_drawdown_pct` |
| 連敗停止 | 3連敗 | `RiskManager.max_consecutive_losses` |
| ML再学習トリガー | 解決20件ごと | `OrchestratorConfig.retrain_threshold` |
| Whale閾値 | $10,000 | `OrderflowDetector.whale_threshold_usd` |
| トリガー有効期限 | max(30分, 分析間隔×1.5) | `orchestrator._set_trigger()` |

### CLIコマンド

```bash
python main.py scan                        # マーケットスキャン
python main.py analyze -n 5               # LLM分析
python main.py run                        # 自動売買 (ドライラン + ダッシュボード)
python main.py run --live                 # 本番実行
python main.py run --no-dashboard         # ダッシュボードなし
python main.py run --no-retrain           # ML自動再学習無効
python main.py run --enable-exit          # 利確・損切り有効
python scripts/train_ml.py --days 30      # 手動ML学習
python scripts/backtest.py --days 90     # バックテスト (MLのみ)
python scripts/backtest.py --use-llm     # バックテスト (ML + LLM)
```
