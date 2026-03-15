# Poly AI Trader

Polymarket 自動売買システム

## セットアップ

### 1. 依存関係インストール
```bash
pip install -r requirements.txt
```

### 2. 環境変数設定
```bash
cp .env.example .env
# .env を編集して秘密鍵を設定
```

### 3. ウォレット準備
- Polygon (MATIC) ウォレットが必要
- USDC (Polygon) を入金
- Polymarket で Token Allowance を設定

## 使い方

### マーケット検索
```bash
# アクティブマーケット一覧
python main.py markets

# キーワード検索
python main.py markets -q "Trump"

# 件数指定
python main.py markets -q "Bitcoin" -n 20
```

### 価格確認
```bash
python main.py price "Will Trump win"
```

### 買い注文
```bash
# 指値 (50%で$10分)
python main.py buy <token_id> 10 -p 0.50 --confirm

# 成行
python main.py buy <token_id> 10 --confirm
```

### 売り注文
```bash
python main.py sell <token_id> 10 -p 0.60 --confirm
```

## Pythonから使う

```python
from client import PolyClient

# 読み取り専用
client = PolyClient()
client.connect(read_only=True)

# マーケット検索
markets = client.search_markets("Trump", limit=5)
for m in markets:
    print(f"{m.question}: YES={client.get_midpoint(m.yes_token_id):.1%}")

# 認証付き (取引する場合)
client = PolyClient(
    private_key="0x...",
    funder="0x...",
)
client.connect()

# 買い注文
result = client.buy(token_id="xxx", amount=10, price=0.50)
print(result)
```

## アーキテクチャ

```
poly-ai-trader/
├── client/
│   ├── __init__.py
│   └── polymarket.py    # Polymarket API クライアント
├── strategies/          # 売買戦略 (TODO)
├── main.py              # CLI エントリーポイント
├── requirements.txt
└── .env.example
```

## 必要なもの

1. **Polygonウォレット**
   - MetaMask等で作成
   - 秘密鍵をエクスポート

2. **USDC (Polygon)**
   - 取引所からPolygonネットワークで送金
   - または Bridge で変換

3. **Token Allowance**
   - Polymarket サイトで初回設定必要
   - https://polymarket.com

## 注意事項

- **秘密鍵の管理**: .env に保存し、.gitignore に追加
- **リスク**: 予測市場は投機的。余剰資金で
- **規制**: 地域によっては利用制限あり

## 今後の予定

- [ ] 戦略エンジン (AI分析)
- [ ] バックテスト機能
- [ ] 自動売買ループ
- [ ] Discord通知
- [ ] ダッシュボード
