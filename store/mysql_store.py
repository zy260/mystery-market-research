"""
MySQL 数据存储模块
===================
将采集到的书籍数据存入 MySQL 数据库，支持 UPSERT 去重。

功能：
- 自动建表（首次运行时）
- 批量插入/更新（UPSERT，基于 douban_id 去重）
- 支持从数据库读取数据供分析模块使用
- 连接池管理，异常处理
"""

import logging
from typing import List, Dict, Optional

import pymysql
from pymysql.cursors import DictCursor

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MYSQL_CONFIG, TABLE_NAME

logger = logging.getLogger(__name__)


class MySQLStore:
    """MySQL 数据存储管理器"""

    # 建表 SQL
    CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `douban_id` VARCHAR(20) NOT NULL COMMENT '豆瓣书籍ID',
        `title` VARCHAR(255) NOT NULL COMMENT '书名',
        `author` VARCHAR(255) DEFAULT '' COMMENT '作者',
        `publisher` VARCHAR(255) DEFAULT '' COMMENT '出版社',
        `publish_year` INT DEFAULT NULL COMMENT '出版年份',
        `rating` DECIMAL(3,1) DEFAULT NULL COMMENT '豆瓣评分',
        `rating_count` INT DEFAULT 0 COMMENT '评价人数',
        `intro` TEXT COMMENT '内容简介',
        `tags` VARCHAR(500) DEFAULT '' COMMENT '用户标签',
        `category` VARCHAR(50) DEFAULT '悬疑推理' COMMENT '分类',
        `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
        `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY `uk_douban_id` (`douban_id`),
        INDEX `idx_rating` (`rating`),
        INDEX `idx_publish_year` (`publish_year`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='悬疑推理书籍数据表';
    """

    def __init__(self):
        self.config = MYSQL_CONFIG
        self._connection = None

    def _ensure_database_exists(self):
        """确保数据库存在（不存在则自动创建）—— 免去手动建库的步骤"""
        db_name = self.config["database"]
        try:
            # 先不带 database 连接 MySQL 服务器
            server_conn = pymysql.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                charset=self.config["charset"],
                cursorclass=DictCursor,
            )
            with server_conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                server_conn.commit()
                logger.info(f"✅ 数据库 `{db_name}` 已就绪（不存在则已自动创建）")
            server_conn.close()
        except pymysql.Error as e:
            logger.error(f"❌ 自动建库失败: {e}")
            raise

    # ==================== 连接管理 ====================

    def get_connection(self):
        """获取数据库连接（懒加载）"""
        if self._connection is None or not self._connection.open:
            try:
                # 先确保数据库存在（自动建库）
                self._ensure_database_exists()
                self._connection = pymysql.connect(
                    host=self.config["host"],
                    port=self.config["port"],
                    user=self.config["user"],
                    password=self.config["password"],
                    database=self.config["database"],
                    charset=self.config["charset"],
                    cursorclass=DictCursor,
                )
                logger.info("✅ MySQL 连接成功")
            except pymysql.Error as e:
                logger.error(f"❌ MySQL 连接失败: {e}")
                raise
        return self._connection

    def close(self):
        """关闭连接"""
        if self._connection and self._connection.open:
            self._connection.close()
            logger.info("🔒 MySQL 连接已关闭")

    # ==================== 建表 ====================

    def ensure_table_exists(self):
        """确保数据表存在（不存在则自动创建）"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(self.CREATE_TABLE_SQL)
            conn.commit()
            logger.info(f"✅ 表 `{TABLE_NAME}` 已就绪")

    # ==================== 写入：UPSERT ====================

    def upsert_books(self, books: List[Dict]) -> int:
        """
        批量插入或更新书籍数据（UPSERT）

        Args:
            books: 书籍字典列表

        Returns:
            成功写入的条数
        """
        if not books:
            logger.warning("⚠️ 没有数据需要写入")
            return 0

        conn = self.get_connection()
        upsert_sql = f"""
        INSERT INTO `{TABLE_NAME}`
            (douban_id, title, author, publisher, publish_year,
             rating, rating_count, intro, tags, category)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            title       = VALUES(title),
            author      = VALUES(author),
            publisher   = VALUES(publisher),
            publish_year= VALUES(publish_year),
            rating      = VALUES(rating),
            rating_count= VALUES(rating_count),
            intro       = VALUES(intro),
            tags        = VALUES(tags),
            category    = VALUES(category),
            updated_at  = CURRENT_TIMESTAMP
        """

        count = 0
        with conn.cursor() as cursor:
            for book in books:
                row = (
                    book.get("douban_id"),
                    book.get("title", ""),
                    book.get("author", ""),
                    book.get("publisher", ""),
                    book.get("publish_year"),
                    book.get("rating"),
                    book.get("rating_count", 0),
                    book.get("intro", "")[:5000],  # 截断过长内容
                    book.get("tags", ""),
                    book.get("category", "悬疑推理"),
                )
                try:
                    cursor.execute(upsert_sql, row)
                    count += 1
                except pymysql.Error as e:
                    logger.warning(f"⚠️ 写入失败 [{book.get('title', '?')}]: {e}")

            conn.commit()

        logger.info(f"💾 UPSERT 完成: {count}/{len(books)} 条记录")
        return count

    # ==================== 读取 ====================

    def fetch_all_books(self) -> List[Dict]:
        """读取全部书籍数据（数值列统一转为 float，避免 Decimal/float 混用冲突）"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM `{TABLE_NAME}` ORDER BY rating DESC, rating_count DESC")
            rows = cursor.fetchall()

        # 统一数值类型：MySQL DECIMAL 读回是 decimal.Decimal，统一转成 float，避免下游分析 TypeError
        for row in rows:
            for col in ("rating", "rating_count", "publish_year"):
                if col in row and row[col] is not None:
                    try:
                        row[col] = float(row[col])
                    except (TypeError, ValueError):
                        pass
        return rows

    def fetch_summary_stats(self) -> Dict:
        """获取汇总统计信息"""
        conn = self.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    COUNT(*) AS total_books,
                    COUNT(rating) AS rated_books,
                    AVG(rating) AS avg_rating,
                    MAX(rating) AS max_rating,
                    MIN(rating) AS min_rating,
                    SUM(rating_count) AS total_ratings,
                    COUNT(DISTINCT publisher) AS publisher_count,
                    COUNT(DISTINCT author) AS author_count,
                    MIN(publish_year) AS earliest_year,
                    MAX(publish_year) AS latest_year
                FROM `{TABLE_NAME}`
            """)
            return cursor.fetchone()


# ==================== 快捷入口 ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    store = MySQLStore()
    store.ensure_table_exists()
    stats = store.fetch_summary_stats()
    print(f"当前库状态: {stats}")
    store.close()
