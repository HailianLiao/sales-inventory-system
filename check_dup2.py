# -*- coding: utf-8 -*-
import sqlite3, json
conn = sqlite3.connect("database/sales.db")

# 按年统计完全重复的行（单据编号+日期+物料编码+销售数量+客户+销售部门 都相同）
result = {}
for year in [2022, 2023, 2024, 2025, 2026]:
    rows = conn.execute("""
        SELECT 单据编号, 日期, 物料编码, 销售数量, 客户, 销售部门, COUNT(*) as cnt
        FROM sales_history
        WHERE 年 = ?
        GROUP BY 单据编号, 日期, 物料编码, 销售数量, 客户, 销售部门
        HAVING cnt > 1
    """, (year,)).fetchall()
    result[str(year)] = {
        "重复组数": len(rows),
        "重复行数": sum(r[6] for r in rows)
    }

# 查看2026年KYSH-1806E 1月是否有整行重复
rows = conn.execute("""
    SELECT 单据编号, 日期, 物料编码, 销售数量, 客户, 销售部门, COUNT(*) as cnt
    FROM sales_history
    WHERE 物料编码 = 'KYSH-1806E' AND 年 = 2026 AND 月 = 1
    GROUP BY 单据编号, 日期, 物料编码, 销售数量, 客户, 销售部门
    ORDER BY cnt DESC, 销售数量 DESC
    LIMIT 10
""").fetchall()
result["KYSH-1806E_2026_01_top_duplicates"] = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6]] for r in rows]

print(json.dumps(result, ensure_ascii=False, indent=2))
conn.close()
