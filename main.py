#!/usr/bin/env python3
"""
悬疑推理书籍市场研究系统 — 主入口
==================================
一键运行完整数据流管道：

  豆瓣采集 → MySQL存储 → pandas分析 → LLM洞察(RAG) → 智能排期

使用方式：
  # 完整流程（需要MySQL + 可选DeepSeek API）
  python main.py --full

  # 仅采集 + 分析（不需要数据库和API）
  python main.py --collect-only

  # 从已有数据文件分析（跳过采集）
  python main.py --from-file data/books_data.json

环境变量（可选）：
  MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
  DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
"""

import argparse
import json
import logging
import os
import sys

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collect.douban_collector import DoubanCollector
from store.mysql_store import MySQLStore
from analyze.analyzer import MarketAnalyzer
from llm.insight_engine import InsightEngine
from plan.planner import ContentPlanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def run_full_pipeline():
    """运行完整的数据流管道"""
    logger.info("=" * 60)
    logger.info("  悬疑推理书籍市场研究系统 — 启动完整流水线")
    logger.info("=" * 60)

    books_data = []

    # ====== 阶段1：数据采集 ======
    logger.info("\n📡 [阶段1/5] 数据采集 — 豆瓣")
    collector = DoubanCollector()
    books_data = collector.collect_by_tags()

    if not books_data:
        logger.error("❌ 采集到0条数据，无法继续。请检查网络或反爬状态。")
        return

    # 保存原始数据备份（用绝对路径定位到项目 data 目录）
    project_root = os.path.dirname(os.path.abspath(__file__))
    data_backup_path = os.path.join(project_root, "data", "books_data.json")
    os.makedirs(os.path.join(project_root, "data"), exist_ok=True)
    with open(data_backup_path, "w", encoding="utf-8") as f:
        json.dump(books_data, f, ensure_ascii=False, indent=2)
    logger.info(f"💾 原始数据已备份至: {data_backup_path}")

    # ====== 阶段2：MySQL 存储 ======
    logger.info("\n💾 [阶段2/5] 数据存储 — MySQL")
    try:
        store = MySQLStore()
        store.ensure_table_exists()
        count = store.upsert_books(books_data)
        logger.info(f"✅ 已写入 {count} 条记录到 MySQL")

        # 从数据库重新读取（确保数据一致性）
        books_data = store.fetch_all_books()
        store.close()
    except Exception as e:
        logger.warning(f"⚠️ MySQL 存储失败 ({e})，使用内存数据继续分析")

    # ====== 阶段3：数据分析 ======
    logger.info("\n📊 [阶段3/5] 数据分析 — pandas + matplotlib")
    analyzer = MarketAnalyzer()
    analysis_results = analyzer.run_full_analysis(books_data)

    # ====== 阶段4：LLM 洞察 (RAG) ======
    logger.info("\n🧠 [阶段4/5] LLM 洞察 — DeepSeek + RAG")
    insight_engine = InsightEngine()
    insight_engine.build_knowledge_base()
    insight_result = insight_engine.generate_insight(analysis_results)

    # 保存洞察报告
    project_root = os.path.dirname(os.path.abspath(__file__))
    insight_path = os.path.join(project_root, "output", "insight_report.txt")
    os.makedirs(os.path.join(project_root, "output"), exist_ok=True)
    with open(insight_path, "w", encoding="utf-8") as f:
        f.write(insight_result["insight"])
    logger.info(f"💡 洞察报告已保存: {insight_path}")
    logger.info(f"   （来源: {insight_result['source']}）")

    # 打印洞察摘要
    print("\n" + "=" * 60)
    print("  🧠 AI 市场洞察摘要")
    print("=" * 60)
    print(insight_result["insight"][:1500])
    if len(insight_result["insight"]) > 1500:
        print("\n... (完整版见 output/insight_report.txt)")
    print("=" * 60)

    # ====== 阶段5：智能排期 ======
    logger.info("\n📅 [阶段5/5] 智能排期 — 内容计划生成")
    planner = ContentPlanner()
    plan_result = planner.generate_plan(analysis_results, insight_result)

    # ====== 完成 ======
    logger.info("\n" + "🎉" * 20)
    logger.info("  全部流程执行完毕！")
    logger.info("=" * 60)
    logger.info(f"  📁 输出目录: output/")
    logger.info(f"  📊 分析图表: output/01~05_*.png")
    logger.info(f"  📝 数据报告: output/analysis_report.txt")
    logger.info(f"  🧠 洞察报告: output/insight_report.txt")
    logger.info(f"  📅 排期计划: output/content_plan.json / .md")
    logger.info("=" * 60)

    return {
        "books_count": len(books_data),
        "analysis": analysis_results,
        "insight": insight_result,
        "plan": plan_result,
    }


def run_collect_only():
    """仅运行采集模块，保存为JSON文件"""
    logger.info("📡 仅运行数据采集模式...")
    collector = DoubanCollector()
    books_data = collector.collect_by_tags()

    project_root = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(project_root, "data"), exist_ok=True)
    path = os.path.join(project_root, "data", "books_data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(books_data, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 采集完成！{len(books_data)} 本书已保存至 {path}")
    return books_data


def run_from_file(filepath):
    """从已有的JSON数据文件开始分析和洞察"""
    logger.info(f"📂 从文件加载数据: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        books_data = json.load(f)
    logger.info(f"   加载了 {len(books_data)} 条记录")

    # 跳过采集和存储，直接进入分析
    analyzer = MarketAnalyzer()
    analysis_results = analyzer.run_full_analysis(books_data)

    insight_engine = InsightEngine()
    insight_engine.build_knowledge_base()
    insight_result = insight_engine.generate_insight(analysis_results)

    project_root = os.path.dirname(os.path.abspath(__file__))
    insight_path = os.path.join(project_root, "output", "insight_report.txt")
    os.makedirs(os.path.join(project_root, "output"), exist_ok=True)
    with open(insight_path, "w", encoding="utf-8") as f:
        f.write(insight_result["insight"])

    planner = ContentPlanner()
    plan_result = planner.generate_plan(analysis_results, insight_result)

    logger.info("✅ 从文件模式完成！")
    return {"analysis": analysis_results, "insight": insight_result, "plan": plan_result}


def run_agent(args):
    """运行 LangGraph Agent 模式（--agent / --agent-ask）。"""
    from agent.run_agent import dispatch
    task = args.agent_ask or "对悬疑推理书籍市场做一次完整研究：采集数据、分析市场、生成洞察、制定排期"
    logger.info(f"🧠 启动 Agent 任务：{task}")
    return dispatch(task)


# ==================== CLI 入口 ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="悬疑推理书籍市场研究系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py --full              # 完整流程
  python main.py --collect-only      # 仅采集
  python main.py --from-file data/books_data.json  # 从文件分析
  python main.py --agent             # LangGraph Agent 自主编排完整研究
  python main.py --agent-ask "悬疑市场什么方向值得做？"  # 带目标一问一答
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--full", action="store_true", help="运行完整流水线")
    group.add_argument("--collect-only", action="store_true", help="仅采集数据")
    group.add_argument("--from-file", type=str, help="从JSON文件加载并分析")
    group.add_argument("--agent", action="store_true", help="用 LangGraph Agent 自主编排完整研究")
    group.add_argument("--agent-ask", type=str, help="带具体目标给 Agent，让它自主规划完成")
    args = parser.parse_args()

    if args.full:
        run_full_pipeline()
    elif args.collect_only:
        run_collect_only()
    elif args.from_file:
        run_from_file(args.from_file)
    elif args.agent or args.agent_ask:
        run_agent(args)
    else:
        # 默认：显示帮助信息
        parser.print_help()
        print("\n💡 提示: 使用 --full 运行完整流程，--agent 用 Agent 自主编排，或 --collect-only 仅采集数据")
