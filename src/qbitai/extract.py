import json
import hashlib
from datetime import datetime, timedelta
import feedparser
from playwright.async_api import async_playwright
import trafilatura
import asyncio
from astrbot.api import logger
from pathlib import Path
import httpx

CACHE_DURATION = timedelta(hours=3)

async def get_full_content(url: str, browser, semaphore: asyncio.Semaphore, loop: asyncio.AbstractEventLoop) -> str:
    """使用共享的浏览器实例并发获取文章全文。"""
    async with semaphore:
        context = None
        try:
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            )
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            
            content = await loop.run_in_executor(None, trafilatura.extract, html)
            return content if content else ""
        except Exception as e:
            logger.error(f"QbitAI: 抓取内容失败: {url}", exc_info=e)
            return ""
        finally:
            if context:
                await context.close()

async def fetch_latest_articles(limit: int = 10, semaphore: asyncio.Semaphore = None, cache_dir: Path = None) -> list:
    """
    Fetches the latest articles from QbitAI using RSS feed.
    """
    if not cache_dir:
        raise ValueError("cache_dir must be provided.")
        
    cache_file = cache_dir / "articles.json"

    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            last_fetched_time = datetime.fromisoformat(cached_data.get('timestamp'))
            if datetime.now() - last_fetched_time < CACHE_DURATION:
                logger.info("QbitAI: 从缓存加载文章。")
                return cached_data.get('articles', [])[:limit]
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            pass

    logger.info("QbitAI: 从网络抓取文章。")
    
    articles = []
    
    p = None
    browser = None
    try:
        rss_url = "https://www.qbitai.com/feed"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(rss_url, headers=headers)
            response.raise_for_status()
            feed_content = response.text
        
        loop = asyncio.get_running_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, feed_content)
        
        tasks = []
        
        p = await async_playwright().start()
        browser = await p.chromium.launch()

        for entry in feed.entries[:limit]:
            url = entry.link
            title = entry.title
            logger.info(f"QbitAI: 正在准备抓取: {title}")
            task = asyncio.create_task(get_full_content(url, browser, semaphore, loop))
            articles.append({
                "title": title,
                "url": url,
                "task": task
            })

        contents = await asyncio.gather(*(article.pop("task") for article in articles))

        for i, article in enumerate(articles):
            article["content"] = contents[i]
            article["id"] = hashlib.md5(article["url"].encode("utf-8")).hexdigest()[:5]
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            cache_content = {
                'timestamp': datetime.now().isoformat(),
                'articles': articles
            }
            json.dump(cache_content, f, ensure_ascii=False, indent=4)

        return articles[:limit]
    except httpx.RequestError as e:
        logger.error(f"QbitAI: 抓取RSS源失败", exc_info=e)
        return []
    except Exception as e:
        logger.error(f"QbitAI: 处理文章时失败", exc_info=e)
        return []
    finally:
        if browser:
            await browser.close()
        if p:
            await p.stop()