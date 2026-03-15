# Poly AI Trader

Polymarket AI 自動売買システム

## 特徴

- **Scanner**: Polymarket + Binance リアルタイム監視
- **Analyst**: LLM + LightGBM + Orderflow の Bayesian 統合
- **Executor**: 自動注文実行 (ドライラン対応)

## クイックスタート

```bash
# インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env を編集

# マーケットスキャン
python main.py scan

# LLM分析
python main.py analyze -n 5

# 取引 (ドライラン)
python main.py trade --execute

# 自動ループ (60分間隔)
python main.py run --interval 60
```

## 環境変数

```bash
# Polymarket
POLY_PRIVATE_KEY=0x...
POLY_FUNDER_ADDRESS=0x...

# LLM (LiteLLM 自動読み込み)
ANTHROPIC_API_KEY=sk-ant-api03-xxx
# または
OPENAI_API_KEY=sk-xxx
GROQ_API_KEY=gsk_xxx
```

## LLM モデル

```bash
# 利用可能なモデル一覧
python main.py models
```

| エイリアス | モデル | 価格 |
|-----------|--------|------|
| `claude-haiku-4.5` | claude-haiku-4-5 | $1/MTok (デフォルト) |
| `claude-sonnet-4.6` | claude-sonnet-4-6 | $3/MTok |
| `claude-opus-4.6` | claude-opus-4-6 | $5/MTok |
| `gpt-4o-mini` | gpt-4o-mini | $0.15/MTok |
| `groq/llama-70b` | Llama 3.1 70B | 無料枠あり |

```bash
# モデル指定
python main.py analyze -m claude-sonnet-4.6 -n 3
```

## アーキテクチャ

```
poly-ai-trader/
├── client/
│   └── polymarket.py       # Polymarket API
├── scanner/
│   └── market_scanner.py   # Binance + Polymarket 監視
├── analyst/
│   ├── llm_analyst.py      # LLM (LiteLLM)
│   ├── ml_analyst.py       # LightGBM
│   ├── orderflow.py        # クジラ/流動性検出
│   ├── bayesian.py         # Bayesian統合
│   ├── ensemble.py         # 全シグナル統合
│   └── features.py         # 30特徴量
├── executor/
│   └── trade_executor.py   # 注文実行
├── models/                 # 学習済みモデル
├── docs/
│   └── ROADMAP.md          # 開発計画
└── main.py                 # CLI
```

## シグナル統合 (Bayesian)

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

## 開発ロードマップ

詳細: [docs/ROADMAP.md](docs/ROADMAP.md)

| Phase | 内容 | 状態 |
|-------|------|------|
| 1 | Scanner + Analyst + Executor | ✅ |
| 2 | LightGBM + Orderflow + Bayesian | ✅ |
| 3 | Risk Manager + Auditor | 🔜 |
| 4 | Factor Miner + Auto-learning | 予定 |

## 注意事項

- **秘密鍵の管理**: `.env` に保存、`.gitignore` に追加済み
- **リスク**: 予測市場は投機的。余剰資金で
- **規制**: 地域によっては利用制限あり
- **ドライラン**: デフォルトで有効。`--live` で本番実行
