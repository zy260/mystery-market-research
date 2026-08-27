# 🔍 悬疑推理书籍市场研究系统

> **自动研究大众口味的机器** — 从数据采集到智能决策的完整闭环

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📖 项目简介

这是一套**数据驱动的悬疑推理书籍市场研究系统**，通过自动化数据流管道回答三个核心问题：

1. **大众现在喜欢什么？** — 哪类悬疑题材在涨、哪类在退
2. **为什么喜欢？** — 高口碑的书赢在哪：强逻辑、烧脑反转、还是人性深度
3. **接下来内容该怎么安排？** — 下一阶段做哪类、排期怎么排

## 🏗️ 系统架构

```
                ┌────────────────────────────────────────────┐
                │       🧠 Agent 智能编排层 (agent/)           │
                │   LangGraph 状态机 + LangChain @tool + ReAct │
                │   思考 → 行动 → 观察 →（循环直到收敛）          │
                └────────────────────────────────────────────┘
                                │ 自主调用
        ┌──────────┬──────────┐─┴─┬──────────┬──────────┐
        ▼          ▼          ▼   ▼          ▼          ▼
┌────────────┐┌──────────┐┌────────────┐┌────────────┐┌────────────┐
│  数据采集   ││  数据存储 ││  数据分析  ││ LLM洞察+RAG││ 智能排期    │
│ (豆瓣爬虫) ││ (MySQL)  ││ (pandas)  ││(DeepSeek) ││(计划生成)  │
│ collect/   ││ store/   ││ analyze/  ││   llm/    ││   plan/    │
└────────────┘└──────────┘└────────────┘└────────────┘└────────────┘
   书名/评分     UPSERT    评分分布/趋势   人话洞察报告    周度排期计划
   作者/标签     去重沉淀    四象限分析     RAG知识库增强   优先级排序

◆ 两种运行模式并行：
   --full   → 确定性随机管线（按固定顺序执行）
   --agent  → 由 Agent 自主思考、决策调用顺序（ReAct 循环，直到收敛）
```

> 传统管道模式把每一步"写死"；Agent 模式则把每一步包装成**工具**，由 LLM 自主思考下一步该调用哪个、按什么顺序，实现**从"固定流程"到"自主编排"**的升级。

## ✨ 核心功能

| 模块 | 功能说明 | 技术栈 |
|------|---------|--------|
| 🕷️ **数据采集** | 从豆瓣按标签抓取书单+详情页，提取评分、评价人数、作者、出版社等字段 | `requests` + `BeautifulSoup4` |
| 💾 **数据存储** | PyMySQL 驱动，UPSERT 去重写入 MySQL，支持断点续采 | `PyMySQL` + `MySQL` |
| 📊 **数据分析** | 评分分布、题材词频、年份趋势、出版社集中度、四象限分析（评分×热度） | `pandas` + `matplotlib` |
| 🧠 **LLM洞察** | DeepSeek API 将统计结果翻译成人话结论；RAG 注入写作方法论知识库增强判断 | `DeepSeek API` + 自研向量检索 |
| 📅 **智能排期** | 多维度加权打分（热度/口碑/趋势/差异化），自动生成周级更新计划 | 纯 Python 排序算法 |
| 🧠 **Agent 编排** | LangGraph 状态机自主编排全流程，ReAct 循环：思考→行动→观察→收敛 | `LangGraph` + `LangChain Core` |

## 🚀 快速开始

### 环境要求

- Python 3.8+
- MySQL 5.7+ / 8.0（可选，不配置时跳过存储步骤）
- DeepSeek API Key（可选，不配置时使用内置规则引擎）

### 安装依赖

```bash
cd mystery-market-research
pip install -r requirements.txt
```

### 运行方式

```bash
# 方式一：完整流水线（采集→存储→分析→洞察→排期）
python main.py --full

# 方式二：仅采集数据（保存为JSON）
python main.py --collect-only

# 方式三：从已有数据文件分析（跳过采集）
python main.py --from-file data/books_data.json

# 方式四：Agent 自主编排（LangGraph + ReAct，自动决策调用顺序）
python main.py --agent

# 方式五：Agent 一问一答式（带研究目标）
python main.py --agent-ask "悬疑推理市场什么方向值得深耕？"
```

> **Agent 依赖说明**：`--agent` 依赖 `langgraph` + `langchain-core`。未安装时程序会自动降级为顺序管道执行（功能等价、不会报错）。安装请执行 `pip install -r requirements.txt`。

### 环境变量配置（可选）

```bash
# MySQL 配置
export MYSQL_HOST=localhost
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_PASSWORD=your_password
export MYSQL_DB=mystery_books

# DeepSeek LLM 配置
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxx
export DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

## 📁 项目结构

```
mystery-market-research/
├── main.py                    # 主入口，一键运行完整流水线 或 Agent
├── config/
│   └── settings.py            # 全局配置（豆瓣/MySQL/LLM/RAG/分析参数）
├── agent/                     # 🧠 Agent 智能编排模块（LangGraph + LangChain + ReAct）
│   ├── __init__.py
│   ├── state.py               # Agent 状态定义（TypedDict + 字段归约器）
│   ├── tools.py               # 用 @tool 包装 采集/入库/分析/洞察/排期 工具
│   ├── nodes.py               # ReAct 节点：思考 / 行动 / 观察 / 收敛
│   ├── graph.py               # LangGraph 状态机图组装
│   └── run_agent.py           # Agent 入口 + 优雅降级顺序管道
├── collect/
│   ├── __init__.py
│   └── douban_collector.py    # 豆瓣数据采集器（列表页+详情页）
├── store/
│   ├── __init__.py
│   └── mysql_store.py         # MySQL 存储管理器（建表/UPSERT/查询）
├── analyze/
│   ├── __init__.py
│   └── analyzer.py            # 数据分析器（6大维度 + 5张可视化图表）
├── llm/
│   ├── __init__.py
│   └── insight_engine.py      # LLM洞察引擎 + RAG知识库
├── plan/
│   ├── __init__.py
│   └── planner.py             # 智能排期计划生成器
├── data/
│   └── knowledge_base.txt     # 内置写作方法论知识库
├── output/                    # 输出目录（运行后生成）
│   ├── 01_rating_distribution.png
│   ├── 02_tag_popularity.png
│   ├── 03_year_trend.png
│   ├── 04_publisher_concentration.png
│   ├── 05_quadrant_analysis.png
│   ├── analysis_report.txt
│   ├── insight_report.txt
│   ├── content_plan.json
│   ├── content_plan.md
│   └── agent_log.txt          # Agent 自主研究过程回放（--agent 模式）
├── requirements.txt
├── README.md
└── .gitignore
```

## 📊 输出产物

运行 `--full` 模式后，在 `output/` 目录下生成：

| 文件 | 说明 |
|------|------|
| `01~05_*.png` | 5张高分辨率分析图表 |
| `analysis_report.txt` | 结构化数据统计报告 |
| `insight_report.txt` | AI 生成的市场洞察（人话版） |
| `content_plan.json` | 完整排期计划（机器可读） |
| `content_plan.md` | 排期计划（人类可读 Markdown） |
| `agent_log.txt` | `--agent` 模式下的 Agent 自主研究过程回放 |

## 🧠 Agent 智能编排模块（核心亮点 ✨）

本系统不只是一条死板的流水线，而是提供了一套 **LangGraph + LangChain + ReAct 构建的智能体**，能像研究员一样"思考—行动—观察"自主完成整套市场研究。

### 为什么需要 Agent？

传统管道模式把「采集→分析→洞察→排期」的顺序**写死在代码里**。而 Agent 模式把每一步封装成**可被自主调用的工具**，LLM 核心根据实时结果**决定下一步该做什么**，实现了从"固定流程"到"自主决策"的升级——这正是 Agent 岗最看重的能力。

### 技术栈

| 组件 | 用途 |
|------|------|
| `LangGraph` | `StateGraph` 状态机，显式定义节点 + 条件边，编排 ReAct 循环 |
| `LangChain Core` | `@tool` 装饰器，把管道模块包装成 LLM 可调用的工具（含结构化 docstring 供 LLM 理解） |
| `ReAct 范式` | 思考(Think) → 行动(Act) → 观察(Observe) 循环，直到达成目标收敛 |

### 核心设计

```
AgentState（TypedDict）
 ├─ task         # 目标
 ├─ books_data / analysis / insight / plan   # 各阶段产出（真实数据流动）
 ├─ tools_used / think_log                   # 用 Annotated[List, add] 归约器拼接
 └─ next_action / last_result                # 当前决策 + 上一工具返回

图结构：
 START → [node_think] →?→ [node_call_tool] → [node_reflect] ↘
        （决策下一步）    （执行工具）        （解析结果）      ↺ 回到 think（直到收敛）
       plan 已生成 → [node_finalize] → 生成最终报告 → END
```

- **零人工干预**：只需给 Agent 一个目标（`--agent` 或 `--agent-ask "..."`），其余全自主编排
- **真实数据流动**：采集到的完整书籍 JSON 会作为状态在各个工具间传递，而非拼接字符串
- **优雅降级**：未安装 `langgraph` 时自动退化为顺序管道，功能等价、绝不报错
- **过程可观测**：think_log 完整回放每一步思考，输出至 `output/agent_log.txt`，方便调试与演示
- **5 个工具**：`collect_books_tool` / `store_to_mysql_tool` / `analyze_books_tool` / `generate_insight_tool` / `generate_plan_tool`

### 运行 Agent

```bash
python main.py --agent                        # 全自动跑一遍研究
python main.py --agent-ask "悬疑哪类题材涨得最快？"  # 带目标的一问一答
```

## 🔬 分析维度详解

### 1️⃣ 评分分布
- 直方图展示所有书籍的评分分布
- 分段统计：<6 / 6-7 / 7-7.5 / 7.5-8 / 8-8.5 / 8.5-9 / >9

### 2️⃣ 热门标签 TOP-N
- 词频统计用户打的标签
- 揭示当前最火的细分题材方向

### 3️⃣ 出版趋势
- 近25年出版数量折线图 + 平均评分叠加线
- 判断品类处于上升/下降/平稳哪个阶段

### 4️⃣ 出版社集中度
- 帕累托图（柱状图 + 累计曲线）
- 计算 CR5（前5家占比），识别头部玩家

### 5️⃣ 四象限分析 ⭐
- **横轴**：评价人数（热度/对数刻度）
- **纵轴**：豆瓣评分（口碑）
- **四个象限**：
  - 🟢 叫好又叫座 — 主力学习对象
  - 🔵 高口碑低热度 — 蓝海机会
  - 🟠 高热度低口碑 — 营销强但品质待提升
  - 🔴 冷门低分 — 避坑区域

## 🧠 RAG 知识库

系统内置一份 **悬疑推理写作方法论知识库**，包含：

- 高口碑悬疑书的共同特征
- 当前市场趋势观察
- 写作实操技巧（红鲱鱼设计、信息差控制、节奏公式）
- 常见失败模式及规避方法
- 出版与运营建议

LLM 生成洞察时会自动检索相关知识片段作为参考依据，让结论从"数据统计"上升到"有行业经验的判断"。

## ⚠️ 注意事项

1. **反爬策略**：采集模块已内置随机延时（2.5~5秒）和真实 UA，但仍建议：
   - 不要短时间内大量请求
   - 如遇 403/418，程序会自动等待后重试
   
2. **MySQL 可选**：未配置 MySQL 时，系统会跳过存储步骤，使用内存数据继续分析和洞察

3. **DeepSeek 可选**：未配置 API Key 时，系统会使用内置规则引擎生成模板化洞察，效果依然可用

## 🛠️ 技术亮点（简历向）

- ✅ **LangGraph + LangChain Agent**：StateGraph 状态机 + `@tool` 工具封装 + ReAct 循环，实现从"固定流水线"到"自主编排"的升级
- ✅ **完整数据流管道**：采集→存储→分析→洞察→决策，端到端闭环
- ✅ **两种模式并存**：确定性管道（`--full`）与自主 Agent（`--agent`）可自由切换，优雅降级不崩
- ✅ **真实 MySQL 使用**：UPSERT 去重、索引优化、连接池管理
- ✅ **RAG 落地实践**：自研轻量向量检索 + 知识库分块 + 检索增强生成
- ✅ **多维度决策模型**：四维加权排序（热度/口碑/趋势/差异化）
- ✅ **工程化规范**：统一配置管理、结构化日志、异常处理、CLI 入口

## 📄 License

MIT License

## 👨‍💻 作者

Built with ❤️ for content creators & mystery lovers

---

> ⚠️ **免责声明**：本工具仅用于学习和研究目的。使用时请遵守豆瓣的 robots.txt 和服务条款，合理控制请求频率。
