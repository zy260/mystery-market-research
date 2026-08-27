"""
Agent 工具封装
================
用 LangChain 的 @tool 装饰器，把现有管道模块（采集/入库/分析/洞察/排期）
包装成 Agent 可以自主调用的工具。

每个工具的 docstring 写得非常清楚——因为 ReAct 模式下，LLM 就是靠读
docstring 来"思考该调用哪个工具"的。
"""

from langchain_core.tools import tool

import json

from collect.douban_collector import DoubanCollector
from store.mysql_store import MySQLStore
from analyze.analyzer import MarketAnalyzer
from llm.insight_engine import InsightEngine
from plan.planner import ContentPlanner


@tool
def collect_books_tool(tags: str = "悬疑,推理,侦探") -> str:
    """从豆瓣采集悬疑推理类书籍数据。

    参数:
        tags: 逗号分隔的标签，如 "悬疑,推理,侦探"。默认抓取热门题材。

    返回:
        采集到的书籍 JSON 字符串（评分、评价人数、标签、作者、简介、出版社等）。
    """
    tag_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    try:
        collector = DoubanCollector()
        books = collector.collect_by_tags(tags=tag_list or None)
        n = len(books)
        # 返回完整 JSON（让 Agent 状态携带真实数据供下游分析工具使用）
        return json.dumps(books, ensure_ascii=False, default=str)
    except Exception as e:
        return f"采集失败：{e}"


@tool
def store_to_mysql_tool(books_data_json: str) -> str:
    """把书籍数据写入 MySQL（库不存在会自动建库建表）。

    参数:
        books_data_json: 书籍数据 JSON 字符串。

    返回:
        写入结果说明。
    """
    import json
    try:
        books = json.loads(books_data_json) if books_data_json else []
        if not books:
            return "没有可入库的数据"
        store = MySQLStore()
        store.ensure_table_exists()
        count = store.upsert_books(books)
        store.close()
        return f"已入库 {count} 条记录到 MySQL（mystery_books 库）"
    except Exception as e:
        return f"MySQL 入库失败：{e}（不影响后续分析，可继续）"


@tool
def analyze_books_tool(books_data_json: str) -> str:
    """对书籍数据做多维度市场分析（评分分布/标签热度/年份趋势/出版社帕累托/四象限）。

    参数:
        books_data_json: 书籍数据 JSON 字符串。

    返回:
        分析结果摘要（各维度统计 + 图表已生成的提示）。
    """
    import json
    try:
        books = json.loads(books_data_json) if books_data_json else []
        analyzer = MarketAnalyzer()
        results = analyzer.run_full_analysis(books)
        # 产出摘要
        bs = results.get("basic_stats", {})
        summary = (
            f"分析完成，共 {len(books)} 本书。"
            f"平均评分 {bs.get('avg_rating')}，"
            f"中位好评 {bs.get('median_rating')}。"
            f"图表已保存至 output/（5 张）。"
        )
        return summary
    except Exception as e:
        return f"分析失败：{e}"


@tool
def generate_insight_tool(analysis_json: str) -> str:
    """基于分析结果生成市场洞察（DeepSeek + RAG 知识库；未配 key 走规则引擎）。

    参数:
        analysis_json: 分析结果 JSON 字符串。

    返回:
        洞察报告全文。
    """
    import json
    try:
        analysis = json.loads(analysis_json) if analysis_json else {}
        engine = InsightEngine()
        engine.build_knowledge_base()
        result = engine.generate_insight(analysis)
        return f"[来源: {result.get('source')}]\n{result.get('insight')}"
    except Exception as e:
        return f"洞察生成失败：{e}"


@tool
def generate_plan_tool(analysis_json: str, insight_json: str) -> str:
    """基于分析和洞察生成 4 周智能排期内容计划。

    参数:
        analysis_json: 分析结果 JSON 字符串。
        insight_json:  洞察结果 JSON 字符串。

    返回:
        排期计划（JSON 概要）。
    """
    import json
    try:
        analysis = json.loads(analysis_json) if analysis_json else {}
        insight = json.loads(insight_json) if insight_json else {}
        planner = ContentPlanner()
        result = planner.generate_plan(analysis, insight)
        plan = result.get("schedule", result)
        return f"排期计划已生成，输出至 output/content_plan.json 与 .md。摘要：{str(plan)[:400]}"
    except Exception as e:
        return f"排期生成失败：{e}"


# 暴露给图组装用的工具清单（LangGraph 里会遍历它）
TOOLS = [
    collect_books_tool,
    store_to_mysql_tool,
    analyze_books_tool,
    generate_insight_tool,
    generate_plan_tool,
]

# 工具名 -> 实际函数 的映射，用于"反射"节点选择调用
TOOL_MAP = {t.name: t for t in TOOLS}