# AI 日报生成器 (AI Daily Report Generator)

这是一个为 AstrBot 设计的插件，用于自动抓取中国三大 AI 媒体（AI ERA, 机器之心, QbitAI）的最新文章，使用大语言模型生成摘要，并最终渲染成一份排版精美的日报图片。

## ✨ 功能特性

- **自动化内容聚合**: 定时从多个来源抓取最新 AI 资讯。
- **智能摘要生成**: 利用可配置的 LLM Provider (如 OpenAI, ZhipuAI 等) 为每篇文章生成精炼摘要。
- **智能缓存**: 报告生成后会缓存3小时，避免在短时间内重复生成，节约资源。


## 🚀 如何使用

要生成一份新的 AI 日报，请在聊天中发送以下指令：

```
/今日顶会
```

机器人将回复一条提示消息，并在后台开始生成过程。完成后，机器人会自动将渲染好的日报图片发送到当前聊天。

## ⚙️ 配置说明

为了使摘要功能正常工作，您必须在 AstrBot 的插件管理界面中为此插件进行配置。

- **`summary_provider`**:
  - **描述**: 用于生成文章摘要的 LLM Provider 的 ID。
  - **类型**: `string`
  - **默认值**: `"openai"`
  - **说明**: 请确保此处填写的 Provider ID 已经在您的 AstrBot 主配置中正确设置并可用。您可以根据需要将其更改为您偏好的任何已配置的 Provider ID。

## 📦 依赖项

在启用此插件之前，请确保您的 Python 环境中已安装以下依赖项：

```
playwright
trafilatura
requests
feedparser
```

您可以通过运行以下命令来安装它们，框架在载入时也会尝试自动安装：

```bash
pip install playwright trafilatura requests feedparser
playwright install
```
**注意**: `playwright` 需要一个额外的步骤来安装浏览器核心，请务必运行 `playwright install`，该步不会由框架自动执行。
