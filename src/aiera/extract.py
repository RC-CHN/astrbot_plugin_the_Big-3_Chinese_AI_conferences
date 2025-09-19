import json
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
import trafilatura
import asyncio
from astrbot.api import logger
from pathlib import Path

CACHE_DURATION = timedelta(hours=3)

async def get_full_content(url: str, semaphore: asyncio.Semaphore, loop: asyncio.AbstractEventLoop) -> str:
    """使用Playwright和Trafilatura获取文章全文，并使用信号量控制并发。"""
    async with semaphore:
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
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
            logger.error(f"AIERA: 抓取内容失败: {url}", exc_info=e)
            return ""
        finally:
            if browser:
                await browser.close()

async def fetch_latest_articles(limit: int = 10, semaphore: asyncio.Semaphore = None, cache_dir: Path = None) -> list:
    """
    Fetches the latest articles from AIERA using Playwright.
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
                logger.info("AIERA: 从缓存加载文章。")
                return cached_data.get('articles', [])[:limit]
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            pass

    logger.info("AIERA: 从网络抓取文章。")
    
    articles = []
    
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto("https://aiera.com.cn/", wait_until='domcontentloaded')
            
            locators = await page.locator('article a, .post-title a, .entry-title a, h2 a, h3 a').all()
            
            fetched_urls = set()
            tasks = []
            loop = asyncio.get_running_loop()

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
                task = asyncio.create_task(get_full_content(url, semaphore, loop))
                articles.append({
                    "title": title,
                    "url": url,
                    "task": task
                })

            contents = await asyncio.gather(*(article.pop("task") for article in articles))
            
            for i, article in enumerate(articles):
                article["content"] = contents[i]
                
    except Exception as e:
        logger.error(f"AIERA: Playwright抓取失败", exc_info=e)
    finally:
        if browser:
            await browser.close()
    
    with open(cache_file, 'w', encoding='utf-8') as f:
        cache_content = {
            'timestamp': datetime.now().isoformat(),
            'articles': articles
        }
        json.dump(cache_content, f, ensure_ascii=False, indent=4)

    return articles[:limit]