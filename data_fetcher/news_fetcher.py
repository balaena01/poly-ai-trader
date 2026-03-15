"""
News Fetcher
- Scraplingを使ったニュース取得
- Polymarket予測用の情報収集
"""
import os
import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

# Scrapling (要インストール: pip install scrapling)
try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False
    print("Warning: scrapling not installed. Run: pip install scrapling")

# フォールバック用
import httpx


DATA_DIR = Path(__file__).parent.parent / "data" / "news"


@dataclass
class NewsArticle:
    """ニュース記事"""
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    summary: str = ""
    content: str = ""
    relevance_keywords: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
            "content": self.content[:500] if self.content else "",  # 最初の500文字
            "keywords": self.relevance_keywords,
        }


@dataclass 
class NewsContext:
    """LLM用ニュースコンテキスト"""
    market_question: str
    articles: List[NewsArticle]
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def to_prompt(self) -> str:
        """LLMプロンプト用に整形"""
        lines = [
            f"# Market Question: {self.market_question}",
            f"# News Context (fetched: {self.fetched_at.strftime('%Y-%m-%d %H:%M')})",
            "",
        ]
        
        for i, article in enumerate(self.articles[:10], 1):  # 最大10件
            lines.append(f"## [{i}] {article.title}")
            lines.append(f"Source: {article.source}")
            if article.published:
                lines.append(f"Date: {article.published.strftime('%Y-%m-%d')}")
            if article.summary:
                lines.append(f"Summary: {article.summary}")
            lines.append("")
        
        return "\n".join(lines)


class NewsFetcher:
    """ニュース取得"""
    
    # ニュースソース設定
    SOURCES = {
        "decrypt": {
            "url": "https://decrypt.co/news",
            "selectors": {
                "articles": "[class*='PostCard'], [class*='post-card'], article[class*='post']",
                "title": "h3, h2, [class*='title']",
                "link": "a[href*='/news/'], a[href*='/article/']",
                "summary": "p, [class*='excerpt'], [class*='summary']",
            }
        },
        "coindesk": {
            "url": "https://www.coindesk.com/latest-crypto-news",
            "selectors": {
                "articles": "[class*='article'], [class*='card'], [class*='story']",
                "title": "h2, h3, h4, [class*='headline']",
                "link": "a[href*='/20']",
                "summary": "p, [class*='excerpt']",
            }
        },
        "cointelegraph": {
            "url": "https://cointelegraph.com/tags/bitcoin",
            "selectors": {
                "articles": "[class*='post'], article",
                "title": "h2, h3, [class*='title']",
                "link": "a[href*='/news/']",
                "summary": "p, [class*='lead']",
            }
        },
        "theblock": {
            "url": "https://www.theblock.co/latest",
            "selectors": {
                "articles": "[class*='article'], [class*='story']",
                "title": "h2, h3, [class*='headline']",
                "link": "a[href*='/post/']",
                "summary": "p",
            }
        },
    }
    
    def __init__(self, save_dir: Path = None, use_stealth: bool = True):
        """
        初期化
        
        Args:
            save_dir: 保存ディレクトリ
            use_stealth: ステルスモード (アンチボット回避)
        """
        self.save_dir = save_dir or DATA_DIR
        self.use_stealth = use_stealth
        os.makedirs(self.save_dir, exist_ok=True)
    
    async def fetch_from_source(
        self,
        source: str,
        limit: int = 10,
    ) -> List[NewsArticle]:
        """
        特定ソースからニュース取得
        
        Args:
            source: ソース名 (decrypt, coindesk, etc.)
            limit: 最大取得件数
        
        Returns:
            List[NewsArticle]
        """
        if source not in self.SOURCES:
            print(f"❌ Unknown source: {source}")
            return []
        
        config = self.SOURCES[source]
        articles = []
        
        try:
            if SCRAPLING_AVAILABLE:
                articles = await self._fetch_with_scrapling(source, config, limit)
            else:
                articles = await self._fetch_with_httpx(source, config, limit)
        except Exception as e:
            print(f"❌ {source} 取得エラー: {e}")
        
        return articles
    
    async def _fetch_with_scrapling(
        self,
        source: str,
        config: Dict,
        limit: int,
    ) -> List[NewsArticle]:
        """Scraplingでフェッチ (スレッドで実行)"""
        import concurrent.futures
        
        url = config["url"]
        selectors = config["selectors"]
        
        print(f"🔍 {source}: {url}")
        
        # 同期処理をスレッドで実行
        def fetch_sync():
            if self.use_stealth:
                return StealthyFetcher.fetch(url, headless=True, network_idle=True)
            else:
                return Fetcher.fetch(url)
        
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            page = await loop.run_in_executor(pool, fetch_sync)
        
        articles = []
        seen_urls = set()
        
        # 全リンクを取得してフィルタリング
        all_links = page.css("a")
        
        for link_elem in all_links:
            try:
                href = link_elem.attrib.get("href", "")
                text = link_elem.text.strip() if link_elem.text else ""
                
                # 空リンクスキップ
                if not href or not text:
                    continue
                
                # 相対URL対応
                if not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                
                # 重複スキップ
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                # ニュース記事っぽいURLのみ
                article_patterns = ["/news/", "/article/", "/post/", "/20"]  # /2024/, /2025/ etc
                skip_patterns = ["/price", "/tag/", "/category/", "/author/", "/login", "/signup", "#"]
                
                is_article = any(p in href for p in article_patterns)
                should_skip = any(p in href for p in skip_patterns)
                
                if not is_article or should_skip:
                    continue
                
                # タイトル長チェック
                if len(text) < 15 or len(text) > 200:
                    continue
                
                articles.append(NewsArticle(
                    title=text,
                    url=href,
                    source=source,
                    summary="",
                ))
                
                if len(articles) >= limit:
                    break
                
            except Exception:
                continue
        
        print(f"  ✅ {len(articles)} 記事取得")
        return articles
    
    async def _fetch_with_httpx(
        self,
        source: str,
        config: Dict,
        limit: int,
    ) -> List[NewsArticle]:
        """httpxでフェッチ (フォールバック)"""
        url = config["url"]
        print(f"🔍 {source}: {url} (httpx fallback)")
        
        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible)"}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            
            # 簡易パース (Scraplingなしの場合は限定的)
            # 本格的にはBeautifulSoupを使うが、ここではプレースホルダー
            print(f"  ⚠️ Scrapling未インストール - 詳細パース不可")
            return []
    
    async def fetch_all(self, limit_per_source: int = 5) -> List[NewsArticle]:
        """
        全ソースからニュース取得
        
        Args:
            limit_per_source: ソースあたりの最大件数
        
        Returns:
            List[NewsArticle]
        """
        all_articles = []
        
        for source in self.SOURCES:
            articles = await self.fetch_from_source(source, limit_per_source)
            all_articles.extend(articles)
            await asyncio.sleep(1)  # レート制限対策
        
        return all_articles
    
    async def fetch_for_market(
        self,
        market_question: str,
        keywords: List[str] = None,
        limit: int = 10,
    ) -> NewsContext:
        """
        特定マーケット用のニュース取得
        
        Args:
            market_question: マーケットの質問
            keywords: 検索キーワード
            limit: 最大件数
        
        Returns:
            NewsContext
        """
        # キーワード抽出
        if not keywords:
            keywords = self._extract_keywords(market_question)
        
        print(f"🎯 マーケット: {market_question[:50]}...")
        print(f"   キーワード: {keywords}")
        
        # 全ソースから取得
        all_articles = await self.fetch_all(limit_per_source=5)
        
        # キーワードでフィルタリング
        relevant = []
        for article in all_articles:
            score = self._relevance_score(article, keywords)
            if score > 0:
                article.relevance_keywords = [
                    kw for kw in keywords 
                    if kw.lower() in article.title.lower() or kw.lower() in article.summary.lower()
                ]
                relevant.append((score, article))
        
        # スコア順でソート
        relevant.sort(key=lambda x: x[0], reverse=True)
        top_articles = [a for _, a in relevant[:limit]]
        
        print(f"   関連記事: {len(top_articles)}/{len(all_articles)}")
        
        return NewsContext(
            market_question=market_question,
            articles=top_articles,
        )
    
    def _extract_keywords(self, question: str) -> List[str]:
        """質問からキーワード抽出"""
        # 基本キーワード
        keywords = []
        
        # 仮想通貨関連
        crypto_keywords = ["BTC", "Bitcoin", "ETH", "Ethereum", "crypto", "cryptocurrency"]
        for kw in crypto_keywords:
            if kw.lower() in question.lower():
                keywords.append(kw)
        
        # 価格関連
        if any(w in question.lower() for w in ["price", "reach", "above", "below"]):
            keywords.append("price")
        
        # 数値抽出 (e.g., "$100,000")
        import re
        numbers = re.findall(r'\$?[\d,]+(?:\.\d+)?[kKmMbB]?', question)
        keywords.extend(numbers)
        
        # デフォルト
        if not keywords:
            keywords = ["Bitcoin", "crypto", "market"]
        
        return keywords
    
    def _relevance_score(self, article: NewsArticle, keywords: List[str]) -> int:
        """関連度スコア計算"""
        score = 0
        text = f"{article.title} {article.summary}".lower()
        
        for kw in keywords:
            if kw.lower() in text:
                score += 2 if kw.lower() in article.title.lower() else 1
        
        return score
    
    async def search(self, query: str, limit: int = 10) -> List[NewsArticle]:
        """
        統合検索 (Scrapling + Google News RSS)
        
        Args:
            query: 検索クエリ
            limit: 最大件数
        
        Returns:
            List[NewsArticle]
        """
        articles = []
        
        # 1. Scraplingで各ソースから取得 (タイムアウト付き)
        if SCRAPLING_AVAILABLE:
            try:
                scraped = await asyncio.wait_for(
                    self.fetch_all(limit_per_source=2),
                    timeout=30.0
                )
                # クエリでフィルタリング
                query_lower = query.lower()
                for a in scraped:
                    if query_lower in a.title.lower() or query_lower in a.summary.lower():
                        articles.append(a)
            except asyncio.TimeoutError:
                print(f"⚠️ Scrapling タイムアウト")
            except Exception as e:
                print(f"⚠️ Scrapling取得エラー: {e}")
        
        # 2. Google News RSSで補完
        try:
            rss_url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(rss_url)
                resp.raise_for_status()
                
                import re
                items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
                
                for item in items[:limit]:
                    title_match = re.search(r'<title>(.*?)</title>', item)
                    link_match = re.search(r'<link>(.*?)</link>', item)
                    source_match = re.search(r'<source[^>]*>(.*?)</source>', item)
                    
                    if title_match and link_match:
                        articles.append(NewsArticle(
                            title=title_match.group(1).replace('&amp;', '&'),
                            url=link_match.group(1),
                            source=source_match.group(1) if source_match else "Google News",
                        ))
        except Exception as e:
            print(f"⚠️ Google News RSSエラー: {e}")
        
        # 重複除去
        seen = set()
        unique = []
        for a in articles:
            if a.title not in seen:
                seen.add(a.title)
                unique.append(a)
        
        return unique[:limit]
    
    def save_context(self, context: NewsContext, filename: str = None):
        """コンテキストを保存"""
        if not filename:
            filename = f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = self.save_dir / filename
        
        data = {
            "market_question": context.market_question,
            "fetched_at": context.fetched_at.isoformat(),
            "articles": [a.to_dict() for a in context.articles],
        }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 保存: {filepath}")


# Google News RSS (Scrapling不要)
class GoogleNewsFetcher:
    """Google News RSS フェッチャー (軽量版)"""
    
    RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    
    async def search(self, query: str, limit: int = 10) -> List[NewsArticle]:
        """
        Google Newsで検索
        
        Args:
            query: 検索クエリ
            limit: 最大件数
        
        Returns:
            List[NewsArticle]
        """
        import urllib.parse
        url = self.RSS_URL.format(query=urllib.parse.quote(query))
        
        articles = []
        
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                
                # 簡易XMLパース
                import re
                items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
                
                for item in items[:limit]:
                    title_match = re.search(r'<title>(.*?)</title>', item)
                    link_match = re.search(r'<link>(.*?)</link>', item)
                    pub_match = re.search(r'<pubDate>(.*?)</pubDate>', item)
                    source_match = re.search(r'<source[^>]*>(.*?)</source>', item)
                    
                    if title_match and link_match:
                        # 日付パース
                        pub_date = None
                        if pub_match:
                            try:
                                from email.utils import parsedate_to_datetime
                                pub_date = parsedate_to_datetime(pub_match.group(1))
                            except:
                                pass
                        
                        articles.append(NewsArticle(
                            title=title_match.group(1).replace('&amp;', '&'),
                            url=link_match.group(1),
                            source=source_match.group(1) if source_match else "Google News",
                            published=pub_date,
                        ))
                
            except Exception as e:
                print(f"❌ Google News エラー: {e}")
        
        return articles


# CLI
async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="ニュース取得")
    parser.add_argument("--source", help="ソース (decrypt, coindesk, etc.)")
    parser.add_argument("--query", help="Google News検索クエリ")
    parser.add_argument("--market", help="マーケット質問")
    parser.add_argument("--limit", type=int, default=10, help="最大件数")
    
    args = parser.parse_args()
    
    if args.query:
        # Google News検索
        fetcher = GoogleNewsFetcher()
        print(f"🔍 Google News: {args.query}")
        articles = await fetcher.search(args.query, args.limit)
        
        for i, a in enumerate(articles, 1):
            print(f"{i}. {a.title}")
            print(f"   {a.source} | {a.published}")
            print()
    
    elif args.market:
        # マーケット用ニュース
        fetcher = NewsFetcher()
        context = await fetcher.fetch_for_market(args.market, limit=args.limit)
        print("\n" + context.to_prompt())
    
    elif args.source:
        # 特定ソース
        fetcher = NewsFetcher()
        articles = await fetcher.fetch_from_source(args.source, args.limit)
        
        for i, a in enumerate(articles, 1):
            print(f"{i}. {a.title}")
            print(f"   {a.url}")
            print()
    
    else:
        # 全ソース
        fetcher = NewsFetcher()
        articles = await fetcher.fetch_all(limit_per_source=3)
        
        print(f"\n📰 {len(articles)} 記事取得")
        for a in articles[:10]:
            print(f"  - [{a.source}] {a.title[:50]}...")


if __name__ == "__main__":
    asyncio.run(main())
