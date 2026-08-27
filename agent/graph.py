"""
Agent 状态图组装
=================
用 LangGraph 的 StateGraph 把 think / call_tool / reflect / finalize 四个节点
串成一张"状态机"：

    START → think ──► call_tool ──► reflect
                    ▲                   │
                    └─────── 条件边 ─────┘（还有工具要跑则回到 think）

    当所有工具跑完 → 条件边跳转到 finalize ──► END

这张图就是 Agent 的"骨架"，节点是"脑"，边是"神经通路"。
"""

import logging

from langgraph.graph import StateGraph, START, END

from agent.state import AgentState
from agent import nodes

logger = logging.getLogger("agent.graph")


def route_after_think(state) -> str:
    """条件边：think 之后去哪个节点。

    - 若 think 已把 final_report 置为 DONE，说明该收敛了 → 直接去 finalize
    - 否则去 call_tool 执行工具
    """
    if state.get("final_report") == "DONE":
        return "finalize"
    return "call_tool"


def route_after_reflect(state) -> str:
    """条件边：reflect 之后去哪个节点。

    - 若 plan 已生成（全流程闭环），且 final_report 未置位 → 回 think 让它收敛
    - 否则回到 think 继续编排下一个工具
    """
    return "think"


def build_agent_graph():
    """构建并返回一个编译好的 LangGraph 状态图。"""
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("think", nodes.node_think)
    graph.add_node("call_tool", nodes.node_call_tool)
    graph.add_node("reflect", nodes.node_reflect)
    graph.add_node("finalize", nodes.node_finalize)

    # 连线：START → think
    graph.add_edge(START, "think")

    # think → (条件) → call_tool 或 finalize
    graph.add_conditional_edges(
        "think",
        route_after_think,
        {"call_tool": "call_tool", "finalize": "finalize"},
    )

    # call_tool → reflect
    graph.add_edge("call_tool", "reflect")

    # reflect → (条件) → think（回环继续编排下一工具）
    graph.add_conditional_edges(
        "reflect",
        route_after_reflect,
        {"think": "think"},
    )

    # finalize → END
    graph.add_edge("finalize", END)

    # 编译成可执行对象
    return graph.compile()


# 预编译一份，供 run_agent 反复调用
compiled_agent = build_agent_graph()