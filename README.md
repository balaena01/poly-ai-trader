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
│  │              分析層 (5-60分間隔)                         │   │
│  │  ┌────────┐  ┌──────────┐  ┌────────┐  ┌────────────┐   │   │
│  │  │ News   │─▶│ Analyst  │─▶│Auditor │─▶│Risk Manager│   │   │
│  │  │Fetcher │  │LLM+ML+OF │  │  監査  │  │  リスク    │   │   │
│  │  └────────┘  └──────────┘  └────────┘  └────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            ▲                                    │
│                            │ 戦略更新 (50トレードごと)          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              学習層 (バックグラウンド)                   │   │
│  │  ┌──────────────┐    ┌──────────────┐                   │   │
│  │  │ Factor Miner │───▶│ Auto-Killer  │                   │   │
│  │  │  戦略生成    │    │  戦略淘汰    │                   │   │
│  │  └──────────────┘    └──────────────┘                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

## 実行フロー

```
LLM分析 (5-60分間隔、解決時間に応じて可変)
    ↓
シグナル生成 → トリガー条件セット
    ↓
WebSocket 常時監視
    ↓
条件一致 → 即座に売買
```

| 処理 | 頻度 | 方式 |
|------|------|------|
| LLM分析 | 5-60分 (ルールベース可変) | バッチ |
| 価格監視 | 常時 | WebSocket |
| 売買執行 | 条件一致時 | 即時 |
| 戦略更新 | 50トレードごと | Factor Miner |

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
pip install scrapling  # ニュース取得用 (オプション)

# 環境変数設定
cp .env.example .env

# マーケットスキャン
python main.py scan

# LLM分析
python main.py analyze -n 5

# 取引 (ドライラン)
python main.py trade --execute

# 自動ループ
python main.py run
```

## データ取得

```bash
# 過去価格データ取得
python -m data_fetcher.history --days 30 --limit 10

# ニュース検索 (Google News)
python -m data_fetcher.news_fetcher --query "Bitcoin price"

# マーケット用ニュース
python -m data_fetcher.news_fetcher --market "Will BTC reach $100k?"
```

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
├── scanner/          # 市場監視
├── analyst/          # LLM + ML + Orderflow + Bayesian
├── executor/         # 注文実行
├── risk/             # リスク管理 + 監査
├── factor/           # 自動学習
├── data_fetcher/     # データ取得
│   ├── history.py        # 過去価格 (Polymarket API)
│   ├── websocket_client.py  # リアルタイム (WebSocket)
│   └── news_fetcher.py   # ニュース (Scrapling/Google)
├── data/
│   ├── historical/   # 過去価格データ
│   ├── news/         # ニュースキャッシュ
│   └── factors/      # ファクターDB
└── main.py           # CLI
```

## 開発ロードマップ

| Phase | 内容 | 状態 |
|-------|------|------|
| 1 | Scanner + Analyst + Executor | ✅ |
| 2 | LightGBM + Orderflow + Bayesian | ✅ |
| 3 | Risk Manager + Auditor | ✅ |
| 4 | Factor Miner + Auto-learning | ✅ |

詳細: [docs/ROADMAP.md](docs/ROADMAP.md)

## 注意事項

- **秘密鍵の管理**: `.env` に保存、`.gitignore` に追加済み
- **リスク**: 予測市場は投機的。余剰資金で
- **ドライラン**: デフォルトで有効。`--live` で本番実行
