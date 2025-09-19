import json
import random
from datetime import datetime, timedelta
import asyncio
from pathlib import Path
from filelock import FileLock, Timeout

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.api import logger
from astrbot.core.star.star_tools import StarTools

# 导入提取器
from .src.aiera import extract as aiera_extract
from .src.jiqizhixin import extract as jiqizhixin_extract
from .src.qbitai import extract as qbitai_extract


@register("astrbot_plugin_the_Big-3_Chinese_AI_conferences", "RC-CHN", "亿万人将要精读中文AI顶会", "v1.1")
class DailyReportPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        
        self.plugin_data_dir: Path = StarTools.get_data_dir() 
        self.report_meta_path = self.plugin_data_dir / "report_meta.json"
        self.report_meta_lock_path = self.plugin_data_dir / "report_meta.json.lock"
        self.output_image_path = self.plugin_data_dir / "daily_report.jpeg"
        
        self.extractors = {
            "AIERA": aiera_extract, 
            "Jiqizhixin": jiqizhixin_extract, 
            "QbitAI": qbitai_extract
        }
        
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
        pass

    def _get_and_update_issue_number(self) -> int:
        """获取并更新报告刊号，使用文件锁防止竞态条件。"""
        lock = FileLock(self.report_meta_lock_path, timeout=10)
        try:
            with lock:
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
        except Timeout:
            logger.error("获取报告刊号锁超时，可能存在并发问题。")
            # 在超时的情况下返回一个临时的或默认的值
            return -1


    async def _run_extraction(self):
        """运行所有数据提取过程，并传递缓存路径。"""
        logger.info("--- 启动数据提取 ---")
        semaphore = asyncio.Semaphore(self.max_fetch_concurrency)
        tasks = []
        for name, module in self.extractors.items():
            logger.info(f"正在准备从 {name} 获取...")
            cache_dir = self.plugin_data_dir / f"{name.lower()}_cache"
            tasks.append(asyncio.create_task(module.fetch_latest_articles(
                semaphore=semaphore, 
                cache_dir=cache_dir
            )))
        
        await asyncio.gather(*tasks)
        logger.info("--- 数据提取完成 ---")

    async def _get_summary(self, content: str) -> str:
        """根据提供的全文内容，使用框架配置的 Provider 生成摘要。"""
        if not content:
            return "内容为空，无法生成摘要。"

        provider_id = self.config.get("summary_provider")
        if not provider_id:
            logger.warning("摘要功能未配置，请在插件设置中指定 Provider ID。")
            return "摘要功能未配置。"

        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            logger.error(f"无法找到 ID 为 '{provider_id}' 的 Provider 实例。")
            return f"无法找到 Provider '{provider_id}'。"

        try:
            prompt = f"请将以下文章内容总结为一段精炼的中文摘要，直接给出摘要，不要包含任何引言或结束语,大约三十字左右。\n文章内容：\n---\n{content}\n---\n摘要："
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
        """从各个提取器的缓存中加载文章。"""
        all_articles = []
        for name, module in self.extractors.items():
            cache_dir = self.plugin_data_dir / f"{name.lower()}_cache"
            article_path = cache_dir / "articles.json"
            try:
                with open(article_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for article in data.get("articles", []):
                        article['source'] = name  # 直接使用字典的键作为来源
                        all_articles.append(article)
            except FileNotFoundError:
                logger.warning(f"未找到文章缓存文件: {article_path}")
            except json.JSONDecodeError:
                logger.error(f"解析 {article_path} 出错")
        return all_articles

    @filter.command("今日顶会")
    async def generate_report_command(self, event: AstrMessageEvent):
        """生成AI日报"""
        if self.output_image_path.exists():
            last_modified_time = datetime.fromtimestamp(self.output_image_path.stat().st_mtime)
            if datetime.now() - last_modified_time < self.report_cache_duration:
                logger.info("报告在缓存有效期内，直接返回现有报告图片。")
                yield event.image_result(str(self.output_image_path))
                return

        yield event.plain_result("严肃学习中，少话...")

        issue_number = self._get_and_update_issue_number()
        if issue_number == -1:
            yield event.plain_result("无法获取报告刊号，请稍后再试。")
            return

        await self._run_extraction()

        articles = self._load_articles()
        if not articles:
            yield event.plain_result("学习失败，已严肃反思")
            return

        random.shuffle(articles)
        selected_articles = articles[:10]

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

        weather_text, weather_icon = random.choice(self.WEATHERS)
        render_data = {
            "featured_articles": selected_articles[:2],
            "regular_articles": selected_articles[2:],
            "issue_number": issue_number,
            "date": datetime.now().strftime("%A, %B %d, %Y"),
            "weather_text": weather_text,
            "weather_icon": weather_icon
        }
        
        template_path = Path(__file__).parent / "templates" / "report_template.html"
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            image_path_str = await self.html_render(
                tmpl=template_content,
                data=render_data,
                return_url=False,
                options={"type": "jpeg", "full_page": True, "quality": 90}
            )
            
            # 使用pathlib进行路径操作
            image_path = Path(image_path_str)
            if self.output_image_path.exists():
                self.output_image_path.unlink()
            image_path.rename(self.output_image_path)

            yield event.image_result(str(self.output_image_path))
            yield event.plain_result("已严肃学习")
            logger.info(f"新的日报已生成 (第 {issue_number} 期)：{self.output_image_path}")

        except Exception as e:
            logger.error(f"渲染日报图片时出错: {e}", exc_info=True)
            yield event.plain_result("渲染失败，已严肃反思")

    async def terminate(self):
        pass
