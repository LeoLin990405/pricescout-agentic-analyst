<div align="center">

[![English](https://img.shields.io/badge/Language-English-555555?style=for-the-badge)](README.md) &nbsp; [![中文](https://img.shields.io/badge/语言-中文-2ea44f?style=for-the-badge)](README.zh-CN.md)

# PriceScout · Agentic 分析师

### 基于 MCP 的研究助手 —— 抓取并对比各家 LLM 推理定价

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/协议-MCP-blueviolet?style=for-the-badge" />
  <img src="https://img.shields.io/badge/存储-SQLite-blue?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-yellowgreen?style=for-the-badge" />
</p>

</div>

> LLM 推理定价散落在十几个 provider 页面、每周还变。PriceScout 让 agent 去抓这些页面、提取数字、落库,并回答「模型 X 谁家更便宜?」。

---

## 概览

PriceScout 是一个**基于 MCP 的研究助手**,用于跨 provider 对比 LLM 推理定价。

| 组件 | 职责 |
|---|---|
| `starter_server.py` | MCP server —— 抓取 provider 定价页 + 取回已存内容的工具 |
| `starter_client.py` | MCP client —— 连接抓取与 SQLite server、路由 Claude 工具调用、存结构化定价数据 |
| `server_config.json` | MCP server 配置(本地项目 server + SQLite MCP server) |
| `evidence.pdf` | 视觉证据:抓取、提取、最终对比 |

---

## 1. Provider

默认工作流目标:

- [CloudRift](https://www.cloudrift.ai/inference) · [DeepInfra](https://deepinfra.com/pricing) · [Fireworks](https://fireworks.ai/pricing#serverless-pricing) · [Groq](https://groq.com/pricing)

---

## 2. 安装

```bash
uv sync
cp .env.example .env
```

把 key 写进 `.env`(真实执行用):

```bash
ANTHROPIC_API_KEY=your_anthropic_key
FIRECRAWL_API_KEY=your_firecrawl_key
```

运行:

```bash
uv run python starter_client.py
```

示例提问:

```text
CloudRift 的 deepseek v3 多少钱?
DeepInfra 的 deepseek v3 多少钱?
对比 CloudRift 和 DeepInfra 的 deepseek v3 成本
```

---

## 3. 证据 / Demo 模式

不暴露私有 key 也能出证据 —— 支持确定性 demo 执行:

```bash
PRICESCOUT_DEMO_MODE=1 uv run python starter_client.py
```

Demo 模式跑同样的 MCP 工具 + 落库路径,但用本地定价文本代替调用 Firecrawl/Anthropic。`evidence.pdf` 展示:4/4 抓取成功 · SQLite 结构化提取 + `show data` · 最终自然语言对比 + 单测输出。

提交目录已排除 `.env`、`test.db`、`scraped_content/`、`.venv/`、`__pycache__/`。

---

## 许可

[MIT](LICENSE) © 2026 Leo Lin
