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
│  │              分析層 (5-60分間隔)                         │   │
│  │  News ──▶ Analyst ──▶ Auditor ──▶ Risk Manager          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ 戦略更新 (50トレードごと)          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              学習層 (バックグラウンド)                   │   │
│  │  Factor Miner ──▶ Backtest ──▶ Auto-Killer              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 実行モデル

| 層 | 処理 | 頻度 | 方式 |
|----|------|------|------|
| リアルタイム | 価格監視・売買 | 常時 | WebSocket |
| 分析 | LLM予測・シグナル生成 | 5-60分 | バッチ |
| 学習 | 戦略生成・淘汰 | 50トレードごと | バックグラウンド |

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

**設計思想:** LLMは「戦略家」、WebSocketは「執行官」

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

**目標:** 複数シグナルの組み合わせ + Bayesian統合

### 追加コンポーネント

| 名前 | 説明 |
|------|------|
| LightGBM Model | 30特徴量、500ツリーの確率出力 |
| Orderflow Detector | クジラ検出、流動性シフト、大口注文クラスタ |
| Bayesian Aggregator | 複数シグナルの確率的統合 |

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

### ファイル構成
```
analyst/
├── llm_analyst.py      # LLM
├── ml_analyst.py       # LightGBM
├── orderflow.py        # オーダーフロー
├── bayesian.py         # Bayesian統合
├── ensemble.py         # 全シグナル統合
└── features.py         # 30特徴量
```

---

## Phase 3: リスク管理 ✅ 完了

**目標:** 資金管理とリスク制御

### 追加コンポーネント

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

### 追加コンポーネント

| 名前 | 説明 |
|------|------|
| Factor Miner | LLM仮説生成 + バックテスト |
| Auto-Killer | 性能不良ファクターの自動除去 |

### ファクター管理
- 最大10アクティブファクター
- IC > 0.05 で採用
- 50トレード後に評価
- 5連敗 or IC不足で淘汰

### ファイル構成
```
factor/
├── miner.py            # 仮説生成
├── backtester.py       # バックテスト
└── manager.py          # ファクター管理
```

---

## データ取得 ✅ 完了

### コンポーネント

| 名前 | 説明 |
|------|------|
| PriceHistoryFetcher | Polymarket過去価格 (/prices-history) |
| PolyWebSocket | リアルタイム価格ストリーム |
| NewsFetcher | Scrapling + Google News |

### Polymarket API

| 機能 | エンドポイント | レート制限 |
|------|---------------|-----------|
| 過去価格 | `/prices-history` | 1,000 req/10s |
| オーダーブック | `/book` | 1,500 req/10s |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | - |

### ニュースソース
- **Scrapling対応**: Decrypt, CoinDesk, CoinTelegraph, TheBlock
- **Scrapling不要**: Google News RSS

### ファイル構成
```
data_fetcher/
├── history.py          # 過去価格
├── websocket_client.py # WebSocket
└── news_fetcher.py     # ニュース (Scrapling/Google)
```

---

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| 言語 | Python 3.9+ |
| ML | LightGBM |
| LLM | LiteLLM (Anthropic, OpenAI, Groq) |
| スクレイピング | Scrapling (ステルスモード) |
| 価格データ | Polymarket WebSocket |
| 執行 | py-clob-client |

### LLM モデル

| エイリアス | モデル | 価格 | 用途 |
|-----------|--------|------|------|
| `claude-haiku-4.5` | claude-haiku-4-5 | $1/MTok | デフォルト分析 |
| `claude-sonnet-4.6` | claude-sonnet-4-6 | $3/MTok | 高精度分析 |
| `gpt-4o-mini` | gpt-4o-mini | $0.15/MTok | 低コスト |

---

## マイルストーン

| Phase | 目標 | 状態 |
|-------|------|------|
| 1 | MVP | ✅ 完了 |
| 2 | シグナル強化 | ✅ 完了 |
| 3 | リスク管理 | ✅ 完了 |
| 4 | 自動学習 | ✅ 完了 |
| - | データ取得 | ✅ 完了 |

---

## 参考リンク

- [元ツイート](https://x.com/0xcristal/status/2033122263365804181)
- [Polymarket Docs](https://docs.polymarket.com/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Scrapling](https://github.com/D4Vinci/Scrapling)
