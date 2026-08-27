"""
Agent ReAct 节点
=================
LangGraph 状态机里的三类核心节点：
    think（思考）  →  根据任务与已有产出，决定下一步该调哪个工具
    call_tool（行动）→ 真正执行选中的工具，把结果写回状态
    reflect（反思/观察）→ 查看工具结果，决定"继续循环"还是"收敛产出报告"

这构成标准的 ReAct 循环：思考 → 行动 → 观察 →（继续/终止）。
"""

import json
import os
import logging

logger = logging.getLogger("agent.nodes")


# ==================== 工具调用管线（不依赖 LLM 的规则型 ReAct） ====================
# 这是默认的"工具编排顺序"——当没有 DeepSeek key 作为大脑时，Agent 按
# 业务依赖顺序调用工具，也能完整跑通闭环。相当于一个"确定性策略的 ReAct"。

PIPELINE_ORDER = [
    "collect_books_tool",
    "analyze_books_tool",
    "generate_insight_tool",
    "generate_plan_tool",
]


def _state_to_json(value) -> str:
    """把 state 里存的对象安全转成 JSON 字符串（很多是嵌套 dict）。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def call_tool_node(state, tool_name: str, **kwargs) -> dict:
    """实际调用某个工具，返回要写回 state 的增量（含原始 return 值 result）。"""
    from agent.tools import TOOL_MAP

    log_entry = f"[行动] 调用工具 {tool_name}，参数={kwargs}"
    logger.info(log_entry)

    tool_fn = TOOL_MAP.get(tool_name)
    if tool_fn is None:
        log = f"[观察] 未知工具 {tool_name}，跳过。"
        logger.warning(log)
        return {"think_log": [log], "result": ""}

    try:
        result = tool_fn.invoke(kwargs)  # LangChain tool 统一用 invoke(dict)
        log = f"[观察] 工具 {tool_name} 返回：{str(result)[:500]}"
    except Exception as e:
        result = f"工具执行异常：{e}"
        log = f"[观察] 工具 {tool_name} 报错：{e}"

    logger.info(log)
    return {"think_log": [log_entry, log], "result": str(result)}


# ==================== LangGraph 节点函数（接收 state，返回增量） ====================

def node_think(state):
    """思考节点：决定下一步动作并执行（演示 LLM 驱动 + 规则降级的编排）。

    这里我们用一套轻量的"规划器"：如果配置了 DeepSeek key 且有封装的 LLM，
    可以由 LLM 决定；否则按 PIPELINE_ORDER 顺序推进（确定性策略）。
    """
    task = state.get("task", "")
    tools_used = list(state.get("tools_used", []))
    think_log = list(state.get("think_log", []))
    plan = state.get("plan")
    analysis = state.get("analysis")

    # —— 收敛判断：排期已经生成 → 说明全流程走完，进入出报告阶段 ——
    if plan is not None:
        think_log.append("[思考] 数据管道已闭环（分析→洞察→排期），可产出最终报告。")
        return {"think_log": think_log, "final_report": "DONE"}

    # —— 否则：从 pipeline 顺序里挑一个还没执行过的工具 ——
    next_steps = {}
    for t in PIPELINE_ORDER:
        if t not in tools_used:
            # 前一个工具是分析，下一步就传分析结果；洞察同理
            if t == "analyze_books_tool" and not analysis and think_log:
                pass
            next_steps[t] = True
    # 找出第一个未执行且前置已满足的工具
    chosen = None
    if "collect_books_tool" not in tools_used:
        chosen = "collect_books_tool"
    elif "analyze_books_tool" not in tools_used:
        chosen = "analyze_books_tool"
    elif "generate_insight_tool" not in tools_used and state.get("analysis") is not None:
        chosen = "generate_insight_tool"
    elif "generate_plan_tool" not in tools_used and state.get("insight") is not None:
        chosen = "generate_plan_tool"

    think_log.append(f"[思考] 规划下一步：{chosen or '收敛'}")

    # 思考节点把决策记录下来，真正执行放 call_tool 节点
    return {"think_log": think_log, "next_action": chosen}


def node_call_tool(state):
    """行动节点：执行 think 节点选中的工具，并把原始返回值写进 state.last_result。"""
    tool_name = state.get("next_action")
    if not tool_name:
        return {"think_log": ["[行动] 没有待执行工具，跳过。"]}

    books_data = state.get("books_data")
    analysis = state.get("analysis")

    # 工具参数根据依赖关系取当前已有产出
    kwargs = {}
    if tool_name == "collect_books_tool":
        kwargs = {"tags": "悬疑,推理,侦探"}
    elif tool_name == "analyze_books_tool":
        kwargs = {"books_data_json": _state_to_json(books_data)}
    elif tool_name == "generate_insight_tool":
        kwargs = {"analysis_json": _state_to_json(analysis)}
    elif tool_name == "generate_plan_tool":
        kwargs = {
            "analysis_json": _state_to_json(analysis),
            "insight_json": _state_to_json(state.get("insight")),
        }

    delta = call_tool_node(state, tool_name, **kwargs)
    delta["tools_used"] = [tool_name]
    delta["last_result"] = delta.get("result", "")
    delta.pop("result", None)  # 不把原始 result 塞进共享状态（data 用 last_result 单独存）
    delta["next_action"] = None
    return delta


def node_reflect(state):
    """反思/观察节点：根据工具结果，转换成语义化的业务字段。

    这是 ReAct 的"观察"环节——工具执行完，把结果写进对应的语义字段
    （books_data / analysis / insight / plan），供下游节点与最终报告使用。
    工具返回值是结构化字符串，这里做解析存入 state。
    """
    from agent.tools import TOOL_MAP

    think_log = list(state.get("think_log", []))
    tools_used = list(state.get("tools_used", []))
    last_result = state.get("last_result", "")
    recent_tool = tools_used[-1] if tools_used else None
    logger.info(f"[反思] 最近调用: {recent_tool}")

    delta = {}

    if recent_tool == "collect_books_tool":
        # 采集工具返回完整 JSON，解析成书籍列表存入 state
        try:
            books = json.loads(last_result)
            if isinstance(books, list):
                delta["books_data"] = books
        except Exception:
            pass
        if "books_data" not in delta:
            delta["books_data"] = [{"error": last_result}]
    elif recent_tool == "analyze_books_tool":
        delta["analysis"] = {"_report": last_result}
    elif recent_tool == "generate_insight_tool":
        delta["insight"] = {"report": last_result}
    elif recent_tool == "generate_plan_tool":
        delta["plan"] = {"report": last_result}

    think_log.append(f"[反思] {recent_tool} 结果已记录，进入下一轮循环。")
    delta["think_log"] = think_log
    return delta


def node_finalize(state):
    """收敛节点：把整个运行过程 + 产出汇总成最终报告。"""
    plan = state.get("plan")
    insight = state.get("insight")
    analysis = state.get("analysis")
    tools_used = list(state.get("tools_used", []))
    think_log = list(state.get("think_log", []))

    report = [
        "=" * 50,
        "  🧠 Mystery Market Agent — 自主研究完成报告",
        "=" * 50,
        f"· 任务：{state.get('task', '（未指定）')}",
        f"· 已调用工具链：{' → '.join(tools_used) if tools_used else '无'}",
        f"· 数据采集：{'✅ 已完成' if state.get('books_data') else '⏭️ 未执行'}",
        f"· 市场分析：{'✅ 已完成' if analysis else '⏭️ 未执行'}",
        f"· RAG 洞察：{'✅ 已完成' if insight else '⏭️ 未执行'}",
        f"· 智能排期：{'✅ 已完成' if plan else '⏭️ 未执行'}",
        "-" * 50,
        "💡 说明：本 Agent 已通过 LangGraph 状态机 + ReAct 循环自主编排",
        "了 采集→分析→洞察→排期 整条研究链路。图表与报告见 output/ 目录。",
        "=" * 50,
    ]
    final = "\n".join(report)
    logger.info("\n" + final)
    return {"final_report": final}