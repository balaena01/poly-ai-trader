# Poly AI Trader

Polymarket AI 自動売買システム

## アーキテクチャ

```
┌────────────────────────────────────────────────────────────────┐
│                      Poly AI Trader                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              リアルタイム層 (常時稼働)                   │   │
│  │  ┌──────────────┐    ┌──────────────┐                   │   │
│  │  │  WebSocket   │───▶│   Executor   │                   │   │
│  │  │  価格監視    │    │   即時売買   │                   │   │
│  │  └──────────────┘    └──────────────┘                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ シグナル & トリガー条件            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              分析層 (5-240分間隔)                        │   │
│  │  ┌────────┐  ┌──────────┐  ┌────────┐  ┌────────────┐   │   │
│  │  │ News   │─▶│ Analyst  │─▶│Auditor │─▶│Risk Manager│   │   │
│  │  │Fetcher │  │LLM+ML+OF │  │  監査  │  │  リスク    │   │   │
│  │  └────────┘  └──────────┘  └────────┘  └────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ バックグラウンド更新               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              学習層 (バックグラウンド)                   │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ Factor Miner → Backtest → Auto-Killer            │   │   │
│  │  │                          (50トレードごと)         │   │   │
│  │  ├──────────────────────────────────────────────────┤   │   │
│  │  │ ML Retrainer → LightGBM学習 → Hot-swap           │   │   │
│  │  │                          (20マーケット解決ごと)   │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

## 実行フロー

```
Binance/Polymarket スキャン → BTC/ETH価格取得
    ↓
LLM + ML + Orderflow 分析 (5-240分間隔、解決時間に応じて可変)
    ↓
シグナル生成 → トリガー条件セット
    ↓
WebSocket 常時監視
    ↓
条件一致 → 即座に売買
```

| 処理 | 頻度 | 方式 |
|------|------|------|
| LLM+ML+Orderflow 分析 | 5-240分 (ルールベース可変) | バッチ |
| 価格監視 | 常時 | WebSocket |
| 売買執行 | 条件一致時 | 即時 |
| Factor Miner | 50トレードごと | バックグラウンド |
| ML再学習 + ホットスワップ | 20マーケット解決ごと | バックグラウンド (ThreadPoolExecutor) |

**分析間隔の自動調整:**
```python
解決まで < 2時間  → 5分間隔
解決まで < 24時間 → 15分間隔
解決まで < 7日    → 60分間隔
それ以上          → 4時間間隔
```

## クイックスタート

```bash
# インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# POLY_PRIVATE_KEY, POLY_FUNDER_ADDRESS, ANTHROPIC_API_KEY を設定

# マーケットスキャン
python main.py scan

# LLM分析
python main.py analyze -n 5

# 自動売買 (ドライラン、ダッシュボード自動起動)
python main.py run

# 自動売買 (本番)
python main.py run --live

# ダッシュボードなし
python main.py run --no-dashboard

# ML自動再学習を無効化
python main.py run --no-retrain
```

## ダッシュボード

```bash
python main.py run
# → http://localhost:8080
```

ダッシュボードはデフォルトで有効。無効にする場合は `--no-dashboard`。

リアルタイム表示:
- **Live Signals**: LLM+ML+Orderflow 分析結果
- **Active Triggers**: 待機中の注文
- **Trade History**: 取引履歴
- **Edge Distribution**: エッジの推移グラフ

## MLモデル

LightGBM モデルは 2 通りの方法で学習されます。

### 手動学習

```bash
python scripts/train_ml.py --days 30
# → models/lgb_model.pkl に保存
```

`models/lgb_model.pkl` が存在すれば起動時に自動でロードされ、ML分析が有効になります。

### 自動再学習 (稼働中)

20 マーケット解決ごとに自動で再学習が走ります。

```
マーケット解決 20件
  → 解決済みデータを収集 (Polymarket API)
  → 価格履歴を取得 (非同期)
  → LightGBM 再学習 (ThreadPoolExecutor でバックグラウンド実行)
  → モデルをホットスワップ (メインループを止めない)
```

無効にする場合: `python main.py run --no-retrain`

## データ取得

```bash
# 過去価格データ取得
python -m data_fetcher.history --days 30 --limit 10

# ニュース検索 (Google News)
python -m data_fetcher.news_fetcher --query "Bitcoin price"

# マーケット用ニュース
python -m data_fetcher.news_fetcher --market "Will BTC reach $100k?"
```

## 学習層 (Factor Manager)

```bash
# ファクター生成
python -m factor.miner --market "Will BTC hit 100k?"

# バックテスト
python -m factor.backtester --market "Will BTC hit 100k?"

# ファクター管理
python -m factor.manager --list        # 一覧
python -m factor.manager --stats       # 統計
python -m factor.manager --leaderboard # ランキング
python -m factor.manager --evaluate    # 評価・淘汰
python -m factor.manager --mine "コンテキスト"  # 新規生成
```

**自動動作:**
- 50トレード成功ごとに `mine_new_factor()` がバックグラウンドで実行
- IC > 0.05 のファクターのみ採用
- 5連敗 or IC不足で自動淘汰
- ファクターは `data/factors/factors.json` に永続化、再起動後も復元

## 環境変数

```bash
# Polymarket
POLY_PRIVATE_KEY=0x...
POLY_FUNDER_ADDRESS=0x...

# LLM (LiteLLM 自動読み込み)
ANTHROPIC_API_KEY=sk-ant-api03-xxx
```

## LLM モデル

| エイリアス | モデル | 価格 |
|-----------|--------|------|
| `claude-haiku-4.5` | claude-haiku-4-5 | $1/MTok (デフォルト) |
| `claude-sonnet-4.6` | claude-sonnet-4-6 | $3/MTok |
| `gpt-4o-mini` | gpt-4o-mini | $0.15/MTok |

## ディレクトリ構成

```
poly-ai-trader/
├── client/           # Polymarket API
├── scanner/          # 市場監視 (Polymarket + Binance価格)
├── analyst/          # LLM + ML + Orderflow + Bayesian
├── executor/         # 注文実行
├── risk/             # リスク管理 + 監査
├── factor/           # 自動学習 (Factor Miner + Auto-Killer)
├── data_fetcher/     # データ取得
│   ├── history.py        # 過去価格 (Polymarket API)
│   ├── websocket_client.py  # リアルタイム (WebSocket)
│   └── news_fetcher.py   # ニュース (Google News RSS)
├── dashboard/        # Web UI (Cyberpunk theme)
│   └── server.py         # FastAPI + WebSocket
├── runner/           # オーケストレーター
│   └── orchestrator.py   # 3層統合ランナー
├── scripts/
│   └── train_ml.py       # MLモデル手動学習スクリプト
├── models/           # 学習済みモデル (lgb_model.pkl)
├── data/
│   ├── historical/   # 過去価格データ
│   ├── news/         # ニュースキャッシュ
│   └── factors/      # ファクターDB (factors.json)
└── main.py           # CLI
```

## 開発ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| 1 | Scanner + Analyst + Executor | ✅ |
| 2 | LightGBM + Orderflow + Bayesian + ML自動再学習 | ✅ |
| 3 | Risk Manager + Auditor | ✅ |
| 4 | Factor Miner + Auto-learning | ✅ |

詳細: [docs/ROADMAP.md](docs/ROADMAP.md)

## 注意事項

- **秘密鍵の管理**: `.env` に保存、`.gitignore` に追加済み
- **リスク**: 予測市場は投機的。余剰資金で
- **ドライラン**: デフォルトで有効。`--live` で本番実行
- **ML再学習**: 解決済みマーケットが50件以上ないとモデルが学習されない
