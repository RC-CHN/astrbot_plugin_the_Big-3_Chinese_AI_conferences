import requests
import json
import os
from datetime import datetime, timedelta
import feedparser
from playwright.async_api import async_playwright
import trafilatura
import asyncio

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'articles.json')
CACHE_DURATION = timedelta(hours=3)

async def get_full_content(url, semaphore):
    """使用Playwright和Trafilatura获取文章全文，并使用信号量控制并发。"""
    async with semaphore:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
                )
                page = await context.new_page()
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                # 等待2秒让动态内容加载
                await page.wait_for_timeout(2000)
                html = await page.content()
                await browser.close()
            
            content = trafilatura.extract(html)
            return content if content else ""
        except Exception as e:
            print(f"  - 抓取内容失败: {url}, 错误: {e}")
            return ""

async def fetch_latest_articles(limit=10, semaphore=None):
    """
    Fetches the latest articles from QbitAI using RSS feed.
    
    Args:
        limit (int): The number of articles to fetch.
        
    Returns:
        list: A list of articles with title and URL.
    """
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            last_fetched_time = datetime.fromisoformat(cached_data.get('timestamp'))
            if datetime.now() - last_fetched_time < CACHE_DURATION:
                print("Fetching articles from cache.")
                return cached_data.get('articles', [])[:limit]
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            pass

    print("Fetching articles from network.")
    
    articles = []
    
    # Use RSS feed
    rss_url = "https://www.qbitai.com/feed/"
    feed = feedparser.parse(rss_url)
    
    tasks = []
    for entry in feed.entries[:limit]:
        url = entry.link
        title = entry.title
        print(f"  - 正在准备抓取: {title}")
        task = asyncio.create_task(get_full_content(url, semaphore))
        articles.append({
            "title": title,
            "url": url,
            "task": task
        })

    # 并发执行所有抓取任务
    contents = await asyncio.gather(*(article.pop("task") for article in articles))

    # 将结果填充回文章列表
    for i, article in enumerate(articles):
        article["content"] = contents[i]
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        cache_content = {
            'timestamp': datetime.now().isoformat(),
            'articles': articles
        }
        json.dump(cache_content, f, ensure_ascii=False, indent=4)

    return articles[:limit]

if __name__ == '__main__':
    async def main_async():
        latest_articles = await fetch_latest_articles()
        if latest_articles:
            print(f"Successfully fetched {len(latest_articles)} articles.")
            print(f"First article: {latest_articles[0]['title']}")
            print(f"URL: {latest_articles[0]['url']}")
        else:
            print("No articles found.")
    asyncio.run(main_async())