"""
市场数据分析模块
=================
用 pandas 对采集到的书籍数据进行多维度统计分析，生成可视化图表。

分析维度：
1. 评分分布（直方图 + 分段统计）
2. 题材词频 / 标签热度
3. 出版年份趋势
4. 出版社集中度（长尾分布）
5. 评分 vs 热度散点图（四象限分析）
6. 作者产出与口碑矩阵
"""

import os
import re
import logging
from typing import List, Dict, Optional

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")  # 无GUI后端，服务器环境必须
# 设置中文字体
plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import ANALYZE_CONFIG, TABLE_NAME

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """悬疑推理书籍市场数据分析器"""

    def __init__(self):
        self.output_dir = ANALYZE_CONFIG["output_dir"]
        os.makedirs(self.output_dir, exist_ok=True)
        self.df: Optional[pd.DataFrame] = None
        self._report_lines: List[str] = []

    # ==================== 主入口 ====================

    def run_full_analysis(self, books_data: List[Dict]) -> Dict:
        """
        执行完整分析流水线

        Args:
            books_data: 书籍字典列表（来自存储模块或直接传入）

        Returns:
            包含所有分析结果的汇总字典
        """
        if not books_data:
            logger.warning("⚠️ 没有数据可分析")
            return {}

        # 转为 DataFrame
        self.df = pd.DataFrame(books_data)

        # 统一数值列类型：消除 MySQL DECIMAL(Decimal) 与 float 混列导致的运算冲突
        # 关键：数据库中 rating 是 DECIMAL 类型，读回是 decimal.Decimal；JSON 来源是 float，必须统一。
        for col in ("rating", "rating_count", "publish_year"):
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

        logger.info(f"📊 开始分析 {len(self.df)} 条数据（数值列已统一为 float）")

        results = {}

        # 1. 基础统计
        results["basic_stats"] = self._basic_stats()

        # 2. 评分分布
        results["rating_distribution"] = self._rating_distribution()
        self._plot_rating_histogram()

        # 3. 标签/题材热度
        results["tag_analysis"] = self._tag_analysis()
        self._plot_tag_bar(top_n=20)

        # 4. 年份趋势
        results["year_trend"] = self._year_trend()
        self._plot_year_trend()

        # 5. 出版社集中度
        results["publisher_concentration"] = self._publisher_analysis()
        self._plot_publisher_pareto(top_n=15)

        # 6. 四象限分析（评分 × 热度）
        results["quadrant"] = self._quadrant_analysis()
        self._plot_quadrant_scatter()

        # 7. 生成文字报告
        report_path = self._generate_text_report(results)
        results["report_path"] = report_path

        logger.info(f"✅ 分析完成！报告和图表已保存到: {self.output_dir}")
        return results

    # ==================== 各维度分析方法 ====================

    def _basic_stats(self) -> Dict:
        """基础描述性统计"""
        df = self.df
        rated = df[df["rating"].notna()]
        stats = {
            "total_books": len(df),
            "rated_books": len(rated),
            "avg_rating": round(rated["rating"].mean(), 2) if len(rated) > 0 else None,
            "median_rating": round(rated["rating"].median(), 2) if len(rated) > 0 else None,
            "max_rating": float(rated["rating"].max()) if len(rated) > 0 else None,
            "min_rating": float(rated["rating"].min()) if len(rated) > 0 else None,
            "std_rating": round(rated["rating"].std(), 2) if len(rated) > 0 else None,
            "total_ratings": int(df["rating_count"].sum()),
            "avg_ratings_per_book": round(df["rating_count"].mean(), 1),
            "unique_authors": df["author"].nunique(),
            "unique_publishers": df["publisher"].nunique(),
        }
        # 年份范围
        years = df[df["publish_year"].notna()]["publish_year"]
        if len(years) > 0:
            stats["year_range"] = f"{int(years.min())} - {int(years.max())}"
            stats["median_year"] = int(years.median())
        return stats

    def _rating_distribution(self) -> Dict:
        """评分分段统计"""
        df = self.df
        rated = df[df["rating"].notna()]
        bins = ANALYZE_CONFIG["rating_bins"]
        labels = ANALYZE_CONFIG["rating_labels"]
        rated = rated.copy()
        rated["rating_bin"] = pd.cut(rated["rating"], bins=bins, labels=labels, right=False)
        dist = rated["rating_bin"].value_counts().sort_index().to_dict()
        return {"distribution": {str(k): v for k, v in dist.items()},
                "total_rated": len(rated)}

    def _tag_analysis(self) -> Dict:
        """标签/题材词频分析"""
        all_tags: List[str] = []
        for tags_str in self.df["tags"].dropna():
            tags_list = [t.strip() for t in str(tags_str).split(",") if t.strip()]
            all_tags.extend(tags_list)

        from collections import Counter
        tag_counter = Counter(all_tags)
        top_tags = tag_counter.most_common(30)
        return {"top_tags": [{"tag": t, "count": c} for t, c in top_tags],
                "unique_tags": len(tag_counter)}

    def _year_trend(self) -> Dict:
        """出版年份趋势"""
        df = self.df
        years_df = df[df["publish_year"].notna()].copy()
        if len(years_df) == 0:
            return {}
        yearly = years_df.groupby("publish_year").agg(
            book_count=("title", "count"),
            avg_rating=("rating", "mean"),
            total_ratings=("rating_count", "sum"),
        ).reset_index()
        yearly = yearly.sort_values("publish_year")
        # 只返回近20年的详细数据和总体趋势
        recent = yearly[yearly["publish_year"] >= (yearly["publish_year"].max() - 19)]
        return {
            "yearly_data": recent.to_dict(orient="records"),
            "peak_year": int(yearly.loc[yearly["book_count"].idxmax(), "publish_year"]),
            "trend_direction": "上升" if len(yearly) >= 3 and yearly.iloc[-1]["book_count"] > yearly.iloc[-3]["book_count"]
                              else ("下降" if len(yearly) >= 3 and yearly.iloc[-1]["book_count"] < yearly.iloc[-3]["book_count"] else "平稳"),
        }

    def _publisher_analysis(self) -> Dict:
        """出版社集中度分析（帕累托）"""
        pub_stats = self.df.groupby("publisher").agg(
            book_count=("title", "count"),
            avg_rating=("rating", "mean"),
        ).sort_values("book_count", ascending=False).reset_index()
        total = pub_stats["book_count"].sum()
        pub_stats["cumulative_pct"] = (pub_stats["book_count"].cumsum() / total * 100).round(1)
        top_publishers = pub_stats.head(15).to_dict(orient="records")
        # 计算CR5（前5家占比）
        cr5 = pub_stats.head(5)["book_count"].sum() / total * 100
        return {
            "top_publishers": top_publishers,
            "cr5": round(cr5, 1),
            "total_publishers": len(pub_stats),
        }

    def _quadrant_analysis(self) -> Dict:
        """评分×热度四象限分析"""
        df = self.df[self.df["rating"].notna() & (self.df["rating_count"] > 0)].copy()
        if len(df) == 0:
            return {}

        rating_median = df["rating"].median()
        count_median = df["rating_count"].median()

        def get_quadrant(row):
            r, c = row["rating"], row["rating_count"]
            if r >= rating_median and c >= count_median:
                return "叫好又叫座"
            elif r >= rating_median and c < count_median:
                return "高口碑低热度"
            elif r < rating_median and c >= count_median:
                return "高热度低口碑"
            else:
                return "冷门低分"

        df["quadrant"] = df.apply(get_quadrant, axis=1)
        quad_summary = df.groupby("quadrant").agg(
            count=("title", "count"),
            avg_rating=("rating", "mean"),
            example_titles=("title", lambda x: "、".join(x.head(3))),
        ).to_dict("index")

        # 每个象限的top3书
        quadrant_examples = {}
        for q in ["叫好又叫座", "高口碑低热度", "高热度低口碑", "冷门低分"]:
            subset = df[df["quadrant"] == q].nlargest(3, "rating")
            quadrant_examples[q] = [
                {"title": row["title"], "rating": row["rating"],
                 "rating_count": row["rating_count"]}
                for _, row in subset.iterrows()
            ]

        return {
            "thresholds": {"rating_median": round(float(rating_median), 2),
                           "count_median": int(count_median)},
            "summary": quad_summary,
            "examples": quadrant_examples,
        }

    # ==================== 可视化方法 ====================

    def _plot_rating_histogram(self):
        """评分分布直方图"""
        fig, ax = plt.subplots(figsize=(10, 6))
        rated = self.df[self.df["rating"].notna()]["rating"]
        if len(rated) == 0:
            plt.close(fig)
            return
        ax.hist(rated, bins=20, edgecolor="white", color="#4A90D9", alpha=0.85)
        ax.set_title("悬疑推理书籍评分分布", fontsize=16, fontweight="bold")
        ax.set_xlabel("豆瓣评分", fontsize=12)
        ax.set_ylabel("书籍数量", fontsize=12)
        ax.axvline(rated.mean(), color="red", linestyle="--", linewidth=1.5,
                   label=f"均值: {rated.mean():.2f}")
        ax.legend(fontsize=11)
        plt.tight_layout()
        path = os.path.join(self.output_dir, "01_rating_distribution.png")
        fig.savefig(path, dpi=ANALYZE_CONFIG["chart_dpi"])
        plt.close(fig)

    def _plot_tag_bar(self, top_n: int = 20):
        """题材标签TOP-N柱状图"""
        from collections import Counter
        all_tags = []
        for ts in self.df["tags"].dropna():
            all_tags.extend([t.strip() for t in str(ts).split(",") if t.strip()])
        top = Counter(all_tags).most_common(top_n)
        if not top:
            return

        tags, counts = zip(*top)
        fig, ax = plt.subplots(figsize=(12, max(6, len(tags) * 0.35)))
        colors = plt.cm.Blues([(i + 3) / (len(tags) + 3) for i in range(len(tags))])
        bars = ax.barh(range(len(tags)), counts, color=colors, edgecolor="white")
        ax.set_yticks(range(len(tags)))
        ax.set_yticklabels(tags, fontsize=10)
        ax.invert_yaxis()
        ax.set_xlabel("出现次数", fontsize=12)
        ax.set_title(f"悬疑推理书籍 TOP-{top_n} 热门题材标签", fontsize=14, fontweight="bold")
        # 添加数值标注
        for bar, count in zip(bars, counts):
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                    str(count), va="center", fontsize=9)
        plt.tight_layout()
        path = os.path.join(self.output_dir, "02_tag_popularity.png")
        fig.savefig(path, dpi=ANALYZE_CONFIG["chart_dpi"])
        plt.close(fig)

    def _plot_year_trend(self):
        """出版年份趋势折线图+柱状图组合"""
        years_df = self.df[self.df["publish_year"].notna()]
        if len(years_df) == 0:
            return
        yearly = years_df.groupby("publish_year").size().sort_index()
        # 只画近25年
        recent = yearly[yearly.index >= (yearly.index.max() - 24)]

        fig, ax1 = plt.subplots(figsize=(14, 6))
        ax2 = ax1.twinx()
        bars = ax1.bar(recent.index, recent.values, color="#6BAED6", alpha=0.7,
                       label="出版数量")
        # 叠加平均评分线
        yearly_rating = years_df.groupby("publish_year")["rating"].mean()
        yr_recent = yearly_rating[yearly_rating.index >= (yearly_rating.index.max() - 24)]
        ax2.plot(yr_recent.index, yr_recent.values, "o-", color="#E6550D",
                 linewidth=2, markersize=5, label="平均评分")

        ax1.set_xlabel("年份", fontsize=12)
        ax1.set_ylabel("出版数量（本）", fontsize=12, color="#6BAED6")
        ax2.set_ylabel("平均评分", fontsize=12, color="#E6550D")
        ax1.set_title("悬疑推理书籍出版趋势（近25年）", fontsize=14, fontweight="bold")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        plt.tight_layout()
        path = os.path.join(self.output_dir, "03_year_trend.png")
        fig.savefig(path, dpi=ANALYZE_CONFIG["chart_dpi"])
        plt.close(fig)

    def _plot_publisher_pareto(self, top_n: int = 15):
        """出版社帕累托图（柱状图+累计曲线）"""
        pub_counts = self.df["publisher"].value_counts().head(top_n)
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax2 = ax1.twinx()
        x = range(len(pub_counts))
        bars = ax1.bar(x, pub_counts.values, color="#756BB1", alpha=0.8)
        ax1.set_xticks(x)
        ax1.set_xticklabels(pub_counts.index, rotation=35, ha="right", fontsize=9)
        cumulative = pub_counts.values.cumsum() / pub_counts.values.sum() * 100
        ax2.plot(x, cumulative, "o-", color="#E6550D", linewidth=2, markersize=5)
        ax2.axhline(80, color="gray", linestyle="--", alpha=0.5, label="80%线")
        ax1.set_ylabel("出书数量", fontsize=12)
        ax2.set_ylabel("累计占比 (%)", fontsize=12)
        ax1.set_xlabel("出版社", fontsize=12)
        ax1.set_title(f"出版社集中度 TOP-{top_n}", fontsize=14, fontweight="bold")
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax2.legend(lines1 + lines2, labels1 + labels2, loc="center right")
        plt.tight_layout()
        path = os.path.join(self.output_dir, "04_publisher_concentration.png")
        fig.savefig(path, dpi=ANALYZE_CONFIG["chart_dpi"])
        plt.close(fig)

    def _plot_quadrant_scatter(self):
        """评分×评价人数四象限散点图"""
        df = self.df[(self.df["rating"].notna()) & (self.df["rating_count"] > 0)]
        if len(df) < 3:
            return

        r_med = df["rating"].median()
        c_med = df["rating_count"].median()

        fig, ax = plt.subplots(figsize=(12, 9))

        colors_map = {
            "叫好又叫座": "#31A354",
            "高口碑低热度": "#74C476",
            "高热度低口碑": "#F16913",
            "冷门低分": "#D94801",
        }
        markers_map = {
            "叫好又叫座": "o",
            "高口碑低热度": "s",
            "高热度低口碑": "^",
            "冷门低分": "x",
        }

        def get_q(row):
            if row["rating"] >= r_med and row["rating_count"] >= c_med:
                return "叫好又叫座"
            elif row["rating"] >= r_med and row["rating_count"] < c_med:
                return "高口碑低热度"
            elif row["rating"] < r_med and row["rating_count"] >= c_med:
                return "高热度低口碑"
            return "冷门低分"

        df = df.copy()
        df["_q"] = df.apply(get_q, axis=1)

        for q, group in df.groupby("_q"):
            ax.scatter(group["rating_count"], group["rating"],
                       c=colors_map.get(q, "gray"),
                       marker=markers_map.get(q, "o"),
                       s=60, alpha=0.7, label=f"{q} ({len(group)})",
                       edgecolors="white", linewidths=0.5)

        ax.axvline(c_med, color="gray", linestyle="--", alpha=0.5)
        ax.axhline(r_med, color="gray", linestyle="--", alpha=0.5)
        ax.set_xscale("log")  # 评价人数通常差异很大，用对数坐标
        ax.set_xlabel("评价人数（对数刻度）", fontsize=12)
        ax.set_ylabel("豆瓣评分", fontsize=12)
        ax.set_title("悬疑推理书籍：评分 × 热度 四象限分析", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10, loc="lower right")
        ax.grid(True, alpha=0.2)
        plt.tight_layout()
        path = os.path.join(self.output_dir, "05_quadrant_analysis.png")
        fig.savefig(path, dpi=ANALYZE_CONFIG["chart_dpi"])
        plt.close(fig)

    # ==================== 文字报告 ====================

    def _generate_text_report(self, results: Dict) -> str:
        """将所有分析结果写成结构化文本报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("  悬疑推理书籍市场数据分析报告")
        lines.append("=" * 60)
        lines.append("")

        # 基础统计
        bs = results.get("basic_stats", {})
        lines.append("【一、基础概览】")
        lines.append(f"  • 数据总量：{bs.get('total_books', 0)} 本")
        lines.append(f"  • 有评分数：{bs.get('rated_books', 0)} 本")
        lines.append(f"  • 平均评分：{bs.get('avg_rating', 'N/A')}")
        lines.append(f"  • 中位评分：{bs.get('median_rating', 'N/A')}")
        lines.append(f"  • 评分范围：{bs.get('min_rating', '?')} ~ {bs.get('max_rating', '?')}")
        lines.append(f"  • 总评价数：{bs.get('total_ratings', 0):,}")
        lines.append(f"  • 涉及作者：{bs.get('unique_authors', 0)} 位")
        lines.append(f"  • 涉及出版社：{bs.get('unique_publishers', 0)} 家")
        if bs.get("year_range"):
            lines.append(f"  • 出版年份跨度：{bs['year_range']}")
        lines.append("")

        # 评分分布
        rd = results.get("rating_distribution", {})
        lines.append("【二、评分分布】")
        if rd.get("distribution"):
            for band, count in rd["distribution"].items():
                pct = count / rd["total_rated"] * 100
                lines.append(f"  • {band} 分：{count} 本 ({pct:.1f}%)")
        lines.append("")

        # TOP标签
        ta = results.get("tag_analysis", {})
        lines.append("【三、热门题材标签 TOP-10】")
        for item in (ta.get("top_tags") or [])[:10]:
            lines.append(f"  • {item['tag']}：{item['count']} 次")
        lines.append("")

        # 年份趋势
        yt = results.get("year_trend", {})
        lines.append("【四、出版趋势】")
        if yt:
            lines.append(f"  • 整体方向：{yt.get('trend_direction', '未知')}")
            lines.append(f"  • 出版高峰年：{yt.get('peak_year', '?')} 年")
        lines.append("")

        # 出版社
        pa = results.get("publisher_concentration", {})
        lines.append("【五、出版社集中度】")
        lines.append(f"  • CR5（前5家占比）：{pa.get('cr5', '?')}%")
        lines.append("  • TOP-5出版社：")
        for p in (pa.get("top_publishers") or [])[:5]:
            avg = p.get("avg_rating")
            avg_txt = f"{avg:.1f}" if avg is not None else "N/A"
            lines.append(
                f"      {p['publisher']} — {p['book_count']}本 "
                f"(均分:{avg_txt})"
            )
        lines.append("")

        # 四象限
        qa = results.get("quadrant", {})
        lines.append("【六、四象限分析（评分×热度）】")
        if qa.get("thresholds"):
            t = qa["thresholds"]
            lines.append(f"  • 评分中位数：{t['rating_median']}")
            lines.append(f"  • 热度中位数：{t.get('count_median', '?')} 人评价")
        if qa.get("examples"):
            lines.append("  • 各象限代表作品：")
            for q, examples in qa["examples"].items():
                titles = ", ".join([ex["title"] for ex in examples[:2]])
                lines.append(f"      [{q}] {titles}")
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"  图表输出目录：{self.output_dir}")
        lines.append("=" * 60)

        report_text = "\n".join(lines)
        report_path = os.path.join(self.output_dir, "analysis_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        logger.info(f"📝 文字报告已保存: {report_path}")
        return report_path


# ==================== 快捷入口 ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    analyzer = MarketAnalyzer()
    print("分析模块就绪，请通过 main.py 或传入数据调用 run_full_analysis()")
