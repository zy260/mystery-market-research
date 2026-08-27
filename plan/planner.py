"""
智能内容排期计划生成器
========================
根据 LLM 洞察结论 + 数据分析结果，自动生成带优先级的内容更新计划。

功能：
- 综合热度/口碑/趋势/差异化四个维度打分排序
- 生成周级别的排期表（默认4周）
- 输出结构化的 JSON + 可读的 Markdown 计划文档
- 支持自定义权重配置
"""

import os
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import PLAN_CONFIG, ANALYZE_CONFIG

logger = logging.getLogger(__name__)


class ContentPlanner:
    """智能内容排期计划生成器"""

    def __init__(self):
        self.weights = PLAN_CONFIG["weights"]
        self.cycle_weeks = PLAN_CONFIG["planning_cycle_weeks"]
        self.output_dir = ANALYZE_CONFIG["output_dir"]
        os.makedirs(self.output_dir, exist_ok=True)

    # ==================== 主入口 ====================

    def generate_plan(self, analysis_results: Dict, insight_result: Dict) -> Dict:
        """
        根据分析结果和洞察结论，生成完整的排期计划

        Args:
            analysis_results: analyze 模块的输出
            insight_result: llm 模块的洞察输出

        Returns:
            排期计划字典（含方向列表、时间安排、JSON/Markdown输出路径）
        """
        logger.info("📅 开始生成智能排期计划...")

        # 1. 从数据中提取候选方向
        directions = self._extract_directions(analysis_results)

        # 2. 多维度评分排序
        scored_directions = self._score_and_rank(directions, analysis_results)

        # 3. 分配到各周
        weekly_schedule = self._allocate_to_weeks(scored_directions)

        # 4. 构建完整计划
        plan = {
            "meta": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "cycle_weeks": self.cycle_weeks,
                "total_directions": len(scored_directions),
                "insight_source": insight_result.get("source", "unknown"),
            },
            "directions": scored_directions,
            "weekly_schedule": weekly_schedule,
            "summary": self._build_summary(scored_directions, weekly_schedule),
        }

        # 5. 保存输出
        json_path = self._save_json(plan)
        md_path = self._save_markdown(plan, insight_result)

        plan["output_files"] = {"json": json_path, "markdown": md_path}
        logger.info(f"✅ 排期计划已生成！\n   JSON: {json_path}\n   MD: {md_path}")

        return plan

    # ==================== 方向提取 ====================

    def _extract_directions(self, results: Dict) -> List[Dict]:
        """从分析结果中提取候选创作方向"""
        directions = []

        # 从热门标签中提取题材方向
        ta = results.get("tag_analysis", {})
        if ta and ta.get("top_tags"):
            for item in ta["top_tags"][:12]:
                tag_name = item["tag"]
                # 过滤掉太泛的标签
                if tag_name in ["悬疑", "推理", "小说", "图书"]:
                    continue
                directions.append({
                    "name": f"{tag_name}题材",
                    "type": "tag_based",
                    "raw_tag": tag_name,
                    "popularity_score": item["count"],
                })

        # 从四象限中提取策略方向
        qa = results.get("quadrant", {})
        if qa and qa.get("examples"):
            # 高口碑低热度 → 蓝海机会
            hidden_gems = qa["examples"].get("高口碑低热度", [])
            if hidden_gems:
                directions.append({
                    "name": "高口碑低热度蓝海方向",
                    "type": "strategy",
                    "strategy": "blue_ocean",
                    "reference_books": [b["title"] for b in hidden_gems[:3]],
                    "popularity_score": len(hidden_gems) * 5,
                })

            # 叫好又叫座 → 主力方向
            star_books = qa["examples"].get("叫好又叫座", [])
            if star_books:
                directions.append({
                    "name": "叫好又叫座主力方向",
                    "type": "strategy",
                    "strategy": "mainstream",
                    "reference_books": [b["title"] for b in star_books[:3]],
                    "popularity_score": len(star_books) * 10,
                })

        # 从年份趋势中提取趋势方向
        yt = results.get("year_trend", {})
        if yt and yt.get("trend_direction") == "上升":
            directions.append({
                "name": "顺势增量方向（品类上升期）",
                "type": "trend",
                "trend": "rising",
                "popularity_score": 20,
            })

        # 如果提取的方向太少，补充一些通用方向
        if len(directions) < 5:
            default_dirs = [
                {"name": "社会派悬疑（现实议题+解谜）", "type": "default",
                 "popularity_score": 15},
                {"name": "女性视角悬疑", "type": "default", "popularity_score": 12},
                {"name": "短篇系列/单元剧式", "type": "default", "popularity_score": 10},
                {"name": "跨媒介IP潜力方向", "type": "default", "popularity_score": 8},
                {"name": "本土化原创悬疑", "type": "default", "popularity_score": 11},
            ]
            existing_names = {x["name"] for x in directions}
            for dd in default_dirs:
                if dd["name"] not in existing_names:
                    directions.append(dd)
                    existing_names.add(dd["name"])

        return directions

    # ==================== 评分排序 ====================

    def _score_and_rank(self, directions: List[Dict], results: Dict) -> List[Dict]:
        """对每个方向进行多维度加权评分"""
        bs = results.get("basic_stats", {})

        for d in directions:
            scores = {}

            # 1. 热度分 (0-100)：基于标签出现次数或评价人数
            raw_pop = d.get("popularity_score", 1)
            max_pop = max((x.get("popularity_score", 1) for x in directions), default=1)
            scores["popularity"] = (raw_pop / max_pop) * 100 if max_pop > 0 else 50

            # 2. 口碑分 (0-100)：基于参考书的平均评分
            ref_books = d.get("reference_books", [])
            if ref_books and results.get("quadrant", {}).get("examples"):
                # 尝试从四象限数据中找到这些书并取平均分
                all_examples = []
                for q_ex in results["quadrant"]["examples"].values():
                    all_examples.extend(q_ex)
                matching = [b for b in all_examples if b["title"] in ref_books]
                if matching:
                    avg_r = sum(b["rating"] for b in matching) / len(matching)
                    scores["rating"] = (avg_r / 9.0) * 100  # 满分9分≈100
                else:
                    scores["rating"] = 70  # 默认中等偏上
            else:
                avg_r = float(bs.get("avg_rating", 7.5) or 7.5)
                scores["rating"] = (avg_r / 9.0) * 100

            # 3. 趋势分 (0-100)
            strategy = d.get("strategy", "")
            trend_type = d.get("trend", "")
            if strategy == "blue_ocean":
                scores["trend"] = 85  # 蓝海高分
            elif strategy == "mainstream":
                scores["trend"] = 75  # 主力稳分
            elif trend_type == "rising":
                scores["trend"] = 90  # 上升期最高
            elif d.get("type") == "default":
                scores["trend"] = 65  # 默认方向中等
            else:
                scores["trend"] = 60

            # 4. 差异化分 (0-100)：竞争少但品质验证过的方向得分高
            if strategy == "blue_ocean":
                scores["gap"] = 95
            elif d.get("type") == "tag_based" and d.get("popularity_score", 0) < 15:
                scores["gap"] = 80  # 小众标签=差异化机会
            else:
                scores["gap"] = 50

            # 加权总分
            d["scores"] = scores
            d["total_score"] = round(
                sum(scores[k] * self.weights[k] for k in self.weights), 1
            )
            # 确定优先级等级
            if d["total_score"] >= 80:
                d["priority"] = "P0 — 立即启动"
            elif d["total_score"] >= 68:
                d["priority"] = "P1 — 本周启动"
            elif d["total_score"] >= 55:
                d["priority"] = "P2 — 两周内"
            else:
                d["priority"] = "P3 — 观察储备"

        # 按总分降序排列
        directions.sort(key=lambda x: x["total_score"], reverse=True)

        # 给排名
        for i, d in enumerate(directions):
            d["rank"] = i + 1

        return directions

    # ==================== 周分配 ====================

    def _allocate_to_weeks(self, directions: List[Dict]) -> List[Dict]:
        """将方向按优先级分配到各周"""
        schedule = []
        today = datetime.now()

        for week_num in range(1, self.cycle_weeks + 1):
            week_start = today + timedelta(weeks=week_num - 1)
            week_end = week_start + timedelta(days=6)

            # 每周分配2-3个主要方向
            start_idx = (week_num - 1) * 2
            end_idx = min(week_num * 2, len(directions))
            week_directions = directions[start_idx:end_idx]

            if not week_directions:
                break

            schedule.append({
                "week": week_num,
                "date_range": f"{week_start.strftime('%m/%d')} ~ {week_end.strftime('%m/%d')}",
                "focus_count": len(week_directions),
                "directions": [
                    {
                        "rank": d["rank"],
                        "name": d["name"],
                        "score": d["total_score"],
                        "priority": d["priority"],
                        "action_items": self._generate_action_items(d, week_num),
                    }
                    for d in week_directions
                ],
                "weekly_goal": self._generate_weekly_goal(week_directions, week_num),
            })

        return schedule

    @staticmethod
    def _generate_action_items(direction: Dict, week_num: int) -> List[str]:
        """为每个方向生成具体的行动项"""
        items = []
        name = direction["name"]

        if direction.get("type") == "tag_based":
            items.extend([
                f"调研「{direction.get('raw_tag', '')}」领域 TOP-10 代表作",
                f"拆解该题材的核心叙事模式和常见诡计类型",
                f"撰写{direction.get('raw_tag', '')}题材的选题大纲（1个）",
            ])
        elif direction.get("strategy") == "blue_ocean":
            items.extend([
                f"精读参考书：{'、'.join(direction.get('reference_books', [])[:2])}",
                "分析其'高口碑低热度'的原因（营销不足？小众？）",
                "设计可复制的成功要素+改进传播方案",
            ])
        elif direction.get("strategy") == "mainstream":
            items.extend([
                f"精读参考书：{'、'.join(direction.get('reference_books', [])[:2])}",
                "提炼其成功公式（节奏/人物/诡计/主题）",
                "在保留核心优势的基础上寻找差异化切入点",
            ])
        else:
            items.extend([
                f"完成「{name}」方向的竞品调研报告",
                f"撰写{1 if week_num <= 2 else 2}个选题大纲初稿",
                f"{'试写样章（3000字）' if week_num >= 2 else '完成世界观设定'}",
            ])

        return items

    @staticmethod
    def _generate_weekly_goal(week_directions: List[Dict], week_num: int) -> str:
        """生成本周目标描述"""
        names = "、".join([d["name"][:8] for d in week_directions])
        if week_num == 1:
            return f"本周重点：聚焦「{names}」，完成调研与选题立项"
        elif week_num == 2:
            return f"本周重点：推进「{names}」，完成大纲与样章写作"
        elif week_num == 3:
            return f"本周重点：深化「{names}」，进入正文撰写阶段"
        else:
            return f"本周重点：复盘「{names}」，评估效果并调整下一周期"

    # ==================== 输出保存 ====================

    def _save_json(self, plan: Dict) -> str:
        """保存 JSON 格式的完整计划"""
        path = os.path.join(self.output_dir, "content_plan.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        return path

    def _save_markdown(self, plan: Dict, insight: Dict) -> str:
        """保存可读性好的 Markdown 格式计划"""
        lines = []

        lines.append("# 📅 悬疑推理内容更新排期计划")
        lines.append("")
        lines.append(f"> 生成时间：{plan['meta']['generated_at']}")
        lines.append(f"> 计划周期：{plan['meta']['cycle_weeks']} 周")
        lines.append(f"> 洞察引擎：{plan['meta']['insight_source']}")
        lines.append("")

        # 总览
        lines.append("---")
        lines.append("## 📋 排期总览")
        lines.append("")
        lines.append("| 排名 | 方向 | 总分 | 优先级 | 类型 |")
        lines.append("|------|------|------|--------|------|")
        for d in plan["directions"]:
            lines.append(
                f"| {d['rank']} | {d['name']} | {d['total_score']} | "
                f"{d['priority']} | {d['type']} |"
            )
        lines.append("")

        # 各周详情
        lines.append("---")
        lines.append("## 🗓️ 周度安排")
        lines.append("")
        for week in plan["weekly_schedule"]:
            lines.append(f"### 第{week['week']}周 ({week['date_range']})")
            lines.append("")
            lines.append(f"> **本周目标**：{week['weekly_goal']}")
            lines.append("")
            for d in week["directions"]:
                lines.append(f"#### 🎯 [{d['priority']}] #{d['rank']} {d['name']}")
                lines.append(f"- 综合评分：**{d['score']}** 分")
                lines.append("- 行动项：")
                for item in d["action_items"]:
                    lines.append(f"  - [ ] {item}")
                lines.append("")
            lines.append("")

        # 附录：洞察摘要
        lines.append("---")
        lines.append("## 📌 附录：LLM 洞察要点")
        lines.append("")
        insight_text = insight.get("insight", "")
        if insight_text:
            # 只取前2000字符作为附录
            lines.append(insight_text[:2000])
            if len(insight_text) > 2000:
                lines.append("\n\n*(洞察全文已截断，完整版见 analysis_report.txt)*")

        md_text = "\n".join(lines)
        path = os.path.join(self.output_dir, "content_plan.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return path

    @staticmethod
    def _build_summary(directions: List[Dict], schedule: List[Dict]) -> str:
        """构建一句话总结"""
        if not directions:
            return "本周期暂无明确的创作方向，建议先补充调研再启动排期。"
        top3 = directions[:3]
        top_names = " → ".join([d["name"][:6] for d in top3])
        return (
            f"本周期共规划 {len(directions)} 个创作方向，"
            f"TOP-3 为：{top_names}。"
            f"建议第1周集中资源攻克「{top3[0]['name']}」。"
        )


# ==================== 快捷入口 ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    planner = ContentPlanner()
    print("排期模块就绪，请通过 main.py 或传入数据调用 generate_plan()")
