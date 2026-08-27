#!/usr/bin/env python3
"""
Agent 智能体入口
================
把整个"悬疑推理书籍市场研究"流程交给一个 LangGraph + LangChain + ReAct
构建的 Agent 来自主编排完成。

使用方式：
    python main.py --agent                 # 全自动跑一遍研究(采集→分析→洞察→排期)
    python main.py --agent-ask "悬疑市场什么方向值得做？"  # 带目标的一问一答式

设计要点：
    - 用 LangGraph StateGraph 组装状态机
    - 用 @tool 把 采集/入库/分析/洞察/排期 包装成可调用工具
    - ReAct 循环：思考 → 行动 → 观察 →（继续/收敛）
    - 优雅降级：未安装 langgraph 时，退化为"顺序管道式"执行，不崩。
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("agent.run")

DEFAULT_TASK = "对悬疑推理书籍市场做一次完整研究：采集数据、分析市场、生成洞察、制定排期"

# ==================== 真实 Agent（LangGraph） ====================

def run_agent_mode(task: str = DEFAULT_TASK):
    """走 LangGraph 状态机的完整 ReAct 编排。"""
    from agent.graph import compiled_agent

    # 初始状态：只给 Agent 一个目标，其余全靠它自主编排
    initial_state = {
        "task": task,
        "books_data": [],
        "last_result": "",
        "next_action": None,
        "analysis": None,
        "insight": None,
        "plan": None,
        "tools_used": [],
        "think_log": [],
    }

    logger.info("=" * 60)
    logger.info("  🧠 启动 LangGraph Agent — ReAct 自主编排")
    logger.info("=" * 60)

    # 运行状态机（LangGraph 会按图一路走到 END）
    result = compiled_agent.invoke(initial_state)

    print("\n\n" + "=" * 60)
    print("  🧠 Agent 自主研究过程回放")
    print("=" * 60)
    for line in result.get("think_log", []):
        print("  " + line)

    # 输出最终报告
    print("\n" + result.get("final_report", "（无报告）"))

    # 保存回放日志
    os.makedirs(os.path.join(os.path.dirname(__file__), "output"), exist_ok=True)
    with open(
        os.path.join(os.path.dirname(__file__), "output", "agent_log.txt"),
        "w",
        encoding="utf-8",
    ) as f:
        f.write("\n".join(result.get("think_log", [])))
        f.write("\n\n" + result.get("final_report", ""))
    logger.info("✅ Agent 回放已保存至 output/agent_log.txt")

    return result


# ==================== 优雅降级：顺序管道执行 ====================

def run_fallback_pipeline(task: str = DEFAULT_TASK):
    """当 langgraph 未安装时，退化为顺序执行的确定性管道（等价的工具编排）。"""
    from collect.douban_collector import DoubanCollector
    from analyze.analyzer import MarketAnalyzer
    from llm.insight_engine import InsightEngine
    from plan.planner import ContentPlanner

    logger.warning("langgraph 未安装，退化为顺序管道模式。pip install -r requirements.txt 可启用真 Agent。")
    print("=" * 60)
    print("  🧠 Agent（降级模式）— 顺序管道编排")
    print("=" * 60)

    # 1. 采集
    collector = DoubanCollector()
    books = collector.collect_by_tags()
    print(f"[行动] 采集：{len(books)} 本书")

    # 2. 分析
    analyzer = MarketAnalyzer()
    analysis = analyzer.run_full_analysis(books)
    print(f"[行动] 分析：完成")

    # 3. 洞察
    engine = InsightEngine()
    engine.build_knowledge_base()
    insight = engine.generate_insight(analysis)
    print(f"[行动] 洞察：{insight['source']}")

    # 4. 排期
    planner = ContentPlanner()
    plan = planner.generate_plan(analysis, insight)
    print(f"[行动] 排期：完成")

    print("=" * 60)
    print("  ✅ 降级管道执行完毕，报表见 output/ 目录")
    print("=" * 60)
    return {"analysis": analysis, "insight": insight, "plan": plan}


# ==================== 一键入口 ====================

def dispatch(task: str = DEFAULT_TASK):
    """根据依赖可用性，自动选择 LangGraph Agent 或降级管道。"""
    try:
        return run_agent_mode(task)
    except ImportError as e:
        logger.warning(f"Agent 依赖缺失（{e}），切换降级模式。")
        return run_fallback_pipeline(task)


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    dispatch(task)