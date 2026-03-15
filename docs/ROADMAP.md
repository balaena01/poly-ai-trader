# Poly AI Trader - 開発ロードマップ

**参考:** https://x.com/0xcristal/status/2033122263365804181

---

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────┐
│                     Poly AI Trader                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────┐    ┌─────────────┐    ┌─────────┐             │
│  │ SCANNER │───▶│   ANALYST   │───▶│EXECUTOR │             │
│  └─────────┘    └─────────────┘    └─────────┘             │
│       │               │                 │                   │
│       ▼               ▼                 ▼                   │
│  ┌─────────┐    ┌─────────────┐    ┌─────────┐             │
│  │ FACTOR  │    │   AUDITOR   │    │  RISK   │             │
│  │  MINER  │    │             │    │ MANAGER │             │
│  └─────────┘    └─────────────┘    └─────────┘             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

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

### 使い方
```bash
python main.py scan          # スキャン
python main.py analyze -n 5  # 分析
python main.py trade --execute --dry-run  # ドライラン
python main.py run --interval 60  # 自動ループ
```

---

## Phase 2: シグナル強化 ✅ 完了

**目標:** 複数シグナルの組み合わせ + Bayesian統合

### 追加コンポーネント

| 名前 | 説明 |
|------|------|
| LightGBM Model | 30特徴量、500ツリーの確率出力 |
| Orderflow Detector | クジラ検出、流動性シフト、大口注文クラスタ |
| Bayesian Aggregator | 複数シグナルの確率的統合 |

### 実装内容
- [x] 特徴量エンジニアリング (30特徴量)
  - 価格モメンタム (1m, 5m, 15m, 1h)
  - ボラティリティ (ATR, Bollinger)
  - オーダーブック不均衡
  - ボリュームプロファイル
  - センチメント指標
- [x] LightGBM モデル学習
- [x] オーダーフロー検出
  - 大口注文 (> $10k)
  - Bid/Ask 不均衡
  - 流動性の急変
- [x] Bayesian Aggregation
  ```
  Market: 53% UP
  LLM Signal: 64%
  LightGBM: 69%
  Orderflow: 72%
  ↓
  Bayesian Posterior: 81%
  Final: 76.9%
  Edge: 23.9%
  ```

### ファイル構成
```
analyst/
├── llm_analyst.py      # 既存
├── ml_analyst.py       # NEW: LightGBM
├── orderflow.py        # NEW: オーダーフロー
└── bayesian.py         # NEW: Bayesian統合
```

---

## Phase 3: リスク管理 🔜 次

**目標:** 資金管理とリスク制御

### 追加コンポーネント

| 名前 | 説明 |
|------|------|
| Risk Manager | Kelly, ドローダウン, 相関管理 |
| Auditor | ハルシネーション検出, 低流動性ブロック |

### 実装内容
- [ ] Quarter Kelly サイジング (改良版)
- [ ] 3連敗停止ルール
- [ ] 15%ドローダウン → 完全停止
- [ ] BTC/ETH 相関キャップ (同時エクスポージャー制限)
- [ ] 毎注文前のEV再計算
- [ ] Auditor
  - ハルシネーション/検証不能ニュースをフラグ
  - 解決まで10分未満のマーケットをブロック
  - 低流動性マーケットをブロック
  - フラグごとに信頼度8%ペナルティ

### ファイル構成
```
risk/
├── risk_manager.py     # リスク管理
└── auditor.py          # 監査
```

---

## Phase 4: 自動学習

**目標:** 戦略の自動生成と淘汰

### 追加コンポーネント

| 名前 | 説明 |
|------|------|
| Factor Miner | 仮説生成 + バックテスト |
| Auto-Killer | 性能不良ファクターの自動除去 |

### 実装内容
- [ ] Factor Miner
  - Claude Haiku ($0.25/1M tokens) で仮説生成
  - バックテスト実行
  - IC > 0.05 のファクターのみ保持
  - 10個のアクティブファクター管理
- [ ] Auto-Killer
  - 50トレード後に性能評価
  - 基準未達のファクターを自動削除
- [ ] ファクター管理DB
  - 生成日時
  - パフォーマンス履歴
  - IC, Sharpe, Win Rate

### ファイル構成
```
factor/
├── miner.py            # 仮説生成
├── backtester.py       # バックテスト
└── manager.py          # ファクター管理
```

---

## 技術スタック

| カテゴリ | 技術 |
|---------|------|
| 言語 | Python 3.9+ |
| ML | LightGBM |
| LLM | Claude (Haiku/Sonnet) via OpenRouter |
| エージェント | LangGraph (Phase 4) |
| 価格データ | Binance WebSocket |
| 執行 | py-clob-client / Polymarket CLI (Rust) |
| ウォレット | Coinbase Agentic Wallet (TEE) ※検討中 |

---

## マイルストーン

| Phase | 目標 | 工数目安 |
|-------|------|---------|
| 1 | MVP | ✅ 完了 |
| 2 | シグナル強化 | ✅ 完了 |
| 3 | リスク管理 | 🔜 次 |
| 4 | 自動学習 | 予定 |

---

## 参考リンク

- [元ツイート](https://x.com/0xcristal/status/2033122263365804181)
- [Polymarket Docs](https://docs.polymarket.com/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [LightGBM](https://lightgbm.readthedocs.io/)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
