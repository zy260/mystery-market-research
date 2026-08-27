"""
悬疑推理书籍市场研究系统 - 全局配置
=====================================
统一管理所有模块的配置项，避免硬编码散落各处。
"""
import os

# ==================== 项目根目录（自适应定位） ====================
# 无论项目放在哪个目录/系统，都以 settings.py 所在位置为基准定位根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==================== 豆瓣采集配置 ====================
DOUBAN_CONFIG = {
    # 悬疑推理书单标签页（可替换为其他标签）
    "tag_url_template": "https://book.douban.com/tag/{tag}?start={start}&type=T",
    "tags": ["悬疑", "推理", "侦探", "犯罪", "惊悚"],
    # 每页20本书，最多抓取前几页（先小批量试点，可改大）
    "max_pages": 2,          # 先抓前2页（约40本标签书），跑通后再调大
    "per_page": 20,
    # 请求间隔（秒），随机抖动防封
    "min_delay": 3.0,
    "max_delay": 6.0,
    # 每轮采集的最大书籍数（限制批次，先试点跑通）
    "limit": 30,
    # 请求头
    "headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    },
    # 详情页URL模板
    "book_detail_url": "https://book.douban.com/subject/{book_id}/",
}

# ==================== MySQL 存储配置 ====================
# 你在下面直接填你的 MySQL 账密即可（保留环境变量优先）
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", 3306)),
    "user": os.getenv("MYSQL_USER", "root"),        # ← 如果环境变量没设，用下面这个默认
    "password": os.getenv("MYSQL_PASSWORD", ""),    # ← 填你的 MySQL 密码
    "database": os.getenv("MYSQL_DB", "mystery_books"),  # 会自动建库
    "charset": "utf8mb4",
}
# 表名
TABLE_NAME = "books"

# ==================== DeepSeek LLM 配置 ====================
# 填入你的 DeepSeek key（复用你项目现成的 key）；不填也能跑（用规则引擎）
LLM_CONFIG = {
    "api_key": os.getenv("DEEPSEEK_API_KEY", ""),   # ← 填你的 DeepSeek key
    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    "model": "deepseek-chat",
    # LLM洞察时的系统提示词
    "system_prompt": """你是一位资深的悬疑推理书籍市场分析师。你的任务是根据提供的数据分析结果，
用通俗易懂的中文写出市场洞察报告。

要求：
1. 用数据说话，每个结论都要引用具体数字
2. 分点陈述，逻辑清晰
3. 给出可操作的内容创作建议（题材选择、写作方向、排期优先级）
4. 语言风格：专业但不晦涩，像给内容团队做汇报""",
    # RAG 相关
    "rag_chunk_size": 500,          # 知识库分块大小（字符）
    "rag_overlap": 50,              # 分块重叠字符数
    "rag_top_k": 5,                 # 检索时取top-k条
}

# ==================== RAG 知识库配置 ====================
RAG_CONFIG = {
    # 内置知识库路径（爆款方法论、写作技巧）——用项目根目录定位
    "knowledge_base_path": os.path.join(PROJECT_ROOT, "data", "knowledge_base.txt"),
    # 向量存储路径
    "vector_store_path": os.path.join(PROJECT_ROOT, "data", "vector_store.pkl"),
}

# ==================== 分析输出配置 ====================
ANALYZE_CONFIG = {
    # 输出目录——用项目根目录定位
    "output_dir": os.path.join(PROJECT_ROOT, "output"),
    # 图表保存格式
    "chart_format": "png",
    "chart_dpi": 150,
    # 评分分段
    "rating_bins": [0, 6, 7, 7.5, 8, 8.5, 9, 10],
    "rating_labels": ["<6", "6-7", "7-7.5", "7.5-8", "8-8.5", "8.5-9", ">9"],
}

# ==================== 排期计划配置 ====================
PLAN_CONFIG = {
    # 计划周期（周）
    "planning_cycle_weeks": 4,
    # 优先级权重
    "weights": {
        "popularity": 0.35,   # 热度权重（评价人数）
        "rating": 0.30,       # 口碑权重（评分）
        "trend": 0.25,        # 趋势权重（近年出版占比）
        "gap": 0.10,          # 差异化权重（竞争少但评分高）
    },
}