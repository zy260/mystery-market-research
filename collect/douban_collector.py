"""
豆瓣悬疑推理书籍数据采集器
==========================
从豆瓣读书标签页抓取书单 + 详情页，提取结构化数据。

功能：
- 按标签（悬疑/推理/侦探等）爬取书单列表页
- 逐本访问详情页，提取完整字段
- 随机延时防封，真实UA，支持断点续采
- 输出标准化的字典列表，供下游存储模块消费
"""

import random
import time
import re
import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 引入项目配置
import os
import sys
# 项目根目录自适应定位（兼容 Windows/Linux/手机任意路径）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DOUBAN_CONFIG

logger = logging.getLogger(__name__)


class DoubanCollector:
    """豆瓣书籍数据采集器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DOUBAN_CONFIG["headers"])
        self.collected_books: List[Dict] = []
        self._seen_ids: set = set()  # 去重用

    # ==================== 公开接口 ====================

    def collect_by_tags(self, tags: Optional[List[str]] = None) -> List[Dict]:
        """
        按标签采集书籍数据（主入口）

        Args:
            tags: 要采集的标签列表，默认使用配置中的全部标签

        Returns:
            书籍数据字典列表
        """
        tags = tags or DOUBAN_CONFIG["tags"]
        max_pages = DOUBAN_CONFIG["max_pages"]
        limit = DOUBAN_CONFIG.get("limit", 30)   # 本次试点采集数量上限

        for tag in tags:
            if len(self.collected_books) >= limit:
                break
            logger.info(f"📚 开始采集标签: [{tag}]")
            for page in range(max_pages):
                if len(self.collected_books) >= limit:
                    break
                start = page * DOUBAN_CONFIG["per_page"]
                book_list = self._fetch_tag_page(tag, start)
                if not book_list:
                    logger.info(f"   标签 [{tag}] 第{page+1}页无数据，停止翻页")
                    break
                for book_id in book_list:
                    if len(self.collected_books) >= limit:
                        break
                    if book_id in self._seen_ids:
                        continue
                    detail = self._fetch_book_detail(book_id, source_tag=tag)
                    if detail:
                        self.collected_books.append(detail)
                        self._seen_ids.add(book_id)
                        logger.info(f"   ✅ 已采集: {detail['title']} (评分:{detail.get('rating', 'N/A')})")

        logger.info(f"\n🎉 采集完成！共获取 {len(self.collected_books)} 本书的结构化数据")
        return self.collected_books

    # ==================== 内部方法：列表页 ====================

    def _fetch_tag_page(self, tag: str, start: int) -> List[str]:
        """
        抓取标签列表页，返回书籍ID列表

        Args:
            tag: 标签名
            start: 起始偏移量

        Returns:
            豆瓣书籍ID列表（如 ['1234567', '2345678']）
        """
        url = DOUBAN_CONFIG["tag_url_template"].format(tag=tag, start=start)

        try:
            resp = self.session.get(url, timeout=15)
            # 检查是否被反爬拦截
            if self._is_blocked(resp):
                logger.warning(f"⚠️ 列表页可能被拦截 (status={resp.status_code})")
                time.sleep(random.uniform(10, 20))
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            book_items = soup.select("li.subject-item")
            book_ids = []

            for item in book_items:
                link_tag = item.select_one("h2 > a") or item.select_one("a[href*='/subject/']")
                if link_tag and "href" in link_tag.attrs:
                    href = link_tag["href"]
                    # 从URL中提取book ID: /subject/1234567/
                    match = re.search(r"/subject/(\d+)/", href)
                    if match:
                        book_ids.append(match.group(1))

            # 随机延时防封
            delay = random.uniform(DOUBAN_CONFIG["min_delay"], DOUBAN_CONFIG["max_delay"])
            time.sleep(delay)

            return book_ids

        except requests.RequestException as e:
            logger.error(f"❌ 请求列表页失败: {url} | {e}")
            return []

    # ==================== 内部方法：详情页 ====================

    def _fetch_book_detail(self, book_id: str, source_tag: str = "") -> Optional[Dict]:
        """
        抓取单本书的详情页，提取所有目标字段

        Args:
            book_id: 豆瓣书籍ID

        Returns:
            字典格式的书籍数据，或None（解析失败时）
        """
        url = DOUBAN_CONFIG["book_detail_url"].format(book_id=book_id)

        try:
            resp = self.session.get(url, timeout=15)
            if self._is_blocked(resp):
                logger.warning(f"⚠️ 详情页可能被拦截: {url}")
                time.sleep(random.uniform(10, 20))
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            data = self._parse_detail_page(soup, book_id, source_tag=source_tag)

            # 随机延时
            delay = random.uniform(DOUBAN_CONFIG["min_delay"], DOUBAN_CONFIG["max_delay"])
            time.sleep(delay)

            return data

        except requests.RequestException as e:
            logger.error(f"❌ 请求详情页失败: {url} | {e}")
            return None

    def _parse_detail_page(self, soup: BeautifulSoup, book_id: str, source_tag: str = "") -> Dict:
        """解析详情页HTML，提取所有字段"""
        data = {"douban_id": book_id}

        # 1. 书名
        title_tag = soup.select_one("h1 span[property='v:itemreviewed']")
        data["title"] = title_tag.get_text(strip=True) if title_tag else "未知书名"

        # 2. 作者
        author_tag = soup.select_one("span.pl a[href*='/author/' ]")
        if author_tag:
            data["author"] = author_tag.get_text(strip=True)
        else:
            # 备选：从 pub 信息中提取
            pub_text = self._get_pub_text(soup)
            data["author"] = pub_text.split("/")[0].strip() if pub_text else "未知作者"

        # 3. 出版社
        pub_text = self._get_pub_text(soup)
        data["publisher"] = self._extract_publisher(pub_text) if pub_text else ""

        # 4. 出版年份
        data["publish_year"] = self._extract_year(pub_text) if pub_text else None

        # 5. 评分
        rating_tag = soup.select_one("strong.ll.rating_num")
        data["rating"] = float(rating_tag.get_text(strip=True)) if rating_tag else None

        # 6. 评价人数
        # 豆瓣当前结构：评分下方的 "(540993人评价)" 文本，不在 a.people-count 里
        rating_count = 0
        people_tag = soup.select_one("a.people-count span")
        if people_tag:
            text = people_tag.get_text(strip=True).replace("人评价", "")
            try:
                rating_count = int(text.replace(",", ""))
            except ValueError:
                rating_count = 0
        if rating_count == 0:
            # 备选：页面上形如 "540993人评价" 的文本节点
            for m in re.finditer(r"([\d,]+)\s*人评价", soup.get_text()):
                rating_count = int(m.group(1).replace(",", ""))
                break
        data["rating_count"] = rating_count

        # 7. 内容简介
        intro_divs = soup.select("div.related_info div.intro")
        if intro_divs:
            # 取最长的一个简介（通常是全书简介）
            longest_intro = max(intro_divs, key=lambda d: len(d.get_text()))
            data["intro"] = longest_intro.get_text("\n", strip=True)[:2000]  # 截断过长内容
        else:
            data["intro"] = ""

        # 8. 标签（题材分类）
        # 豆瓣新版书籍详情页已移除 div.tags-body 用户标签区，
        # 因此以"采集入口标签"作为可靠的题材标签来源，保证下游分析可用。
        tag_set = []
        if source_tag:
            tag_set.append(source_tag)
        tag_tags = soup.select("a.tag") or soup.select("div.tags-body a")
        for t in tag_tags:
            txt = t.get_text(strip=True)
            if txt and txt not in tag_set:
                tag_set.append(txt)
        data["tags"] = ",".join(tag_set)
        data["source_tag"] = source_tag

        # 9. 分类（来自URL或页面信息）
        data["category"] = "悬疑推理"

        return data

    # ==================== 工具方法 ====================

    @staticmethod
    def _get_pub_text(soup: BeautifulSoup) -> str:
        """提取出版信息文本块"""
        pub_tag = soup.select_one("div#info")
        return pub_tag.get_text("|", strip=True) if pub_tag else ""

    @staticmethod
    def _extract_publisher(pub_text: str) -> str:
        """从出版信息中提取出版社名"""
        # 格式通常为: 作者 / 译者 / 出版社 / 出版年 / 定价
        parts = [p.strip() for p in pub_text.split("|")]
        for part in parts:
            if any(kw in part for kw in ["出版社", "出版社有限公司", "出版公司", "人民文学",
                                           "新星", "南海", "译林", "上海文艺", "北京联合",
                                           "湖南文艺", "江苏凤凰", "中信", "浙江文艺"]):
                return part
        # 备选：取倒数第二段
        return parts[-2] if len(parts) >= 2 else ""

    @staticmethod
    def _extract_year(pub_text: str) -> Optional[int]:
        """从出版信息中提取年份"""
        match = re.search(r"(20|19)\d{2}", pub_text)
        return int(match.group()) if match else None

    @staticmethod
    def _is_blocked(resp: requests.Response) -> bool:
        """检测是否被反爬拦截"""
        if resp.status_code == 403 or resp.status_code == 418:
            return True
        # 豆瓣反爬常见特征
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type and len(resp.text) < 500:
            return True
        if "安全验证" in resp.text or "验证码" in resp.text:
            return True
        return False


# ==================== 快捷运行入口 ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    collector = DoubanCollector()
    books = collector.collect_by_tags()
    print(f"\n共采集到 {len(books)} 本书")
    if books:
        print(f"示例: {books[0]['title']}")
