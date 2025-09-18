import json
import os
import random
from datetime import datetime, timedelta
import asyncio
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.api import logger
from astrbot.core.star.star_tools import StarTools

# 导入提取器
from .src.aiera import extract as aiera_extract
from .src.jiqizhixin import extract as jiqizhixin_extract
from .src.qbitai import extract as qbitai_extract


@register("astrbot_plugin_the_Big-3_Chinese_AI_conferences", "RC-CHN", "亿万人将要精读中文AI顶会", "v1.0")
class DailyReportPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        
        # 使用 StarTools 管理插件数据路径
        self.plugin_data_dir: Path = StarTools.get_data_dir()
        self.report_meta_path = self.plugin_data_dir / "report_meta.json"
        self.output_html_path = self.plugin_data_dir / "daily_report.html"
        self.output_image_path = self.plugin_data_dir / "daily_report.jpeg"
        
        # 将提取器缓存也移到插件数据目录
        aiera_extract.CACHE_DIR = str(self.plugin_data_dir / "aiera_cache")
        aiera_extract.CACHE_FILE = str(self.plugin_data_dir / "aiera_cache" / "articles.json")
        jiqizhixin_extract.CACHE_DIR = str(self.plugin_data_dir / "jiqizhixin_cache")
        jiqizhixin_extract.CACHE_FILE = str(self.plugin_data_dir / "jiqizhixin_cache" / "articles.json")
        qbitai_extract.CACHE_DIR = str(self.plugin_data_dir / "qbitai_cache")
        qbitai_extract.CACHE_FILE = str(self.plugin_data_dir / "qbitai_cache" / "articles.json")

        self.extractors = {"AIERA": aiera_extract, "Jiqizhixin": jiqizhixin_extract, "QbitAI": qbitai_extract}
        
        # To-Do: These can be moved to config later
        self.max_fetch_concurrency = 3
        self.max_llm_concurrency = 5
        self.report_cache_duration = timedelta(hours=3)
        self.WEATHERS = [
            ("Network Congestion", "⦙"),
            ("Cosmic Ray Interference", "☄"),
            ("Data Stream Fluctuation", "〰"),
            ("Server Maintenance", "⚙"),
            ("AI in Deep Thought", "⌬"),
            ("Quantum Entanglement", "⌬")
        ]

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        pass

    def _get_and_update_issue_number(self) -> int:
        """获取并更新报告刊号。"""
        issue_number = 1
        if self.report_meta_path.exists():
            try:
                with open(self.report_meta_path, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                    issue_number = meta_data.get("issue_number", 0) + 1
            except (json.JSONDecodeError, FileNotFoundError):
                issue_number = 1
        
        with open(self.report_meta_path, "w", encoding="utf-8") as f:
            json.dump({"issue_number": issue_number}, f, ensure_ascii=False, indent=4)
            
        return issue_number

    async def _run_extraction(self):
        """运行所有数据提取过程。"""
        logger.info("--- 启动数据提取 ---")
        semaphore = asyncio.Semaphore(self.max_fetch_concurrency)
        tasks = []
        for name, module in self.extractors.items():
            logger.info(f"正在准备从 {name} 获取...")
            tasks.append(asyncio.create_task(module.fetch_latest_articles(semaphore=semaphore)))
        
        await asyncio.gather(*tasks)
        logger.info("--- 数据提取完成 ---")

    async def _get_summary(self, content: str) -> str:
        """根据提供的全文内容，使用框架配置的 Provider 生成摘要。"""
        if not content:
            return "内容为空，无法生成摘要。"

        provider_id = self.config.get("summary_provider")
        if not provider_id:
            logger.warning("摘要功能未配置，请在插件设置中指定 Provider ID。")
            return "摘要功能未配置，请在插件设置中指定 Provider ID。"

        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            logger.error(f"无法找到 ID 为 '{provider_id}' 的 Provider 实例，请检查主配置。")
            return f"无法找到 ID 为 '{provider_id}' 的 Provider 实例。"

        try:
            prompt = f"""
            请将以下文章内容总结为一段精炼的中文摘要，直接给出摘要，不要包含任何引言或结束语,大约三十字左右。
            文章内容：
            ---
            {content}
            ---
            摘要：
            """
            llm_resp = await provider.text_chat(prompt=prompt)
            
            if llm_resp and llm_resp.completion_text:
                return llm_resp.completion_text.strip()
            else:
                logger.warning("生成摘要时出错：模型未返回有效内容。")
                return "生成摘要时出错：模型未返回有效内容。"
        except Exception as e:
            logger.error(f"调用 Provider '{provider_id}' 时出错: {e}", exc_info=True)
            return "生成摘要时出错。"

    def _load_articles(self):
        all_articles = []
        for module in self.extractors.values():
            article_path = module.CACHE_FILE
            try:
                with open(article_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for article in data.get("articles", []):
                        # 确保来源信息存在
                        if 'source' not in article:
                             # 从模块名推断来源
                            source_name = [k for k, v in self.extractors.items() if v == module][0]
                            article['source'] = source_name
                        all_articles.append(article)
            except FileNotFoundError:
                logger.warning(f"未找到文章缓存文件: {article_path}")
            except json.JSONDecodeError:
                logger.error(f"解析 {article_path} 出错")
        return all_articles

    @filter.command("generate_report")
    async def generate_report_command(self, event: AstrMessageEvent):
        """生成AI日报"""
        # 检查报告缓存
        if self.output_image_path.exists():
            last_modified_time = datetime.fromtimestamp(self.output_image_path.stat().st_mtime)
            if datetime.now() - last_modified_time < self.report_cache_duration:
                logger.info("报告在缓存有效期内，直接返回现有报告图片。")
                yield event.image_result(str(self.output_image_path))
                return

        yield event.plain_result("严肃学习中，少话...")

        # 1. 获取新刊号
        issue_number = self._get_and_update_issue_number()

        # 2. 运行数据提取
        await self._run_extraction()

        # 3. 从缓存加载文章
        articles = self._load_articles()
        if not articles:
            yield event.plain_result("学习失败，已严肃反思")
            return

        # 4. 随机选择10篇文章
        random.shuffle(articles)
        selected_articles = articles[:10]

        # 5. 并发生成摘要
        logger.info("--- 开始生成摘要 ---")
        summary_tasks = []
        for article in selected_articles:
            summary_tasks.append(self._get_summary(article.get('content', '')))
        
        summaries = await asyncio.gather(*summary_tasks)

        for article, summary in zip(selected_articles, summaries):
            article['summary'] = summary
            if "出错" in summary or "无法" in summary:
                 logger.warning(f"总结失败: {article['title']} - {summary}")
            else:
                 logger.info(f"已总结: {article['title']}")
        logger.info("--- 摘要生成完毕 ---")

        # 6. 准备渲染数据
        weather_text, weather_icon = random.choice(self.WEATHERS)
        render_data = {
            "featured_articles": selected_articles[:2],
            "regular_articles": selected_articles[2:],
            "issue_number": issue_number,
            "date": datetime.now().strftime("%A, %B %d, %Y"),
            "weather_text": weather_text,
            "weather_icon": weather_icon
        }
        
        # 7. 渲染HTML为图片
        template_path = os.path.join(os.path.dirname(__file__), "templates", "report_template.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            image_path = await self.html_render(
                tmpl=template_content,
                data=render_data,
                return_url=False,
                options={"type": "jpeg", "full_page": True, "quality": 90}
            )
            # 将渲染好的图片移动到我们的数据目录以作为缓存
            if os.path.exists(self.output_image_path):
                os.remove(self.output_image_path)
            os.rename(image_path, self.output_image_path)

            yield event.image_result(str(self.output_image_path))
            yield event.plain_result("已严肃学习")
            logger.info(f"新的日报已生成 (第 {issue_number} 期)：{self.output_image_path}")

        except Exception as e:
            logger.error(f"渲染日报图片时出错: {e}", exc_info=True)
            yield event.plain_result("渲染失败，已严肃反思")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        pass
