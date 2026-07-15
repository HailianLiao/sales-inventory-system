# -*- coding: utf-8 -*-
"""SQLite 数据库初始化模块"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH


def get_connection():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database():
    """初始化数据库，创建所有表"""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. 历史销售数据表 (核心主表)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        产品类别 TEXT,
        客户类别 TEXT,
        日期 TEXT,
        单据类型 TEXT,
        单据编号 TEXT,
        客户 TEXT,
        销售部门 TEXT,
        销售员 TEXT,
        物料编码 TEXT,
        物料名称 TEXT,
        销售数量 REAL,
        含税单价 REAL,
        税率 REAL,
        销售收入_折扣前 REAL,
        价税合计_折扣前 REAL,
        折扣率 REAL,
        折扣额 REAL,
        销售收入_折扣后 REAL,
        价税合计_折扣后 REAL,
        年 INTEGER,
        月 INTEGER,
        年和月 TEXT,
        数据来源 TEXT
    )
    """)

    # 2. 每日库存表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        日期 TEXT NOT NULL,
        物料编码 TEXT NOT NULL,
        物料名称 TEXT,
        库存数量 REAL DEFAULT 0,
        更新时间 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. 每日未交订单表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_pending_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        日期 TEXT NOT NULL,
        物料编码 TEXT NOT NULL,
        物料名称 TEXT,
        未交数量 REAL DEFAULT 0,
        预计交期 TEXT,
        更新时间 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 4. 每日销售表 (汇总当日)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        日期 TEXT NOT NULL,
        物料编码 TEXT NOT NULL,
        物料名称 TEXT,
        销售部门 TEXT,
        销售数量 REAL DEFAULT 0,
        销售金额 REAL DEFAULT 0,
        更新时间 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 5. 月度预测表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monthly_forecast (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        预测月份 TEXT NOT NULL,
        物料编码 TEXT NOT NULL,
        物料名称 TEXT,
        销售部门 TEXT,
        预测数量 REAL DEFAULT 0,
        录入时间 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        备注 TEXT
    )
    """)

    # 6. 字段替换记录表 (记录批量修改历史)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS field_replace_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        表名 TEXT NOT NULL,
        字段名 TEXT NOT NULL,
        原值 TEXT NOT NULL,
        新值 TEXT NOT NULL,
        影响行数 INTEGER,
        操作时间 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 7. 预计算汇总表 (解决大数据量查询慢的问题)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS precomputed_stats (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 8. 按年月汇总表 (预聚合月度数据)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monthly_summary (
        年 INTEGER,
        月 INTEGER,
        年和月 TEXT,
        记录数 INTEGER,
        总销量 REAL,
        销售收入_折扣后 REAL,
        价税合计_折扣后 REAL,
        SKU数 INTEGER,
        客户数 INTEGER,
        PRIMARY KEY (年, 月)
    )
    """)

    # 8b. 按年汇总表 (年度级别去重统计，解决 SUM(月SKU数) 重复计数 bug)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS yearly_summary (
        年 INTEGER PRIMARY KEY,
        记录数 INTEGER,
        总销量 REAL,
        销售收入_折扣后 REAL,
        价税合计_折扣后 REAL,
        SKU数 INTEGER,
        客户数 INTEGER
    )
    """)

    # 9. 字段唯一值缓存表 (加速下拉框加载)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cached_unique_values (
        field_name TEXT NOT NULL,
        field_value TEXT NOT NULL,
        PRIMARY KEY (field_name, field_value)
    )
    """)

    # 创建索引以加速查询
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_history(日期)",
        "CREATE INDEX IF NOT EXISTS idx_sales_year_month ON sales_history(年, 月)",
        "CREATE INDEX IF NOT EXISTS idx_sales_ym ON sales_history(年和月)",
        "CREATE INDEX IF NOT EXISTS idx_sales_sku ON sales_history(物料编码)",
        "CREATE INDEX IF NOT EXISTS idx_sales_dept ON sales_history(销售部门)",
        "CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales_history(客户)",
        "CREATE INDEX IF NOT EXISTS idx_sales_product ON sales_history(物料名称)",
        "CREATE INDEX IF NOT EXISTS idx_inv_date_sku ON daily_inventory(日期, 物料编码)",
        "CREATE INDEX IF NOT EXISTS idx_pending_date_sku ON daily_pending_orders(日期, 物料编码)",
        "CREATE INDEX IF NOT EXISTS idx_daily_sales_date ON daily_sales(日期, 物料编码)",
        "CREATE INDEX IF NOT EXISTS idx_forecast_month ON monthly_forecast(预测月份, 物料编码)",
    ]
    for idx_sql in indexes:
        cursor.execute(idx_sql)

    conn.commit()
    conn.close()
    print(f"数据库初始化完成: {DB_PATH}")


def refresh_precomputed_stats(progress_callback=None):
    """
    刷新预计算汇总数据 (导入数据后调用)
    progress_callback: callable(step, total_steps, description)
        每完成一个步骤调用一次，用于显示进度
    """
    conn = get_connection()
    cursor = conn.cursor()
    total_steps = 9  # 总步骤数
    step = 0

    def _report(desc):
        nonlocal step
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, desc)
        print(f"  [{step}/{total_steps}] {desc}")

    # 1. 全局统计 (合并为一条 SQL，减少全表扫描次数)
    _report("正在计算全局统计...")
    row = cursor.execute("""
        SELECT COUNT(*), MIN(年), MAX(年),
               (SELECT COUNT(DISTINCT 物料编码) FROM sales_history),
               (SELECT COUNT(DISTINCT 客户) FROM sales_history),
               (SELECT COUNT(DISTINCT 销售部门) FROM sales_history),
               (SELECT ROUND(SUM(销售收入_折扣后), 2) FROM sales_history WHERE 年 > 0),
               (SELECT ROUND(SUM(价税合计_折扣后), 2) FROM sales_history WHERE 年 > 0)
        FROM sales_history WHERE 年 > 0
    """).fetchone()
    total_records, min_year, max_year, sku_count, cust_count, dept_count, total_rev, total_tax = row
    for key, val in [("total_records", str(total_records)), ("min_year", str(min_year)),
                     ("max_year", str(max_year)), ("sku_count", str(sku_count)),
                     ("customer_count", str(cust_count)), ("dept_count", str(dept_count)),
                     ("total_revenue", str(total_rev or 0)), ("total_tax_inclusive", str(total_tax or 0))]:
        cursor.execute("INSERT OR REPLACE INTO precomputed_stats (key, value) VALUES (?, ?)", (key, val))

    # 2. 按年月汇总
    _report("正在刷新月度汇总...")
    cursor.execute("DELETE FROM monthly_summary")
    cursor.execute("""
    INSERT INTO monthly_summary (年, 月, 年和月, 记录数, 总销量, 销售收入_折扣后, 价税合计_折扣后, SKU数, 客户数)
    SELECT 年, 月, 年和月,
           COUNT(*),
           ROUND(SUM(销售数量), 0),
           ROUND(SUM(销售收入_折扣后), 2),
           ROUND(SUM(价税合计_折扣后), 2),
           COUNT(DISTINCT 物料编码),
           COUNT(DISTINCT 客户)
    FROM sales_history
    WHERE 年 > 0
    GROUP BY 年, 月, 年和月
    """)

    # 3. 按年汇总
    _report("正在刷新年度汇总...")
    cursor.execute("DELETE FROM yearly_summary")
    cursor.execute("""
    INSERT INTO yearly_summary (年, 记录数, 总销量, 销售收入_折扣后, 价税合计_折扣后, SKU数, 客户数)
    SELECT 年,
           COUNT(*),
           ROUND(SUM(销售数量), 0),
           ROUND(SUM(销售收入_折扣后), 2),
           ROUND(SUM(价税合计_折扣后), 2),
           COUNT(DISTINCT 物料编码),
           COUNT(DISTINCT 客户)
    FROM sales_history
    WHERE 年 > 0
    GROUP BY 年
    """)

    # 4. 缓存各字段唯一值 (下拉框用)
    cursor.execute("DELETE FROM cached_unique_values")
    fields = ["物料编码", "物料名称", "销售部门", "客户", "产品类别", "客户类别"]
    for field in fields:
        _report(f"正在缓存字段唯一值: {field}...")
        cursor.execute(f"""
        INSERT INTO cached_unique_values (field_name, field_value)
        SELECT ?, {field} FROM sales_history
        WHERE {field} IS NOT NULL
        GROUP BY {field}
        """, (field,))

    conn.commit()
    conn.close()
    _report("预计算汇总数据刷新完成")


if __name__ == "__main__":
    init_database()
