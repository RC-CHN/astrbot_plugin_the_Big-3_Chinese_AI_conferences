import json
import random
import shutil
from datetime import datetime, timedelta
import asyncio
from pathlib import Path
from filelock import FileLock, Timeout

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.core.message.message_event_result import MessageChain
import astrbot.core.message.components as Comp
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
        self.generation_lock_path = self.plugin_data_dir / "generation.lock"
        self.output_image_path = self.plugin_data_dir / "daily_report.jpeg"
        self.deep_read_cache_dir = self.plugin_data_dir / "deep_read_cache"
        
        self.extractors = {
            "AIERA": aiera_extract,
            "Jiqizhixin": jiqizhixin_extract,
            "QbitAI": qbitai_extract
        }
        
        self.max_fetch_concurrency = self.config.get("max_fetch_concurrency", 3)
        self.max_llm_concurrency = self.config.get("max_llm_concurrency", 5)
        self.llm_rpm_limit = self.config.get("llm_rpm_limit", 60)
        self.report_cache_duration = timedelta(hours=3)
        self.scheduler = AsyncIOScheduler(timezone=self.context.get_config().get("timezone", "Asia/Shanghai"))
        self.WEATHERS = [
            ("Network Congestion", "⦙"),
            ("Cosmic Ray Interference", "☄"),
            ("Data Stream Fluctuation", "〰"),
            ("Server Maintenance", "⚙"),
            ("AI in Deep Thought", "⌬"),
            ("Quantum Entanglement", "⌬")
        ]

    async def initialize(self):
        """初始化插件，设置并启动定时任务。"""
        self.deep_read_cache_dir.mkdir(parents=True, exist_ok=True)
        
        if self.config.get("schedule_enabled"):
            cron_expr = self.config.get("schedule_cron", "0 9 * * *")
            targets = self.config.get("schedule_targets", [])
            if not targets:
                logger.warning("定时报告已启用，但未配置任何接收者 (schedule_targets)，任务不会运行。")
                return

            logger.info(f"定时报告任务已启用，Cron: '{cron_expr}'，将发送至 {len(targets)} 个目标。")
            self.scheduler.add_job(
                self._scheduled_report_job,
                "cron",
                **self._parse_cron_expr(cron_expr),
                id="daily_report_job",
                misfire_grace_time=300 # 5分钟宽限期
            )
            self.scheduler.start()

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
        """运行所有数据提取过程，并清空旧的精读缓存。"""
        logger.info("--- 启动数据提取，并清空精读缓存 ---")
        if self.deep_read_cache_dir.exists():
            shutil.rmtree(self.deep_read_cache_dir)
        self.deep_read_cache_dir.mkdir(parents=True, exist_ok=True)

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

    async def _get_summary(self, content: str, semaphore: asyncio.Semaphore) -> str:
        """根据提供的全文内容，使用框架配置的 Provider 生成摘要，并使用信号量控制并发。"""
        async with semaphore:
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

    async def _summary_wrapper(self, article: dict, semaphore: asyncio.Semaphore):
        """为单个文章生成摘要、附加结果并实时记录日志的包装器。"""
        summary = await self._get_summary(article.get('content', ''), semaphore)
        article['summary'] = summary
        if "出错" in summary or "无法" in summary:
            logger.warning(f"总结失败: {article['title']} - {summary}")
        else:
            logger.info(f"已总结: {article['title']}")

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

    def _parse_cron_expr(self, cron_expr: str):
        """将标准 Cron 表达式解析为 apscheduler 需要的字典。"""
        fields = cron_expr.split()
        if len(fields) != 5:
            raise ValueError("无效的 Cron 表达式，需要5个字段。")
        return {
            "minute": fields[0],
            "hour": fields[1],
            "day": fields[2],
            "month": fields[3],
            "day_of_week": fields[4],
        }

    async def _generate_and_render_report(self) -> str | None:
        """核心业务逻辑：生成并渲染报告，返回图片路径。如果失败则返回 None。"""
        generation_lock = FileLock(self.generation_lock_path, timeout=60)
        try:
            with generation_lock:
                if self.output_image_path.exists():
                    last_modified_time = datetime.fromtimestamp(self.output_image_path.stat().st_mtime)
                    if datetime.now() - last_modified_time < self.report_cache_duration:
                        logger.info("报告在缓存有效期内，直接返回现有报告。")
                        return str(self.output_image_path)

                issue_number = self._get_and_update_issue_number()
                if issue_number == -1:
                    logger.error("无法获取报告刊号，生成中止。")
                    return None

                await self._run_extraction()
                articles = self._load_articles()
                if not articles:
                    logger.error("未能加载任何文章，生成中止。")
                    return None

                random.shuffle(articles)
                selected_articles = articles[:10]

                logger.info("--- 开始生成摘要 ---")
                llm_semaphore = asyncio.Semaphore(self.max_llm_concurrency)
                rpm_limit = self.llm_rpm_limit
                delay_between_requests = 60.0 / rpm_limit if rpm_limit > 0 else 0
                summary_tasks = []
                for article in selected_articles:
                    summary_tasks.append(asyncio.create_task(self._summary_wrapper(article, llm_semaphore)))
                    if delay_between_requests > 0:
                        await asyncio.sleep(delay_between_requests)
                await asyncio.gather(*summary_tasks)
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
                with open(template_path, "r", encoding="utf-8") as f:
                    template_content = f.read()

                image_path_str = await self.html_render(
                    tmpl=template_content, data=render_data, return_url=False,
                    options={"type": "jpeg", "full_page": True, "quality": 90}
                )
                
                image_path = Path(image_path_str)
                if self.output_image_path.exists():
                    self.output_image_path.unlink()
                image_path.rename(self.output_image_path)
                
                logger.info(f"新的日报已生成 (第 {issue_number} 期)：{self.output_image_path}")
                return str(self.output_image_path)

        except Timeout:
            logger.warning("已有另一个报告生成任务正在进行中，本次请求已跳过。")
            return None
        except Exception as e:
            logger.error(f"生成或渲染报告时发生未知错误: {e}", exc_info=True)
            return None

    async def _send_report(self, target_umo: str, report_path: str):
        """向指定目标发送报告图片。"""
        try:
            chain = MessageChain(chain=[Comp.Image(file=report_path)])
            await self.context.send_message(target_umo, chain)
            logger.info(f"报告已发送至 {target_umo}")
        except Exception as e:
            logger.error(f"向 {target_umo} 发送报告失败: {e}", exc_info=True)

    async def _scheduled_report_job(self):
        """由调度器调用的定时任务。"""
        logger.info("--- 定时报告任务启动 ---")
        report_path = await self._generate_and_render_report()
        if report_path:
            targets = self.config.get("schedule_targets", [])
            for target_umo in targets:
                await self._send_report(target_umo, report_path)
        logger.info("--- 定时报告任务结束 ---")

    @filter.command("今日顶会")
    async def generate_report_command(self, event: AstrMessageEvent):
        """手动触发生成AI日报。"""
        yield event.plain_result("严肃学习中文顶会中，少话...")
        report_path = await self._generate_and_render_report()
        if report_path:
            await self._send_report(event.unified_msg_origin, report_path)
            yield event.plain_result("日报生成完毕，亿万青年必须学习AI")
        else:
            yield event.plain_result("日报生成失败，已严肃反思")

    def _find_article_by_id(self, article_id: str) -> dict | None:
        """根据文章ID在所有缓存中查找文章。"""
        for name in self.extractors:
            cache_dir = self.plugin_data_dir / f"{name.lower()}_cache"
            article_path = cache_dir / "articles.json"
            if not article_path.exists():
                continue
            try:
                with open(article_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for article in data.get("articles", []):
                        if article.get("id") == article_id:
                            article['source'] = name  # 补充来源字段
                            return article
            except (json.JSONDecodeError, FileNotFoundError):
                continue
        return None

    async def _get_deep_interpretation(self, content: str) -> str | None:
        """调用大模型对文章进行详细解读。"""
        if not content:
            return "文章内容为空，无法进行精读。"

        provider_id = self.config.get("summary_provider")
        if not provider_id:
            logger.warning("精读功能未配置 Provider，请在插件设置中指定。")
            return "精读功能未配置 Provider。"

        provider = self.context.get_provider_by_id(provider_id)
        if not provider:
            logger.error(f"无法找到 ID 为 '{provider_id}' 的 Provider 实例。")
            return f"无法找到 Provider '{provider_id}'。"

        try:
            prompt = f"""请作为一名资深的AI领域分析师，对以下文章进行深入、详细的解读。请用清晰的结构、专业的视角，分析其核心观点、技术创新、潜在影响和未来展望。请直接输出解读内容，无需任何引言或客套话。

文章内容：
---
{content}
---
详细解读："""
            llm_resp = await provider.text_chat(prompt=prompt, long_text_mode=True)
            
            if llm_resp and llm_resp.completion_text:
                return llm_resp.completion_text.strip()
            else:
                logger.warning("精读时出错：模型未返回有效内容。")
                return "精读时出错：模型未返回有效内容。"
        except Exception as e:
            logger.error(f"调用 Provider '{provider_id}' 进行精读时出错: {e}", exc_info=True)
            return "调用精读模型时出错。"

    @filter.command("顶会精读")
    async def deep_read_command(self, event: AstrMessageEvent, article_id: str):
        """根据文章ID进行详细解读，并实现持久化缓存。"""
        article = self._find_article_by_id(article_id)
        if not article:
            yield event.plain_result(f"找不到ID为 '{article_id}' 的文章，请检查ID是否正确，或等待缓存刷新。")
            return

        cached_image_path = self.deep_read_cache_dir / f"{article_id}.jpeg"

        if cached_image_path.exists():
            logger.info(f"精读报告 (ID: {article_id}) 命中缓存，直接发送。")
            yield event.image_result(str(cached_image_path))
            yield event.plain_result(f"原文链接：{article['url']}")
            return

        yield event.plain_result(f"深入精读{article_id}中，隐忍...")
        
        interpretation = await self._get_deep_interpretation(article.get("content", ""))
        if not interpretation or "出错" in interpretation or "无法" in interpretation:
            yield event.plain_result(f"对文章 '{article['title']}' 的精读失败：{interpretation}")
            return

        render_data = {
            "article": article,
            "interpretation": interpretation
        }

        template_path = Path(__file__).parent / "templates" / "deep_read_template.html"
        try:
            # html_render 返回的是一个临时路径
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()

            temp_image_path_str = await self.html_render(
                tmpl=template_content,
                data=render_data,
                return_url=False,
                options={"type": "jpeg", "full_page": True, "quality": 90}
            )
            
            # 将临时文件移动到我们的持久化缓存目录
            temp_image_path = Path(temp_image_path_str)
            temp_image_path.rename(cached_image_path)
            logger.info(f"新的精读报告已生成并缓存至：{cached_image_path}")

            # 确保文件已成功移动到缓存位置后再发送
            if cached_image_path.exists():
                yield event.image_result(str(cached_image_path))
                yield event.plain_result(f"原文链接：{article['url']}")
            else:
                logger.error(f"文件移动失败，无法在缓存位置找到文件：{cached_image_path}")
                yield event.plain_result("处理精读报告时发生文件错误，请稍后再试。")

        except Exception as e:
            logger.error(f"渲染或保存精读报告时出错: {e}", exc_info=True)
            yield event.plain_result("渲染精读报告失败，请检查日志。")

    async def terminate(self):
        """插件终止时关闭调度器。"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("日报插件调度器已关闭。")
