import requests
import json
import os
from datetime import datetime, timedelta

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'articles.json')
CACHE_DURATION = timedelta(hours=3)

def fetch_latest_articles(limit=10):
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
        for article in articles:
            title = article.get("title", "")
            slug = article.get("slug", "")
            url = f"https://www.jiqizhixin.com/articles/{slug}"
            formatted_articles.append({
                "title": title,
                "url": url
            })
        
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
    latest_articles = fetch_latest_articles()
    if latest_articles:
        print(f"Successfully fetched {len(latest_articles)} articles.")
        # Print the title of the first article for a quick check
        if latest_articles:
            print(f"First article title: {latest_articles[0].get('title')}")