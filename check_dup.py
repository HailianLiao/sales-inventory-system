# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect("database/sales.db")

SKU = "KYSH-1806E"

print("=== 检查2026年各月重复情况 ===")
for month in range(1, 7):
    total = conn.execute(
        "SELECT SUM(销售数量) FROM sales_history WHERE 物料编码=? AND 年=2026 AND 月=?",
        (SKU, month)
    ).fetchone()[0] or 0
    rec_count = conn.execute(
        "SELECT COUNT(*) FROM sales_history WHERE 物料编码=? AND 年=2026 AND 月=?",
        (SKU, month)
    ).fetchone()[0]

    # 检查重复：按单据编号+日期+客户分组，看是否有完全相同的记录
    dup_check = conn.execute("""
        SELECT 日期, 单据编号, 客户, 销售数量, COUNT(*) as cnt
        FROM sales_history
        WHERE 物料编码=? AND 年=2026 AND 月=?
        GROUP BY 日期, 单据编号, 客户, 销售数量
        HAVING cnt > 1
        LIMIT 5
    """, (SKU, month)).fetchall()

    print(f"  {month}月: 总销量={total}, 记录数={rec_count}, 重复组数={len(dup_check)}")
    for d in dup_check:
        print(f"       重复: 日期={d[0]} 单据={d[1]} 客户={d[2]} 数量={d[3]} 出现{d[4]}次")

print()
print("=== 检查全库重复情况 (按 单据编号+日期+物料编码+销售数量) ===")
rows = conn.execute("""
    SELECT COUNT(*) as 总记录数,
           SUM(CASE WHEN cnt > 1 THEN 1 ELSE 0 END) as 重复记录数
    FROM (
        SELECT 单据编号, 日期, 物料编码, 销售数量, COUNT(*) as cnt
        FROM sales_history
        GROUP BY 单据编号, 日期, 物料编码, 销售数量
    )
""").fetchone()
print(f"  总记录数: {rows[0]}")
print(f"  有重复的组涉及的记录数: {rows[1]}")

print()
print("=== 全库各年份重复统计 ===")
rows = conn.execute("""
    SELECT 年,
           COUNT(*) as 总记录数,
           SUM(CASE WHEN cnt > 1 THEN cnt ELSE 0 END) as 重复行数
    FROM (
        SELECT 年, 单据编号, 日期, 物料编码, 销售数量, COUNT(*) as cnt
        FROM sales_history
        WHERE 年 > 0
        GROUP BY 年, 单据编号, 日期, 物料编码, 销售数量
    )
    GROUP BY 年 ORDER BY 年
""").fetchall()
for r in rows:
    print(f"  {r[0]}年: 总记录数={r[1]}, 重复行数={r[2]}")

conn.close()
