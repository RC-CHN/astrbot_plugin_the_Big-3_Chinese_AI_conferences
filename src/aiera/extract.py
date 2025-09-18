import requests
import json
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'articles.json')
CACHE_DURATION = timedelta(hours=3)

def fetch_latest_articles(limit=10):
    """
    Fetches the latest articles from AIERA using HTML parsing.
    
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
    
    # Try HTML parsing
    try:
        response = requests.get("https://aiera.com.cn/")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for article links
        selectors = [
            'h2 a',
            'h3 a',
            '.post-title a',
            '.entry-title a',
            'article a',
            '.news-item a',
            '.article-title a'
        ]
        
        for selector in selectors:
            links = soup.select(selector)[:limit]
            if links:
                for link in links:
                    title = link.get_text(strip=True)
                    url = link.get('href', '')
                    if url and not url.startswith('http'):
                        url = f"https://aiera.com.cn{url}"
                    if title and url:
                        articles.append({
                            "title": title,
                            "url": url
                        })
                break
                
    except Exception as e:
        print(f"HTML parsing failed: {e}")
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        cache_content = {
            'timestamp': datetime.now().isoformat(),
            'articles': articles
        }
        json.dump(cache_content, f, ensure_ascii=False, indent=4)

    return articles[:limit]

if __name__ == '__main__':
    latest_articles = fetch_latest_articles()
    if latest_articles:
        print(f"Successfully fetched {len(latest_articles)} articles.")
        print(f"First article: {latest_articles[0]['title']}")
        print(f"URL: {latest_articles[0]['url']}")
    else:
        print("No articles found.")