import requests
import json
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import trafilatura
import asyncio
import requests

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
    Fetches the latest articles from Jiqizhixin, using a cache to avoid redundant requests.

    Args:
        limit (int): The number of articles to fetch.

    Returns:
        list: A list of the latest articles.
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
            # Invalid cache, proceed to fetch from network
            pass

    print("Fetching articles from network.")
    url = "https://www.jiqizhixin.com/api/v4/articles.json?sort=time"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        data = response.json()
        articles = data.get("articles", [])
        
        # 统一数据格式为标题和URL
        formatted_articles = []
        tasks = []
        for article in articles:
            title = article.get("title", "")
            slug = article.get("slug", "")
            url = f"https://www.jiqizhixin.com/articles/{slug}"
            print(f"  - 正在准备抓取: {title}")
            task = asyncio.create_task(get_full_content(url, semaphore))
            formatted_articles.append({
                "title": title,
                "url": url,
                "task": task
            })

        # 并发执行所有抓取任务
        contents = await asyncio.gather(*(article.pop("task") for article in formatted_articles))

        # 将结果填充回文章列表
        for i, article in enumerate(formatted_articles):
            article["content"] = contents[i]
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            cache_content = {
                'timestamp': datetime.now().isoformat(),
                'articles': formatted_articles
            }
            json.dump(cache_content, f, ensure_ascii=False, indent=4)

        return formatted_articles[:limit]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching articles: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return []

if __name__ == '__main__':
    async def main_async():
        latest_articles = await fetch_latest_articles()
        if latest_articles:
            print(f"Successfully fetched {len(latest_articles)} articles.")
            # Print the title of the first article for a quick check
            if latest_articles:
                print(f"First article title: {latest_articles[0].get('title')}")
    asyncio.run(main_async())