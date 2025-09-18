import json
import os
from datetime import datetime

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

def generate_html(articles, template_path):
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        print(f"错误: 未找到HTML模板: {template_path}")
        return "<html><body><h1>错误：未找到HTML模板</h1></body></html>"

    article_html = ""
    for article in articles:
        title = article.get('title', '无标题')
        url = article.get('url', '#')
        source = article.get('source', '未知来源')
        article_html += f"""
        <div class="article">
            <h2><a href="{url}" target="_blank">{title}</a></h2>
            <p class="source">来源: {source.capitalize()}</p>
        </div>
        """
    
    today = datetime.now().strftime("%A, %B %d, %Y")
    weather = "Scattered Clouds"

    html_content = template.replace("{articles}", article_html)
    html_content = html_content.replace("{date}", today)
    html_content = html_content.replace("{weather}", weather)

    return html_content

def main():
    # 脚本文件所在的目录
    base_dir = os.path.dirname(__file__)
    data_path = os.path.join(base_dir, "src")
    sites = ["aiera", "jiqizhixin", "qbitai"]
    template_path = os.path.join(base_dir, "templates", "report_template.html")
    output_path = os.path.join(base_dir, "daily_report_poc.html")

    articles = load_articles(data_path, sites)
    if not articles:
        print("没有找到任何文章来生成日报。")
        return

    html_content = generate_html(articles, template_path)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"PoC日报已生成：{output_path}")

if __name__ == "__main__":
    main()