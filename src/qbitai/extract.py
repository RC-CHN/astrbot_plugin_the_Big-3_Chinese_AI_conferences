import requests
import json
import os
from datetime import datetime, timedelta
import feedparser

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'articles.json')
CACHE_DURATION = timedelta(hours=3)

def fetch_latest_articles(limit=10):
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
    
    for entry in feed.entries[:limit]:
        articles.append({
            "title": entry.title,
            "url": entry.link
        })
    
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