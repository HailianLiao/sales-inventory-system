# -*- coding: utf-8 -*-
import sqlite3
conn = sqlite3.connect("database/sales.db")

print("=== 1. 查找 KYSH-1806 相关编码 ===")
rows = conn.execute(
    "SELECT DISTINCT 物料编码, 物料名称 FROM sales_history "
    "WHERE 物料编码 LIKE '%KYSH-1806%' LIMIT 10"
).fetchall()
for r in rows:
    print(f"  编码=[{r[0]}]  名称=[{r[1]}]")

if not rows:
    print("  无匹配，尝试更宽泛搜索...")
    rows = conn.execute(
        "SELECT DISTINCT 物料编码, 物料名称 FROM sales_history "
        "WHERE 物料编码 LIKE '%KYSH%' OR 物料名称 LIKE '%KYSH%' LIMIT 10"
    ).fetchall()
    for r in rows:
        print(f"  编码=[{r[0]}]  名称=[{r[1]}]")

print()
print("=== 2. 查找 1806E 相关编码 ===")
rows = conn.execute(
    "SELECT DISTINCT 物料编码, 物料名称 FROM sales_history "
    "WHERE 物料编码 LIKE '%1806E%' LIMIT 10"
).fetchall()
for r in rows:
    print(f"  编码=[{r[0]}]  名称=[{r[1]}]")

print()
print("=== 3. 精确查 KYSH-1806E 各年月分部门销量 ===")
rows = conn.execute(
    "SELECT 年, 月, 销售部门, SUM(销售数量) as 销量 "
    "FROM sales_history WHERE 物料编码 = 'KYSH-1806E' "
    "GROUP BY 年, 月, 销售部门 ORDER BY 年 DESC, 月 DESC"
).fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]}年{r[1]}月 | {r[2]} | {r[3]}")
else:
    print("  无数据")

print()
print("=== 4. 精确查 KYSH-1806E 各年月总销量 ===")
rows = conn.execute(
    "SELECT 年, 月, SUM(销售数量) as 销量 "
    "FROM sales_history WHERE 物料编码 = 'KYSH-1806E' "
    "GROUP BY 年, 月 ORDER BY 年 DESC, 月 DESC"
).fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]}年{r[1]}月 | {r[2]}")
else:
    print("  无数据")

conn.close()
