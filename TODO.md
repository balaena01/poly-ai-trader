# Poly AI Trader - TODO

コード変更の都度更新すること。compact後の文脈復元にも使う。

---

## 直近の作業履歴

| コミット | 内容 |
|---|---|
| (最新) | fix: ML学習データ lookahead bias修正 + マーケット取得ロジック統一 |
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

## 未対応バグ・懸念点

### 高優先度

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

## 今後やりたいこと (バックログ)

- [ ] **ML学習の実行** — `pip install lightgbm scikit-learn` → `python scripts/train_ml.py --days 90`
  - lookahead bias修正・マーケット取得修正済み。初回学習が必要
  - 学習後に `python scripts/backtest.py --days 90 --limit 100` でバックテスト検証



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
│   ├── llm_analyst.py   # LLM分析 (LiteLLM)
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
