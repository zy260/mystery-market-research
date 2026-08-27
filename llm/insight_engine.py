"""
DeepSeek LLM 洞察引擎 + RAG 知识库增强
========================================
将数据分析结果翻译成人话洞察，并利用 RAG（检索增强生成）
注入写作方法论/爆款知识库，让结论更有行业深度。

功能：
- 内置悬疑推理写作方法论知识库（分块向量化）
- 基于余弦相似度的文本检索（无需外部向量数据库）
- 调用 DeepSeek API 生成结构化市场洞察报告
- 输出：题材建议、创作方向、排期优先级依据
"""

import os
import re
import json
import logging
import pickle
from typing import List, Dict, Optional, Tuple

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import LLM_CONFIG, RAG_CONFIG

logger = logging.getLogger(__name__)


class InsightEngine:
    """LLM 洞察引擎（含 RAG 增强）"""

    def __init__(self):
        self.api_key = LLM_CONFIG["api_key"]
        self.base_url = LLM_CONFIG["base_url"]
        self.model = LLM_CONFIG["model"]
        self.system_prompt = LLM_CONFIG["system_prompt"]
        # RAG 组件
        self.knowledge_chunks: List[str] = []
        self.chunk_embeddings: Optional[List[List[float]]] = None

    # ==================== RAG：知识库管理 ====================

    def build_knowledge_base(self):
        """加载并分块内置知识库，计算嵌入向量"""
        kb_path = RAG_CONFIG["knowledge_base_path"]
        if not os.path.exists(kb_path):
            logger.warning(f"⚠️ 知识库文件不存在: {kb_path}，使用内置默认知识库")
            self._create_default_knowledge_base(kb_path)

        with open(kb_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        # 分块
        self.knowledge_chunks = self._chunk_text(raw_text,
                                                  LLM_CONFIG["rag_chunk_size"],
                                                  LLM_CONFIG["rag_overlap"])
        logger.info(f"📚 知识库已加载: {len(self.knowledge_chunks)} 个文本块")

        # 计算嵌入向量（用简单的 TF-IDF 风格的词频向量，避免依赖外部模型）
        self.chunk_embeddings = [self._text_to_vector(chunk) for chunk in self.knowledge_chunks]
        logger.info("✅ 向量化完成")

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
        """按固定大小分块，带重叠"""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += (chunk_size - overlap)
        return chunks

    @staticmethod
    def _text_to_vector(text: str) -> List[float]:
        """
        将文本转为词频向量（简化版 TF，用于相似度计算）
        不依赖外部 embedding 模型，适合离线环境。
        """
        import math
        text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text.lower())
        words = list(text)  # 中文字符级粒度
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        # 归一化
        norm = math.sqrt(sum(v * v for v in freq.values()))
        if norm == 0:
            return [0.0] * 100  # 固定维度占位
        # 取前100维（按字符编码取模分配到桶中）
        vector = [0.0] * 128
        for char, count in freq.items():
            idx = hash(char) % 128
            vector[idx] += count
        total = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / total for v in vector]

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5 or 1.0
        norm_b = sum(b * b for b in vec_b) ** 0.5 or 1.0
        return dot / (norm_a * norm_b)

    def retrieve_relevant(self, query: str, top_k: int = None) -> str:
        """
        根据查询从知识库中检索最相关的文本块

        Args:
            query: 查询文本（通常是分析结果的摘要）
            top_k: 返回top-k条

        Returns:
            拼接后的相关文本
        """
        if not self.knowledge_chunks or not self.chunk_embeddings:
            return ""
        top_k = top_k or LLM_CONFIG["rag_top_k"]

        query_vec = self._text_to_vector(query)
        scored = [
            (chunk, self._cosine_similarity(query_vec, emb))
            for chunk, emb in zip(self.knowledge_chunks, self.chunk_embeddings)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_chunks = [c[0] for c in scored[:top_k]]
        return "\n\n---\n\n".join(top_chunks)

    # ==================== LLM 洞察生成 ====================

    def generate_insight(self, analysis_results: Dict) -> Dict:
        """
        根据分析结果调用 DeepSeek 生成市场洞察报告

        Args:
            analysis_results: analyze 模块的输出字典

        Returns:
            包含原始回复、结构化解析、RAG引用来源的字典
        """
        if not self.api_key:
            logger.warning("⚠️ 未配置 DEEPSEEK_API_KEY，使用本地规则引擎生成洞察")
            return self._rule_based_insight(analysis_results)

        # 构建提示词
        user_prompt = self._build_prompt(analysis_results)

        # RAG 增强
        rag_context = self.retrieve_relevant(user_prompt)
        if rag_context:
            user_prompt = (
                f"【参考知识库内容】\n{rag_context}\n\n"
                f"---\n\n"
                f"请结合以上知识库中的方法论和经验，分析以下数据：\n\n{user_prompt}"
            )

        try:
            response = self._call_deepseek(self.system_prompt, user_prompt)
            insight_text = self._extract_response(response)

            return {
                "source": "deepseek_rag" if rag_context else "deepseek",
                "insight": insight_text,
                "prompt_used": user_prompt[:500],  # 截断保存
                "rag_citations_count": len(rag_context.split("---")) if rag_context else 0,
            }
        except Exception as e:
            logger.error(f"❌ DeepSeek API 调用失败: {e}，回退到规则引擎")
            return self._rule_based_insight(analysis_results)

    def _build_prompt(self, results: Dict) -> str:
        """构建发给 LLM 的用户提示词"""
        prompt_parts = []

        prompt_parts.append("以下是悬疑推理书籍市场的数据分析结果，请给出深度洞察：\n")

        # 基础统计
        bs = results.get("basic_stats", {})
        if bs:
            prompt_parts.append(
                f"## 数据概览\n"
                f"- 总量 {bs.get('total_books', 0)} 本，有评分 {bs.get('rated_books', 0)} 本\n"
                f"- 平均评分 {bs.get('avg_rating', 'N/A')}，中位 {bs.get('median_rating', 'N/A')}\n"
                f"- 评分范围 {bs.get('min_rating', '?')} ~ {bs.get('max_rating', '?')}\n"
                f"- 总评价数 {bs.get('total_ratings', 0):,}\n"
                f"- 涉及 {bs.get('unique_authors', 0)} 位作者，{bs.get('unique_publishers', 0)} 家出版社\n"
            )

        # 评分分布
        rd = results.get("rating_distribution", {})
        if rd and rd.get("distribution"):
            dist_str = "\n".join([f"  {k}: {v}本" for k, v in rd["distribution"].items()])
            prompt_parts.append(f"\n## 评分分布\n{dist_str}")

        # 标签热度
        ta = results.get("tag_analysis", {})
        if ta and ta.get("top_tags"):
            tags_str = ", ".join([f"{t['tag']}({t['count']})" for t in ta["top_tags"][:15]])
            prompt_parts.append(f"\n## 热门标签 TOP-15\n{tags_str}")

        # 年份趋势
        yt = results.get("year_trend", {})
        if yt:
            prompt_parts.append(
                f"\n## 出版趋势\n"
                f"- 方向: {yt.get('trend_direction', '未知')}\n"
                f"- 高峰年: {yt.get('peak_year', '?')}"
            )

        # 出版社
        pa = results.get("publisher_concentration", {})
        if pa and pa.get("top_publishers"):
            pub_str = "; ".join([
                f"{p['publisher']}({p['book_count']}本,均分{self._fmt(p.get('avg_rating'))})"
                for p in pa["top_publishers"][:8]
            ])
            prompt_parts.append(f"\n## 主要出版社\n{pub_str}")
            prompt_parts.append(f"- CR5集中度: {pa.get('cr5', '?')}%")

        # 四象限
        qa = results.get("quadrant", {})
        if qa and qa.get("examples"):
            prompt_parts.append("\n## 四象限代表作品")
            for q, examples in qa["examples"].items():
                titles = ", ".join([ex["title"] for ex in examples[:3]])
                prompt_parts.append(f"- [{q}] {titles}")

        prompt_parts.append(
            "\n\n请基于以上数据，输出以下内容：\n"
            "1. **市场现状总结**（3-5句话概括整体格局）\n"
            "2. **大众口味画像**（他们喜欢什么类型、什么风格）\n"
            "3. **高口碑书成功要素**（叫好又叫座的书赢在哪）\n"
            "4. **内容创作建议**（具体可操作的选题方向和写作策略）\n"
            "5. **风险提醒**（哪些方向已经饱和或正在衰退）\n"
            "6. **下一阶段重点推荐**（按优先级排列的3-5个方向）"
        )

        return "\n".join(prompt_parts)

    def _call_deepseek(self, system_prompt: str, user_prompt: str) -> str:
        """调用 DeepSeek Chat API"""
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 3000,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]

    @staticmethod
    def _fmt(val, ndigits: int = 1) -> str:
        """安全格式化数值：处理 None / NaN，避免 'nan' 或异常窜入报告"""
        if val is None:
            return "N/A"
        try:
            fv = float(val)
            import math
            if math.isnan(fv):
                return "N/A"
            return f"{fv:.{ndigits}f}"
        except (TypeError, ValueError):
            return "N/A"

    @staticmethod
    def _extract_response(response: str) -> str:
        """提取并清理 LLM 回复"""
        # 移除可能的 markdown 代码块标记
        response = re.sub(r"^```(?:markdown|text)?\s*\n", "", response.strip())
        response = re.sub(r"\n```\s*$", "", response.strip())
        return response.strip()

    # ==================== 规则引擎（无API时的降级方案）====================

    def _rule_based_insight(self, results: Dict) -> Dict:
        """不依赖外部 API 的本地规则引擎，根据统计规律生成模板化洞察"""
        lines = []
        lines.append("# 悬疑推理书籍市场洞察报告（规则引擎版）")
        lines.append("")
        lines.append("## 一、市场现状总结")

        bs = results.get("basic_stats", {})
        total = bs.get("total_books", 0)
        avg_r = bs.get("avg_rating", 0)
        lines.append(
            f"基于对豆瓣平台 {total} 本悬疑推理类书籍的数据分析，"
            f"该品类平均评分为 {avg_r}，整体口碑处于{'较高' if avg_r >= 7.5 else '中等' if avg_r >= 7 else '偏低'}水平。"
        )

        lines.append("")
        lines.append("## 二、大众口味画像")

        ta = results.get("tag_analysis", {})
        if ta and ta.get("top_tags"):
            top3 = ta["top_tags"][:3]
            tags_names = [t["tag"] for t in top3]
            lines.append(
                f"当前读者最关注的三大题材标签为：**{'、'.join(tags_names)}**。"
                f"这表明大众偏好{'强逻辑推理' if '推理' in str(tags_names) else '快节奏叙事'}类型的作品。"
            )
            # 判断是否有日系偏好
            has_japanese = any("日本" in t["tag"] or "东野圭吾" in t["tag"]
                               for t in ta["top_tags"][:10])
            if has_japanese:
                lines.append("- 日系推理作品在中文读者群体中仍有强大影响力。")

        lines.append("")
        lines.append("## 三、高口碑书成功要素")

        qa = results.get("quadrant", {})
        if qa and qa.get("examples"):
            star_books = qa["examples"].get("叫好又叫座", [])
            if star_books:
                titles = [b["title"] for b in star_books[:3]]
                lines.append(
                    f"以《{'》《'.join(titles)}》为代表的「叫好又叫座」作品通常具备以下特征："
                )
                lines.append("- **逻辑自洽**：核心诡计经得起推敲，无明显硬伤")
                lines.append("- **节奏把控**：前3章快速建立悬念，中段持续加码，结尾有力收束")
                lines.append("- **情感共鸣**：在解谜之外提供人性深度的思考空间")
                lines.append("- **信息差设计**：读者与角色之间的信息不对称制造阅读快感")

        lines.append("")
        lines.append("## 四、内容创作建议")

        yt = results.get("year_trend", {})
        trend_dir = yt.get("trend_direction", "未知") if yt else "未知"

        if trend_dir == "上升":
            lines.append("- ✅ 该品类处于**上升通道**，新进入者仍有较大机会窗口")
        elif trend_dir == "下降":
            lines.append("- ⚠️ 该品类出版数量呈**下降趋势**，需寻找差异化切入点")
        else:
            lines.append("- ➡️ 该品类进入**成熟稳定期**，精品化路线是关键")

        # 根据四象限找蓝海
        hidden_gems = qa.get("examples", {}).get("高口碑低热度", []) if qa else []
        if hidden_gems:
            gems_titles = [g["title"] for g in hidden_gems[:2]]
            lines.append(
                f"- 💡 参考《{'》、《'.join(gems_titles)}》等「高口碑低热度」作品的方向，"
                f"竞争相对较小但品质已被验证"
            )

        lines.append("")
        lines.append("## 五、风险提醒")
        lines.append("- ❌ 纯模仿热门IP的同质化作品越来越难获得关注")
        lines.append("- ❌ 过于依赖单一反转的作品复购率低")
        lines.append("- ❌ 忽视人物塑造只重诡计设计的作品口碑天花板明显")

        lines.append("")
        lines.append("## 六、下一阶段重点推荐")
        lines.append("1. 🥇 **社会派悬疑** — 结合现实议题，差异化空间大")
        lines.append("2. 🥈 **短篇系列/单元剧式** — 适配碎片化阅读习惯")
        lines.append("3. 🥉 **跨媒介IP潜力** — 适合影视改编的故事结构")
        lines.append("4. **女性视角悬疑** — 快速增长的细分赛道")
        lines.append("5. **本土化原创** — 减少对外国作品的路径依赖")

        insight_text = "\n".join(lines)
        return {
            "source": "rule_engine",
            "insight": insight_text,
            "note": "未配置 DeepSeek API Key，使用内置规则引擎生成",
        }

    # ==================== 知识库文件管理 ====================

    @staticmethod
    def _create_default_knowledge_base(path: str):
        """创建默认的知识库文件（如果不存在）"""
        default_content = """\
悬疑推理小说爆款方法论与写作技巧知识库
==========================================

一、高口碑悬疑书的共同特征
-----------------------------
1. 核心诡计必须具备"既在意料之外，又在情理之中"的品质。最好的反转不是读者完全猜不到，
   而是读者在回头看时发现所有线索都在那里，只是当时没有注意到。

2. 开篇前三章必须建立强烈的阅读钩子（Hook）。常见手法：
   - 以一场看似不可能的犯罪开场
   - 让主角立刻陷入道德困境
   - 抛出一个与主角个人历史相关的悬而未决之谜

3. 信息差（Information Gap）是驱动读者翻页的核心动力。优秀的设计包括：
   - 读者知道但角色不知道的信息
   - 角色知道但读者不知道的信息
   - 双方都不知道但暗示存在的第三层信息

4. 节奏控制公式：每章结束时至少保留一个未解答的小问题。
   大约每50页安排一个中等规模的转折点（midpoint twist）。

二、当前市场趋势观察
-----------------------
1. 社会派推理崛起：相比传统的本格推理（注重诡计精巧），当代读者更倾向于
   有社会议题深度的作品。代表作如《长夜难明》《沉默的真相》等国产作品的成功
   证明了这一点。

2. 女性视角悬疑成为增长最快的细分赛道之一。女性作者+女性主角的组合
   在近三年的市场中表现突出。

3. 短篇/中篇形式复兴：受播客、有声书等新媒体形态影响，
   单元剧式的悬疑故事比传统长篇小说更容易传播。

4. 跨媒介IP价值：影视改编权价格最高的悬疑作品通常具备以下特征：
   - 强视觉画面感（场景描写生动）
   - 情节密度高（适合剪辑成紧凑剧集）
   - 人物关系网清晰（便于观众记忆）

三、写作实操技巧
-----------------
1. 红鲱鱼（Red Herring）的使用原则：
   - 每条误导线索必须在后期有合理解释
   - 最佳比例是3条误导线索对应1条真实线索
   - 误导线索不能让读者感到被愚弄，只能让他们感到自己判断失误

2. 可疑人物设计：
   - 每个主要角色都应该有动机和能力实施犯罪
   - 最不像凶手的人往往是最好的真凶人选
   - 但要避免过度使用"最不起眼的人是真凶"这个套路

3. 时间线管理的实用方法：
   - 用Excel或专门软件维护完整的时间线表
   - 每个事件标注：时间、地点、参与人员、公开信息、隐藏信息
   - 写作过程中反复核对时间线的逻辑一致性

4. 对话中的信息投放技巧：
   - 通过角色对话自然透露背景信息，而非叙述者说明
   - 每段对话至少承担两个功能：推进情节+揭示性格
   - 审讯/质问场景是最有效的信息密集型对话类型

四、常见失败模式及规避
-------------------------
1. "机械降神"式结局：避免引入之前完全没有铺垫的外部力量解决问题。
   所有解决问题的关键元素必须在全书前80%中出现或暗示过。

2. 角色工具化：每个角色都应该是完整的"人"，而不是推动情节的工具。
   即使是配角也需要有自己的欲望、恐惧和成长弧线。

3. 悬念疲劳：连续的高强度悬念会让读者麻木。
   在高强度段落之后需要安排"呼吸空间"——角色互动、幽默缓解、日常描写。

4. 解释段落过长：最后的揭秘章节不应超过全书的10%-15%。
   如果需要超过20页来解释一切，说明前期铺垫不够均匀。

五、出版与运营建议
---------------------
1. 书名的重要性：好的悬疑书名应包含以下至少一个元素：
   - 暗示谜题的存在（《消失的她》《嫌疑人X的献身》）
   - 制造紧迫感（《72小时》《倒数第二天》）
   - 引发好奇（《谁杀了她》）

2. 封面设计趋势：当前畅销悬疑书的封面倾向：
   - 高对比度配色（黑红、黑白、深蓝+亮色）
   - 极简符号化图形（钥匙、门、剪影、时钟）
   - 大字号书名+一句有力的宣传语

3. 读者社群运营：悬疑推理类读者的社群活跃度高于文学类平均水平。
   - 组织"猜凶手"活动可以大幅提升参与感
   - 提供隐藏章节/番外作为粉丝福利
   - 作者在社交媒体上分享幕后创作过程（如诡计设计草图）效果很好
"""

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_content)
        logger.info(f"📝 已创建默认知识库: {path}")


# ==================== 快捷入口 ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    engine = InsightEngine()
    engine.build_knowledge_base()
    print(f"知识库加载完成: {len(engine.knowledge_chunks)} 个文本块")
