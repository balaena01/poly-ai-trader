# Poly AI Trader - TODO

コード変更の都度更新すること。compact後の文脈復元にも使う。

---

## 直近の作業履歴

| コミット | 内容 |
|---|---|
| `fdf5dc4` | トレードロジック 高・中バグ8件修正 |
| `c343fc6` | 深刻度「中」バグ4件修正 (Auditor/タイムゾーン等) |
| `ebc5957` | README・ROADMAP 全面更新 |
| `9a7a8e8` | ML自動再学習 + ホットスワップ実装 |
| `a4f6ef8` | 学習層 (Factor Manager) の機能不全修正 |
| `48501f7` | ドキュメント齟齬修正 + バグ修正 |

---

## 未対応バグ・懸念点

### 低優先度

- [ ] **⑩ Whale閾値の絶対値固定** (`analyst/orderflow.py:72`)
  - `whale_threshold_usd = $10,000` ハードコード
  - 流動性の小さいマーケットでは全トレードがwhale判定される
  - 対策案: 24h出来高の1%などを相対閾値にする

- [ ] **⑪ max_position_pct の二重定義** (`executor/trade_executor.py` / `risk/risk_manager.py`)
  - 両ファイルにそれぞれ独立してポジション上限が存在
  - 値が乖離した場合にどちらが優先されるか不明
  - 対策案: executor は risk_manager の値を参照するよう統一

### 設計レベル (要検討・手を入れるか判断待ち)

- [ ] **Bayesian二重カウントの根本解決**
  - LLMの確率を LightGBM の特徴量 (`llm_prediction`) として使っているため
    Bayesian集計でLLMが二重にカウントされている
  - 暫定対応済み: LightGBM accuracy を 0.60→0.55 に引き下げ (`fdf5dc4`)
  - 根本解決: LLM特徴量を ML から除外し完全独立にする
    → モデル再学習が必要。運用データが溜まってから検討

- [ ] **トリガー即時発火の約定率**
  - `target_price = current_price` に変更済み (`fdf5dc4`)
  - WebSocketの価格更新タイミング次第で「シグナル生成から発火まで数分」のラグが発生しうる
  - 監視: 約定率・スリッページをログで確認

---

## 今後やりたいこと (バックログ)

- [ ] **実運用ログの整備**
  - 現在は print() のみ。ファイルへの構造化ログ (JSON Lines) がほしい
  - シグナル・トリガー・約定・解決を1行1レコードで残す

- [ ] **バックテスト基盤**
  - 過去の解決済みマーケットデータで戦略全体をバックテストできる仕組みがない
  - factor/backtester.py は個別ファクター用。エンド・ツー・エンドのバックテストは未実装

- [ ] **ポジション管理 UI の強化**
  - ダッシュボードにポジション一覧 (エントリー価格・含み損益) を追加したい

- [ ] **ML特徴量の volume データ改善**
  - 再学習時 (`_retrain_ml_model`) に volume 履歴が取れない
  - Polymarket の `/prices-history` は volume を返さない。別途 `/trades` エンドポイントから集計が必要

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
│   └── features.py      # 30特徴量 (buy_volume_ratio等 修正済み)
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
│   └── train_ml.py      # 手動ML学習
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
```
