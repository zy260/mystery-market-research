"""
Agent 状态定义
================
用 LangGraph 的 TypedDict 定义整个 Agent 在运行过程中要维护的状态。

这个 state 就是 Agent 的"工作台"/"黑板书"——所有节点都能读写它，
用来记录：用户目标、推理过程、调用过的工具、中间产出、最终报告。
"""

from typing import Annotated, List, TypedDict
from operator import add


class AgentState(TypedDict, total=False):
    """LangGraph Agent 的共享状态。

    字段说明：
        task:       用户交给 Agent 的原始任务描述（如"帮我做一份悬疑推理书市研究"）
        books_data: 采集到 / 加载的书本数据（List[Dict]）
        analysis:   市场分析结果（MarketAnalyzer 产出）
        insight:    LLM/RAG 洞察结果
        plan:       智能排期/内容计划结果
        tools_used: 已经调用过的工具名列表（用于去重 / 进度回顾）
        think_log:  思维过程日志（思考-行动-观察的记录）
        final_report: Agent 收敛后产出的最终结论/汇报
    """

    task: str
    books_data: List[dict]
    last_result: str  # 最近一次工具的原始返回值
    next_action: str  # think 节点决定下一步要调用的工具名
    analysis: dict
    insight: dict
    plan: dict

    # 用 add 归约器：多个节点往同一个字段追加时是"拼接"而非覆盖
    tools_used: Annotated[List[str], add]
    think_log: Annotated[List[str], add]

    final_report: str
