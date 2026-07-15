# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect("database/sales.db")

SKU = "KYSH-1806E"

print("=== 1. KYSH-1806E 近3个月分部门明细 (2026年2/3/4月) ===")
rows = conn.execute("""
    SELECT 年, 月, 销售部门, SUM(销售数量) as 销量
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026 AND 月 IN (2,3,4)
    GROUP BY 年, 月, 销售部门
    ORDER BY 月, 销量 DESC
""", (SKU,)).fetchall()
for r in rows:
    print(f"  {r[0]}年{r[1]}月 | 部门=[{r[2]}] | {r[3]}")

print()
print("=== 2. 注意部门名称变化 ===")
rows = conn.execute("""
    SELECT DISTINCT 销售部门, 年
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026 AND 月 IN (2,3,4)
    ORDER BY 销售部门
""", (SKU,)).fetchall()
for r in rows:
    print(f"  部门=[{r[1]}] -> [{r[0]}]")

print()
print("=== 3. 各月份总销量 ===")
rows = conn.execute("""
    SELECT 年, 月, SUM(销售数量) as 总销量
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026
    GROUP BY 年, 月 ORDER BY 月
""", (SKU,)).fetchall()
for r in rows:
    print(f"  {r[0]}年{r[1]}月 -> 总销量={r[2]}")

print()
print("=== 4. 模拟 monthly_avg_sales 的分组结果 ===")
rows = conn.execute("""
    SELECT 物料编码, 物料名称, 销售部门,
           SUM(销售数量) as 总销量,
           COUNT(DISTINCT 年 || '-' || 月) as 月数,
           ROUND(SUM(销售数量) * 1.0 / COUNT(DISTINCT 年 || '-' || 月), 2) as 月均销量
    FROM sales_history
    WHERE 物料编码 = ? AND 年 > 0 AND 月 > 0
      AND (年 = 2026 AND 月 = 4 OR 年 = 2026 AND 月 = 3 OR 年 = 2026 AND 月 = 2)
    GROUP BY 物料编码, 物料名称, 销售部门
    ORDER BY 月均销量 DESC
""", (SKU,)).fetchall()
total_avg = 0
for r in rows:
    print(f"  部门=[{r[2]}] | 总销量={r[3]} | 月数={r[4]} | 月均={r[5]}")
    total_avg += r[5]
print(f"  --> sum(月均) = {total_avg}  <-- 系统显示的就是这个值")

print()
print("=== 5. 正确的月均 = 近3个月总销量 / 3 ===")
row = conn.execute("""
    SELECT SUM(销售数量) as 总销量
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026 AND 月 IN (2,3,4)
""", (SKU,)).fetchone()
total = row[0] if row[0] else 0
print(f"  近3个月总销量 = {total}")
print(f"  正确月均 = {total} / 3 = {round(total/3, 2)}")

print()
print("=== 6. 检查是否有重复数据 (2026年1月) ===")
rows = conn.execute("""
    SELECT 日期, 单据编号, 客户, 销售部门, 销售数量, 数据来源
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026 AND 月 = 1
    ORDER BY 销售数量 DESC
    LIMIT 20
""", (SKU,)).fetchall()
print(f"  2026年1月共 {len(rows)} 条明细 (前20条):")
for r in rows:
    print(f"    日期={r[0]} | 单据={r[1]} | 客户={r[2]} | 部门={r[3]} | 数量={r[4]} | 来源={r[5]}")

print()
print("=== 7. 检查数据来源 ===")
rows = conn.execute("""
    SELECT 数据来源, COUNT(*) as 记录数, SUM(销售数量) as 销量
    FROM sales_history
    WHERE 物料编码 = ? AND 年 = 2026
    GROUP BY 数据来源
""", (SKU,)).fetchall()
for r in rows:
    print(f"  来源=[{r[0]}] | 记录数={r[1]} | 销量={r[2]}")

conn.close()
