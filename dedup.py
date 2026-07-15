# -*- coding: utf-8 -*-
"""
清理 sales_history 表中的重复记录（基于关键业务字段）。
策略：先建一张只存 keep_id 的临时表，再删除不在其中的记录，内存占用最小。
"""
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH
from database.db_init import refresh_precomputed_stats

start = time.time()
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT COUNT(*) FROM sales_history")
old_count = cursor.fetchone()[0]
print(f"清理前 sales_history 记录数: {old_count:,}")

key_columns = ["单据编号", "日期", "物料编码", "物料名称", "销售数量", "客户", "销售部门", "单据类型"]
cols_sql = ", ".join(key_columns)

print("正在找出重复组的最小 id...")
cursor.execute("PRAGMA temp_store = MEMORY")
cursor.execute("PRAGMA synchronous = OFF")

cursor.execute(f"""
    CREATE TABLE keep_ids AS
    SELECT MIN(id) as keep_id
    FROM sales_history
    GROUP BY {cols_sql}
""")

cursor.execute("CREATE INDEX idx_keep_ids ON keep_ids(keep_id)")

cursor.execute("SELECT COUNT(*) FROM keep_ids")
keep_count = cursor.fetchone()[0]
print(f"需要保留的唯一记录数: {keep_count:,}")
print(f"预计删除重复记录数: {old_count - keep_count:,}")

print("正在删除重复记录...")
cursor.execute("""
    DELETE FROM sales_history
    WHERE id NOT IN (SELECT keep_id FROM keep_ids)
""")

deleted = cursor.rowcount
print(f"实际删除记录数: {deleted:,}")

cursor.execute("DROP TABLE keep_ids")

# 释放空间
print("正在回收空间...")
cursor.execute("VACUUM")

# 刷新预计算统计
print("正在刷新预计算统计...")
refresh_precomputed_stats()

conn.commit()
conn.close()

elapsed = time.time() - start
print(f"去重完成，耗时 {elapsed:.1f} 秒")
