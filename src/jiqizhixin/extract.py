import requests
import json
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import trafilatura
import asyncio
from astrbot.api import logger

CACHE_DIR = None
CACHE_FILE = None
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
            logger.error(f"Jiqizhixin: 抓取内容失败: {url}", exc_info=e)
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
                logger.info("Jiqizhixin: 从缓存加载文章。")
                return cached_data.get('articles', [])[:limit]
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            # Invalid cache, proceed to fetch from network
            pass

    logger.info("Jiqizhixin: 从网络抓取文章。")
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
            logger.info(f"Jiqizhixin: 正在准备抓取: {title}")
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
        logger.error(f"Jiqizhixin: 抓取文章列表失败", exc_info=e)
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Jiqizhixin: 解析JSON失败", exc_info=e)
        return []