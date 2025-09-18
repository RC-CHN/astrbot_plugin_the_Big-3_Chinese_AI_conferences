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
            logger.error(f"AIERA: 抓取内容失败: {url}", exc_info=e)
            return ""

async def fetch_latest_articles(limit=10, semaphore=None):
    """
    Fetches the latest articles from AIERA using Playwright.
    
    Args:
        limit (int): The number of articles to fetch.
        
    Returns:
        list: A list of articles with title, URL, and content.
    """
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            last_fetched_time = datetime.fromisoformat(cached_data.get('timestamp'))
            if datetime.now() - last_fetched_time < CACHE_DURATION:
                logger.info("AIERA: 从缓存加载文章。")
                return cached_data.get('articles', [])[:limit]
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            pass

    logger.info("AIERA: 从网络抓取文章。")
    
    articles = []
    
    # Try HTML parsing
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto("https://aiera.com.cn/", wait_until='domcontentloaded')
            
            # 使用更通用的定位器来查找文章链接
            locators = await page.locator('article a, .post-title a, .entry-title a, h2 a, h3 a').all()
            
            fetched_urls = set()
            tasks = []

            for loc in locators:
                if len(fetched_urls) >= limit:
                    break
                
                title = (await loc.inner_text()).strip()
                url = await loc.get_attribute('href')
                
                if not url or not title:
                    continue

                if not url.startswith('http'):
                    url = f"https://aiera.com.cn{url}"
                
                if url in fetched_urls:
                    continue
                
                fetched_urls.add(url)
                logger.info(f"AIERA: 正在准备抓取: {title}")
                # 创建异步任务
                task = asyncio.create_task(get_full_content(url, semaphore))
                articles.append({
                    "title": title,
                    "url": url,
                    "task": task  # 暂存任务
                })

            # 并发执行所有抓取任务
            contents = await asyncio.gather(*(article.pop("task") for article in articles))
            
            # 将结果填充回文章列表
            for i, article in enumerate(articles):
                article["content"] = contents[i]

            await browser.close()
                
    except Exception as e:
        logger.error(f"AIERA: Playwright抓取失败", exc_info=e)
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        cache_content = {
            'timestamp': datetime.now().isoformat(),
            'articles': articles
        }
        json.dump(cache_content, f, ensure_ascii=False, indent=4)

    return articles[:limit]