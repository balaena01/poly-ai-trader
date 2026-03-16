# Poly AI Trader - 開発ロードマップ

**参考:** https://x.com/0xcristal/status/2033122263365804181

---

## アーキテクチャ概要

```
┌────────────────────────────────────────────────────────────────┐
│                      Poly AI Trader                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              リアルタイム層 (常時稼働)                   │   │
│  │  WebSocket ──▶ 価格監視 ──▶ トリガー判定 ──▶ 即時売買   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ シグナル & トリガー条件            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              分析層 (5-240分間隔)                        │   │
│  │  News ──▶ Analyst (LLM+ML+OF) ──▶ Auditor ──▶ Risk Mgr │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ バックグラウンド更新               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              学習層 (バックグラウンド)                   │   │
│  │  Factor Miner ──▶ Backtest ──▶ Auto-Killer              │   │
│  │                              (50トレードごと)            │   │
│  │  ML Retrainer ──▶ LightGBM学習 ──▶ Hot-swap             │   │
│  │                              (20マーケット解決ごと)      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 実行モデル

| 層 | 処理 | 頻度 | 方式 |
|----|------|------|------|
| リアルタイム | 価格監視・売買 | 常時 | WebSocket |
| 分析 | LLM+ML+Orderflow 予測・シグナル生成 | 5-240分 | バッチ |
| 学習 (Factor) | 戦略生成・淘汰 | 50トレードごと | バックグラウンド |
| 学習 (ML) | LightGBM再学習・ホットスワップ | 20マーケット解決ごと | ThreadPoolExecutor |

### 分析間隔の自動調整 (ルールベース)

```python
def get_analysis_interval(market) -> int:
    """分析間隔 (分)"""
    time_to_resolution = market.end_date - datetime.now()

    if time_to_resolution < timedelta(hours=2):
        return 5     # 解決直前
    elif time_to_resolution < timedelta(hours=24):
        return 15    # 24時間以内
    elif time_to_resolution < timedelta(days=7):
        return 60    # 1週間以内
    else:
        return 240   # それ以上
```

**設計思想:** LLMは「戦略家」、WebSocketは「執行官」、学習層は「改良担当」

---

## Phase 1: MVP ✅ 完了

**目標:** 最小限の動作システム

### コンポーネント

| 名前 | 状態 | 説明 |
|------|------|------|
| Scanner | ✅ | Polymarket + Binance 監視 |
| Analyst (LLM) | ✅ | Claude/OpenAI で確率予測 |
| Executor | ✅ | 注文実行 + ドライラン |

### 機能
- [x] Polymarket BTC/ETH マーケット取得
- [x] Binance REST/WebSocket 価格取得
- [x] LLM 確率予測 + エッジ計算
- [x] Quarter Kelly ポジションサイジング
- [x] ドライランモード
- [x] CLI (scan, analyze, trade, run)

---

## Phase 2: シグナル強化 ✅ 完了

**目標:** 複数シグナルの組み合わせ + Bayesian統合 + ML自動再学習

### コンポーネント

| 名前 | 説明 |
|------|------|
| LightGBM Model | 30特徴量、500ツリーの確率出力 |
| Orderflow Detector | クジラ検出、流動性シフト、大口注文クラスタ |
| Bayesian Aggregator | 複数シグナルの確率的統合 |
| ML Retrainer | 解決済みデータで自動再学習 + ホットスワップ |

### Bayesian統合例
```
Market:     53% UP
LLM:        64%
LightGBM:   69%
Orderflow:  72%
    ↓
Posterior:  81%
Final:      76.9%
Edge:       +23.9%
```

### ML自動再学習フロー

```
マーケット解決 20件ごと
  ↓ asyncio.create_task() でバックグラウンド起動
  ↓ 解決済みマーケットを API から収集 (run_in_executor)
  ↓ 各マーケットの価格履歴を非同期取得 (await, レート制限付き)
  ↓ 特徴量抽出 + train/val split
  ↓ LightGBM 学習 (ThreadPoolExecutor — メインループをブロックしない)
  ↓ models/lgb_model.pkl に保存
  ↓ EnsembleAnalyst.reload_ml_model() でホットスワップ
```

- 最小データ数: 50件 (未満の場合はスキップ)
- `--no-retrain` で無効化可能
- `models/lgb_model.pkl` が存在すれば起動時にも自動ロード

### ファイル構成
```
analyst/
├── llm_analyst.py      # LLM
├── ml_analyst.py       # LightGBM (save_model / reload)
├── orderflow.py        # オーダーフロー
├── bayesian.py         # Bayesian統合
├── ensemble.py         # 全シグナル統合 + reload_ml_model()
└── features.py         # 30特徴量

scripts/
└── train_ml.py         # 手動学習スクリプト

models/
└── lgb_model.pkl       # 学習済みモデル (自動再学習で上書き)
```

---

## Phase 3: リスク管理 ✅ 完了

**目標:** 資金管理とリスク制御

### コンポーネント

| 名前 | 説明 |
|------|------|
| Risk Manager | Kelly, ドローダウン, 相関管理 |
| Auditor | ハルシネーション検出, 低流動性ブロック |

### リスクルール
| ルール | 設定 |
|--------|------|
| Kelly | Quarter Kelly (25%) |
| 最大ポジション | 10% |
| 連敗停止 | 3連敗 |
| ドローダウン | 15%で完全停止 |
| 相関キャップ | 20% |

### Auditorフラグ
| フラグ | ペナルティ | ブロック |
|--------|-----------|---------|
| ハルシネーション | 20% | ✗ |
| 検証不能 | 10% | ✗ |
| 低流動性 (<$10k) | 8% | **✓** |
| 解決間近 (<10分) | 15% | **✓** |

### ファイル構成
```
risk/
├── risk_manager.py     # リスク管理
└── auditor.py          # 監査
```

---

## Phase 4: 自動学習 ✅ 完了

**目標:** 戦略の自動生成と淘汰

### コンポーネント

| 名前 | 説明 |
|------|------|
| Factor Miner | LLM仮説生成 + バックテスト |
| Auto-Killer | 性能不良ファクターの自動除去 |

### ファクター管理
- 最大10アクティブファクター
- IC > 0.05 で採用
- **50トレード成功ごとに** `mine_new_factor()` がバックグラウンドで実行
- 5連敗 or IC不足で自動淘汰
- マーケット解決時に PnL を後付け更新して IC を再計算
- `data/factors/factors.json` に永続化 (再起動後も復元)

### ファクター記録フロー

```
トレード発火 → record_trade(pnl=0, market_id=...)  # エントリー時点
    ↓
マーケット解決 → update_pnl_by_market(market_id, pnl)  # 実際のPnLで更新
    ↓
IC再計算 → _check_and_kill()  # 基準未達なら自動淘汰
```

### ファイル構成
```
factor/
├── miner.py            # 仮説生成
├── backtester.py       # バックテスト (仮説IDシードで再現性確保)
└── manager.py          # ファクター管理 + update_pnl_by_market()
```

---

## データ取得 ✅ 完了

### コンポーネント

| 名前 | 説明 |
|------|------|
| PriceHistoryFetcher | Polymarket過去価格 (/prices-history) |
| PolyWebSocket | リアルタイム価格・取引ストリーム |
| NewsFetcher | Google News RSS (+ Scrapling対応) |

### Polymarket API

| 機能 | エンドポイント | レート制限 |
|------|---------------|-----------|
| 過去価格 | `/prices-history` | 1,000 req/10s |
| オーダーブック | `/book` | 1,500 req/10s |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | - |

### ニュースソース
- **Scrapling対応**: Decrypt, CoinDesk, CoinTelegraph, TheBlock
- **Scrapling不要**: Google News RSS (デフォルト)

### ファイル構成
```
data_fetcher/
├── history.py          # 過去価格
├── websocket_client.py # WebSocket (価格・取引ストリーム)
└── news_fetcher.py     # ニュース (Scrapling/Google)
```

---

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| 言語 | Python 3.10+ |
| ML | LightGBM |
| LLM | LiteLLM (Anthropic, OpenAI, Groq) |
| スクレイピング | Scrapling (ステルスモード) |
| 価格データ | Polymarket WebSocket + Binance REST |
| 執行 | py-clob-client |
| 非同期 | asyncio + ThreadPoolExecutor (CPU bound処理) |

### LLM モデル

| エイリアス | モデル | 価格 | 用途 |
|-----------|--------|------|------|
| `claude-haiku-4.5` | claude-haiku-4-5 | $1/MTok | デフォルト分析 |
| `claude-sonnet-4.6` | claude-sonnet-4-6 | $3/MTok | 高精度分析 |
| `gpt-4o-mini` | gpt-4o-mini | $0.15/MTok | 低コスト |

---

## ダッシュボード ✅ 完了

**リアルタイム Web UI** (Cyberpunk × Bloomberg Terminal)

```bash
python main.py run        # ダッシュボード自動起動
# → http://localhost:8080

python main.py run --no-dashboard  # 無効化
```

### 機能

| パネル | 説明 |
|--------|------|
| Live Signals | LLM+ML+Orderflow 分析結果をリアルタイム表示 |
| Active Triggers | 待機中の注文 |
| Trade History | 取引履歴 |
| Edge Distribution | エッジの推移グラフ (Chart.js) |
| Stats | Balance, PnL, Trades, Triggers |

### 技術

- **Frontend**: HTML/CSS/JS (インラインSPA)
- **Backend**: FastAPI + WebSocket
- **Font**: Orbitron + JetBrains Mono
- **Theme**: Cyberpunk (Neon Cyan/Magenta/Green)

---

## マイルストーン

| Phase | 目標 | 状態 |
|-------|------|------|
| 1 | MVP | ✅ 完了 |
| 2 | シグナル強化 + ML自動再学習 | ✅ 完了 |
| 3 | リスク管理 | ✅ 完了 |
| 4 | 自動学習 | ✅ 完了 |
| - | データ取得 | ✅ 完了 |
| - | ダッシュボード | ✅ 完了 |

---

## 参考リンク

- [元ツイート](https://x.com/0xcristal/status/2033122263365804181)
- [Polymarket Docs](https://docs.polymarket.com/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Scrapling](https://github.com/D4Vinci/Scrapling)
