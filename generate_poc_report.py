import json
import os
import random
from datetime import datetime
from openai import OpenAI
import concurrent.futures
import asyncio
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 导入提取器
from src.aiera import extract as aiera_extract
from src.jiqizhixin import extract as jiqizhixin_extract
from src.qbitai import extract as qbitai_extract

# --- 配置 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
MAX_LLM_CONCURRENCY = int(os.getenv("MAX_LLM_CONCURRENCY", 5))
MAX_FETCH_CONCURRENCY = int(os.getenv("MAX_FETCH_CONCURRENCY", 3))

# --- 初始化客户端 ---
llm_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def get_summary_from_content(content):
    """根据提供的全文内容生成摘要。"""
    if not content:
        return "内容为空，无法生成摘要。"
        
    if not all([OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME]):
        return "摘要功能未配置，请检查 .env 文件中的 OPENAI_API_KEY, OPENAI_BASE_URL, 和 MODEL_NAME。"

    try:
        prompt = f"""
        请将以下文章内容总结为一段精炼的中文摘要，直接给出摘要，不要包含任何引言或结束语,大约三十字左右。
        文章内容：
        ---
        {content}
        ---
        摘要：
        """
        
        chat_completion = llm_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.7,
        )
        summary = chat_completion.choices[0].message.content.strip()
        return summary

    except Exception as e:
        print(f"调用LLM时出错: {e}")
        return "生成摘要时出错。"


def load_articles(data_path, sites):
    all_articles = []
    for site in sites:
        article_path = os.path.join(data_path, site, "cache", "articles.json")
        try:
            with open(article_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for article in data.get("articles", []):
                    article['source'] = site
                    all_articles.append(article)
        except FileNotFoundError:
            print(f"警告: 未找到 {article_path}")
        except json.JSONDecodeError:
            print(f"错误: 解析 {article_path} 出错")
    return all_articles

def generate_html(featured_articles, regular_articles, template_path):
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        print(f"错误: 未找到HTML模板: {template_path}")
        return "<html><body><h1>错误：未找到HTML模板</h1></body></html>"

    # 生成头条文章HTML
    featured_html = ""
    for article in featured_articles:
        title = article.get('title', '无标题')
        url = article.get('url', '#')
        source = article.get('source', '未知来源')
        summary = article.get('summary', '暂无摘要')
        featured_html += f"""
        <div class="article featured">
            <h2><a href="{url}" target="_blank">{title}</a></h2>
            <p class="source">来源: {source.capitalize()}</p>
            <p class="summary">{summary}</p>
        </div>
        """

    # 生成常规文章HTML
    regular_html = ""
    for article in regular_articles:
        title = article.get('title', '无标题')
        url = article.get('url', '#')
        source = article.get('source', '未知来源')
        summary = article.get('summary', '暂无摘要')
        regular_html += f"""
        <div class="article">
            <h2><a href="{url}" target="_blank">{title}</a></h2>
            <p class="source">来源: {source.capitalize()}</p>
            <p class="summary">{summary}</p>
        </div>
        """
    
    today = datetime.now().strftime("%A, %B %d, %Y")
    weather = "Scattered Clouds"

    html_content = template.replace("{featured_articles}", featured_html)
    html_content = html_content.replace("{regular_articles}", regular_html)
    html_content = html_content.replace("{date}", today)
    html_content = html_content.replace("{weather}", weather)

    return html_content

async def run_extraction():
    """运行所有数据提取过程。"""
    print("--- 启动数据提取 ---")
    semaphore = asyncio.Semaphore(MAX_FETCH_CONCURRENCY)
    sites = {"AIERA": aiera_extract, "Jiqizhixin": jiqizhixin_extract, "QbitAI": qbitai_extract}
    tasks = []
    for name, module in sites.items():
        print(f"\n正在准备从 {name} 获取...")
        tasks.append(asyncio.create_task(module.fetch_latest_articles(semaphore=semaphore)))
    
    await asyncio.gather(*tasks)
    
    print("\n--- 数据提取完成 ---")


def main():
    # 1. 运行数据提取
    asyncio.run(run_extraction())

    # 2. 从缓存加载文章
    base_dir = os.path.dirname(__file__)
    data_path = os.path.join(base_dir, "src")
    sites = ["aiera", "jiqizhixin", "qbitai"]
    template_path = os.path.join(base_dir, "templates", "report_template.html")
    output_path = os.path.join(base_dir, "daily_report_poc.html")

    articles = load_articles(data_path, sites)
    if not articles:
        print("没有找到任何文章来生成日报。")
        return

    # 3. 随机选择10篇文章
    random.shuffle(articles)
    selected_articles = articles[:10]

    # 4. 并发生成摘要
    print("\n--- 开始生成摘要 ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_LLM_CONCURRENCY) as executor:
        future_to_article = {executor.submit(get_summary_from_content, article.get('content', '')): article for article in selected_articles}
        for future in concurrent.futures.as_completed(future_to_article):
            article = future_to_article[future]
            try:
                summary = future.result()
                article['summary'] = summary
                print(f"  - 已总结: {article['title']}")
            except Exception as exc:
                print(f"  - 总结失败: {article['title']} - {exc}")
                article['summary'] = "生成摘要时出错。"
    print("--- 摘要生成完毕 ---")

    # 5. 生成HTML报告
    featured_articles = selected_articles[:2]
    regular_articles = selected_articles[2:]
    html_content = generate_html(featured_articles, regular_articles, template_path)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nPoC日报已生成：{output_path}")

if __name__ == "__main__":
    main()