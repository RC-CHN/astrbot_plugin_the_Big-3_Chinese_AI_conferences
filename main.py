import json
import os
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("daily_report", "Roo", "生成AI日报", "1.0.0")
class DailyReportPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_path = os.path.join(os.path.dirname(__file__), "src")
        self.sites = ["aiera", "jiqizhixin", "qbitai"]

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        pass
    
    def _load_articles(self):
        all_articles = []
        for site in self.sites:
            article_path = os.path.join(self.data_path, site, "cache", "articles.json")
            try:
                with open(article_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 添加来源信息
                    for article in data.get("articles", []):
                        article['source'] = site
                        all_articles.append(article)
            except FileNotFoundError:
                logger.warning(f"未找到 {article_path}")
            except json.JSONDecodeError:
                logger.error(f"解析 {article_path} 出错")
        return all_articles

    def _generate_html(self, articles):
        template_path = os.path.join(os.path.dirname(__file__), "templates", "report_template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:
            logger.error(f"未找到HTML模板: {template_path}")
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
        # 天气信息可以后续通过API获取
        weather = "Scattered Clouds"

        html_content = template.replace("{articles}", article_html)
        html_content = html_content.replace("{date}", today)
        html_content = html_content.replace("{weather}", weather)

        return html_content

    @filter.command("generate_report")
    async def generate_report_command(self, event: AstrMessageEvent):
        """生成AI日报"""
        articles = self._load_articles()
        if not articles:
            yield event.plain_result("没有找到任何文章来生成日报。")
            return

        html_content = self._generate_html(articles)
        report_path = os.path.join(os.path.dirname(__file__), "daily_report.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        yield event.plain_result(f"日报已生成：{report_path}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        pass
