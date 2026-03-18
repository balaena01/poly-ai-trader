# Poly AI Trader - TODO

コード変更の都度更新すること。compact後の文脈復元にも使う。

---

## 直近の作業履歴

| コミット | 内容 |
|---|---|
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

- [ ] **ML学習の実行** — `pip install lightgbm scikit-learn` → `python scripts/train_ml.py --days 90`
  - lookahead bias修正・マーケット取得修正済み。初回学習が必要
  - 学習後に `python scripts/backtest.py --days 90 --limit 100` でバックテスト検証

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

  **③ `risk/risk_manager.py` — Kelly分率の動的調整**
  ```python
  if skill_score > 0.10:   kelly_fraction = 0.25   # 通常
  elif skill_score > 0.0:  kelly_fraction = 0.125  # 半分
  else:                    kelly_fraction = 0.0625 # 1/4（LLM有害期）
  ```

  **④ `runner/orchestrator.py` — 呼び出しポイント**
  - LLMシグナル生成後 → `brier_tracker.record_prediction()`
  - `_check_resolved_markets()` 解決後 → `brier_tracker.record_outcome()`
  - skill_score を Bayesian・RiskManager に渡す
  - skill_score < 0 かつ サンプル数 >= 20 → LLMシグナルをブロック（HOLD返却）

  **⑤ ダッシュボード表示**
  - stats bar に `LLM Skill` を追加（例: `+0.12` なら緑、`-0.05` なら赤）

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
