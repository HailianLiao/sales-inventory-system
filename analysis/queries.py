# -*- coding: utf-8 -*-
"""分析查询模块 - 提供各种销售分析查询"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.db_init import get_connection


def query_to_df(sql, params=None):
    """执行 SQL 查询并返回 DataFrame"""
    conn = get_connection()
    df = pd.read_sql_query(sql, conn, params=params or [])
    conn.close()
    return df


# ============= 基础统计 =============

def _get_stat(conn, key):
    """从预计算表读取统计值"""
    row = conn.execute("SELECT value FROM precomputed_stats WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def get_data_overview():
    """获取数据库概览 (从预计算表秒读)"""
    conn = get_connection()
    total = _get_stat(conn, "total_records")
    if total is not None:
        stats = {
            "总记录数": int(total),
            "年份范围": (int(_get_stat(conn, "min_year") or 0), int(_get_stat(conn, "max_year") or 0)),
            "SKU数量": int(_get_stat(conn, "sku_count") or 0),
            "客户数量": int(_get_stat(conn, "customer_count") or 0),
            "部门数量": int(_get_stat(conn, "dept_count") or 0),
            "总销售收入": float(_get_stat(conn, "total_revenue") or 0),
            "总价税合计": float(_get_stat(conn, "total_tax_inclusive") or 0),
        }
    else:
        row = conn.execute("SELECT COUNT(*), MIN(年), MAX(年) FROM sales_history WHERE 年 > 0").fetchone()
        stats = {
            "总记录数": row[0],
            "年份范围": (row[1], row[2]),
            "SKU数量": 0,
            "客户数量": 0,
            "部门数量": 0,
            "总销售收入": 0,
            "总价税合计": 0,
        }
    conn.close()
    return stats


def get_year_distribution():
    """获取年度数据分布 (从 yearly_summary 预聚合表秒读，SKU/客户已年度去重)"""
    return query_to_df("""
        SELECT 年 as 年份,
               总销量,
               销售收入_折扣后 as "销售收入(折扣后)",
               价税合计_折扣后 as "价税合计(折扣后)",
               SKU数,
               客户数
        FROM yearly_summary
        ORDER BY 年
    """)


def get_monthly_summary():
    """获取月度汇总 (从预聚合表秒读)"""
    return query_to_df("""
        SELECT 年和月, 年, 月, 记录数, 总销量, 销售收入_折扣后, 价税合计_折扣后, SKU数, 客户数
        FROM monthly_summary
        ORDER BY 年, 月
    """)


def get_unique_values(field):
    """获取某字段的所有唯一值 (从缓存表秒读)"""
    conn = get_connection()
    # 优先从缓存表读取
    rows = conn.execute(
        "SELECT field_value FROM cached_unique_values WHERE field_name = ? ORDER BY field_value",
        (field,)
    ).fetchall()
    conn.close()
    if rows:
        return [r[0] for r in rows]
    # fallback: 缓存表为空则直接查 (慢)
    return query_to_df(
        f"SELECT DISTINCT {field} FROM sales_history WHERE {field} IS NOT NULL ORDER BY {field}"
    )[field].tolist()


# ============= 月均销量分析 =============

def monthly_avg_sales(sku=None, department=None, months=3, end_year=None, end_month=None):
    """
    计算近 N 个月的月均销量
    可按 SKU 和/或部门筛选
    """
    conditions = ["年 > 0", "月 > 0"]
    params = []

    if sku:
        conditions.append("物料编码 = ?")
        params.append(sku)
    if department:
        conditions.append("销售部门 = ?")
        params.append(department)

    where = " AND ".join(conditions)

    # 先取最近 N 个月的年月组合
    period_sql = f"""
    SELECT DISTINCT 年, 月 FROM sales_history
    WHERE {where}
    ORDER BY 年 DESC, 月 DESC
    LIMIT ?
    """
    periods = query_to_df(period_sql, params + [months])

    if periods.empty:
        return pd.DataFrame()

    # 用这些年月做筛选
    period_conditions = " OR ".join(
        [f"(年 = {r['年']} AND 月 = {r['月']})" for _, r in periods.iterrows()]
    )

    sql = f"""
    SELECT 物料编码, 物料名称, 销售部门,
           SUM(销售数量) as 总销量,
           COUNT(DISTINCT 年 || '-' || 月) as 月数,
           ROUND(SUM(销售数量) * 1.0 / COUNT(DISTINCT 年 || '-' || 月), 2) as 月均销量
    FROM sales_history
    WHERE {where} AND ({period_conditions})
    GROUP BY 物料编码, 物料名称, 销售部门
    ORDER BY 月均销量 DESC
    """
    return query_to_df(sql, params)


# ============= 同比分析 =============

def year_over_year(year1, year2, month=None, sku=None, department=None):
    """
    两年同期对比
    """
    conditions = []
    params = []

    if month:
        conditions.append("月 = ?")
        params.append(month)
    if sku:
        conditions.append("物料编码 = ?")
        params.append(sku)
    if department:
        conditions.append("销售部门 = ?")
        params.append(department)

    extra_where = ""
    if conditions:
        extra_where = " AND " + " AND ".join(conditions)

    sql = f"""
    SELECT
        COALESCE(a.物料编码, b.物料编码) as 物料编码,
        COALESCE(a.物料名称, b.物料名称) as 物料名称,
        COALESCE(a.销售部门, b.销售部门) as 销售部门,
        a.销量 as '{year1}年销量',
        b.销量 as '{year2}年销量',
        CASE
            WHEN a.销量 IS NULL OR a.销量 = 0 THEN NULL
            ELSE ROUND((b.销量 - a.销量) * 100.0 / a.销量, 2)
        END as '同比增长率%'
    FROM
        (SELECT 物料编码, 物料名称, 销售部门, SUM(销售数量) as 销量
         FROM sales_history WHERE 年 = ? {extra_where}
         GROUP BY 物料编码, 物料名称, 销售部门) a
    FULL OUTER JOIN
        (SELECT 物料编码, 物料名称, 销售部门, SUM(销售数量) as 销量
         FROM sales_history WHERE 年 = ? {extra_where}
         GROUP BY 物料编码, 物料名称, 销售部门) b
    ON a.物料编码 = b.物料编码 AND a.销售部门 = b.销售部门
    ORDER BY b.销量 DESC NULLS LAST
    """
    return query_to_df(sql, [year1] + params + [year2] + params)


# ============= 月度趋势 =============

def monthly_trend(sku=None, department=None, start_year=None, end_year=None):
    """
    月度销量趋势 (用于图表绘制)
    """
    # 无过滤条件时，直接从汇总表读取 (秒出)
    if not sku and not department and not start_year and not end_year:
        return query_to_df("""
            SELECT 年, 月, 年和月 as 年月,
                   总销量 as 销量, 销售收入_折扣后 as 销售额, SKU数
            FROM monthly_summary
            WHERE 年 > 0 AND 月 > 0
            ORDER BY 年, 月
        """)

    conditions = ["年 > 0", "月 > 0"]
    params = []

    if sku:
        conditions.append("物料编码 = ?")
        params.append(sku)
    if department:
        conditions.append("销售部门 = ?")
        params.append(department)
    if start_year:
        conditions.append("年 >= ?")
        params.append(start_year)
    if end_year:
        conditions.append("年 <= ?")
        params.append(end_year)

    where = " AND ".join(conditions)

    sql = f"""
    SELECT 年, 月,
           年 || '-' || printf('%02d', 月) as 年月,
           SUM(销售数量) as 销量,
           SUM(销售收入_折扣后) as 销售额,
           COUNT(DISTINCT 物料编码) as SKU数
    FROM sales_history
    WHERE {where}
    GROUP BY 年, 月
    ORDER BY 年, 月
    """
    return query_to_df(sql, params)


# ============= 排行榜 =============

def top_sku(year=None, month=None, department=None, top_n=20, metric="销量"):
    """
    SKU 排行 (按销量或销售额)
    """
    conditions = ["年 > 0"]
    params = []

    if year:
        conditions.append("年 = ?")
        params.append(year)
    if month:
        conditions.append("月 = ?")
        params.append(month)
    if department:
        conditions.append("销售部门 = ?")
        params.append(department)

    where = " AND ".join(conditions)
    order_col = "销量" if metric == "销量" else "销售额"

    sql = f"""
    SELECT 物料编码, 物料名称,
           SUM(销售数量) as 销量,
           ROUND(SUM(销售收入_折扣后), 2) as 销售额
    FROM sales_history
    WHERE {where}
    GROUP BY 物料编码, 物料名称
    ORDER BY {order_col} DESC
    LIMIT ?
    """
    return query_to_df(sql, params + [top_n])


def top_department(year=None, month=None, top_n=20):
    """部门/渠道销量排行"""
    conditions = ["年 > 0"]
    params = []

    if year:
        conditions.append("年 = ?")
        params.append(year)
    if month:
        conditions.append("月 = ?")
        params.append(month)

    where = " AND ".join(conditions)

    sql = f"""
    SELECT 销售部门,
           SUM(销售数量) as 销量,
           ROUND(SUM(销售收入_折扣后), 2) as 销售额,
           COUNT(DISTINCT 物料编码) as SKU数,
           COUNT(DISTINCT 客户) as 客户数
    FROM sales_history
    WHERE {where} AND 销售部门 IS NOT NULL
    GROUP BY 销售部门
    ORDER BY 销量 DESC
    LIMIT ?
    """
    return query_to_df(sql, params + [top_n])


# ============= 预测偏差分析 =============

def forecast_deviation(forecast_month):
    """
    预测偏差分析: 对比月度预测 vs 实际销量，标记 >30% 偏差
    """
    sql = """
    SELECT
        f.物料编码, f.物料名称, f.销售部门,
        f.预测数量,
        COALESCE(s.实际销量, 0) as 实际销量,
        CASE
            WHEN f.预测数量 = 0 THEN NULL
            ELSE ROUND(ABS(COALESCE(s.实际销量, 0) - f.预测数量) * 100.0 / f.预测数量, 2)
        END as '偏差率%',
        CASE
            WHEN f.预测数量 = 0 THEN '无预测'
            WHEN ABS(COALESCE(s.实际销量, 0) - f.预测数量) * 100.0 / f.预测数量 > 30 THEN '异常'
            ELSE '正常'
        END as 状态
    FROM monthly_forecast f
    LEFT JOIN (
        SELECT 物料编码, 销售部门, SUM(销售数量) as 实际销量
        FROM sales_history
        WHERE 年 || '-' || printf('%02d', 月) = ?
        GROUP BY 物料编码, 销售部门
    ) s ON f.物料编码 = s.物料编码 AND f.销售部门 = s.销售部门
    WHERE f.预测月份 = ?
    ORDER BY '偏差率%' DESC
    """
    return query_to_df(sql, [forecast_month, forecast_month])


# ============= 采购订单分析 =============

def purchase_order_analysis(sku, quantity):
    """
    采购订单分析: 对某 SKU 的拟采购数量进行多维度分析
    返回: 近3月均销量, 近6月均销量, 当前库存, 未交订单, 拟采购数量, 预估可售月数
    """
    conn = get_connection()
    result = {}

    def _sku_avg_months(months):
        """按 SKU 直接汇总近 N 个月总销量除以实际月数，不按部门拆分"""
        periods = conn.execute(
            "SELECT DISTINCT 年, 月 FROM sales_history "
            "WHERE 年 > 0 AND 月 > 0 AND 物料编码 = ? "
            "ORDER BY 年 DESC, 月 DESC LIMIT ?",
            (sku, months)
        ).fetchall()
        if not periods:
            return 0
        period_conditions = " OR ".join(
            [f"(年 = {p[0]} AND 月 = {p[1]})" for p in periods]
        )
        row = conn.execute(
            f"SELECT SUM(销售数量) FROM sales_history "
            f"WHERE 物料编码 = ? AND ({period_conditions})",
            (sku,)
        ).fetchone()
        total = row[0] if row and row[0] else 0
        return round(total / len(periods), 2)

    # 近 3 / 6 月均销量（不分部门）
    result["近3月月均销量"] = _sku_avg_months(3)
    result["近6月月均销量"] = _sku_avg_months(6)

    # 当前库存（取最新日期的一条记录）
    inv = conn.execute(
        "SELECT 库存数量 FROM daily_inventory "
        "WHERE 物料编码 = ? ORDER BY 日期 DESC LIMIT 1",
        (sku,)
    ).fetchone()
    result["当前库存"] = inv[0] if inv and inv[0] else 0

    # 未交订单（取最新日期的一条记录）
    pending = conn.execute(
        "SELECT 未交数量 FROM daily_pending_orders "
        "WHERE 物料编码 = ? ORDER BY 日期 DESC LIMIT 1",
        (sku,)
    ).fetchone()
    result["未交订单"] = pending[0] if pending and pending[0] else 0

    # 拟采购数量
    result["拟采购数量"] = quantity

    # 预估可售月数 = (库存 + 未交 + 拟采购) / 月均销量
    avg_monthly = result["近3月月均销量"] or result["近6月月均销量"]
    if avg_monthly > 0:
        total_supply = result["当前库存"] + result["未交订单"] + quantity
        result["预估可售月数"] = round(total_supply / avg_monthly, 1)
    else:
        result["预估可售月数"] = "无销量数据"

    conn.close()
    return result


# ============= 可视化筛选查询 =============

def visual_query(query_type, year_start=None, year_end=None, months=None,
                 sku=None, department=None, customer=None, category=None,
                 customer_category=None,
                 sort_field=None, sort_order="DESC", limit=500):
    """
    可视化筛选器后端：根据用户选择动态构建安全的参数化 SQL
    query_type: 销售明细 / 按SKU汇总 / 按部门汇总 / 按客户汇总 / 按月汇总
    """
    conditions = ["年 > 0"]
    params = []

    if year_start:
        conditions.append("年 >= ?")
        params.append(year_start)
    if year_end:
        conditions.append("年 <= ?")
        params.append(year_end)
    if months:
        placeholders = ",".join(["?"] * len(months))
        conditions.append(f"月 IN ({placeholders})")
        params.extend(months)
    if sku:
        conditions.append("物料编码 = ?")
        params.append(sku)
    if department:
        conditions.append("销售部门 = ?")
        params.append(department)
    if customer:
        conditions.append("客户 = ?")
        params.append(customer)
    if category:
        conditions.append("产品类别 = ?")
        params.append(category)
    if customer_category:
        conditions.append("客户类别 = ?")
        params.append(customer_category)

    where = " AND ".join(conditions)

    # 白名单校验排序方向
    sort_dir = "DESC" if sort_order == "DESC" else "ASC"

    if query_type == "销售明细":
        # 白名单校验排序字段
        allowed_sort = {"日期", "销售数量", "销售收入_折扣后", "价税合计_折扣后", "物料编码", "客户", "销售部门"}
        safe_sort = sort_field if sort_field in allowed_sort else "日期"
        sql = f"""
        SELECT 年, 月, 日期, 物料编码, 物料名称, 客户, 销售部门, 销售员,
               销售数量, 销售收入_折扣后, 价税合计_折扣后, 产品类别, 客户类别
        FROM sales_history
        WHERE {where}
        ORDER BY {safe_sort} {sort_dir}
        LIMIT ?
        """
        params.append(limit)

    elif query_type == "按SKU汇总":
        allowed_sort = {"总销量", "销售收入", "价税合计", "物料编码"}
        safe_sort = sort_field if sort_field in allowed_sort else "总销量"
        sql = f"""
        SELECT 物料编码, 物料名称,
               SUM(销售数量) as 总销量,
               ROUND(SUM(销售收入_折扣后), 2) as 销售收入,
               ROUND(SUM(价税合计_折扣后), 2) as 价税合计
        FROM sales_history
        WHERE {where}
        GROUP BY 物料编码, 物料名称
        ORDER BY {safe_sort} {sort_dir}
        LIMIT ?
        """
        params.append(limit)

    elif query_type == "按部门汇总":
        allowed_sort = {"总销量", "销售收入", "价税合计", "销售部门", "SKU数", "客户数"}
        safe_sort = sort_field if sort_field in allowed_sort else "总销量"
        sql = f"""
        SELECT 销售部门,
               SUM(销售数量) as 总销量,
               ROUND(SUM(销售收入_折扣后), 2) as 销售收入,
               ROUND(SUM(价税合计_折扣后), 2) as 价税合计,
               COUNT(DISTINCT 物料编码) as SKU数,
               COUNT(DISTINCT 客户) as 客户数
        FROM sales_history
        WHERE {where} AND 销售部门 IS NOT NULL
        GROUP BY 销售部门
        ORDER BY {safe_sort} {sort_dir}
        LIMIT ?
        """
        params.append(limit)

    elif query_type == "按客户汇总":
        allowed_sort = {"总销量", "销售收入", "价税合计", "客户", "SKU数"}
        safe_sort = sort_field if sort_field in allowed_sort else "总销量"
        sql = f"""
        SELECT 客户, 客户类别,
               SUM(销售数量) as 总销量,
               ROUND(SUM(销售收入_折扣后), 2) as 销售收入,
               ROUND(SUM(价税合计_折扣后), 2) as 价税合计,
               COUNT(DISTINCT 物料编码) as SKU数
        FROM sales_history
        WHERE {where} AND 客户 IS NOT NULL
        GROUP BY 客户, 客户类别
        ORDER BY {safe_sort} {sort_dir}
        LIMIT ?
        """
        params.append(limit)

    elif query_type == "按月汇总":
        allowed_sort = {"总销量", "销售收入", "价税合计", "年", "月", "SKU数", "客户数"}
        safe_sort = sort_field if sort_field in allowed_sort else "年"
        # 按月汇总时默认升序
        if sort_field in (None, "年", "月"):
            sort_dir = "ASC"
        sql = f"""
        SELECT 年, 月, 年和月,
               SUM(销售数量) as 总销量,
               ROUND(SUM(销售收入_折扣后), 2) as 销售收入,
               ROUND(SUM(价税合计_折扣后), 2) as 价税合计,
               COUNT(DISTINCT 物料编码) as SKU数,
               COUNT(DISTINCT 客户) as 客户数
        FROM sales_history
        WHERE {where}
        GROUP BY 年, 月, 年和月
        ORDER BY {safe_sort} {sort_dir}
        LIMIT ?
        """
        params.append(limit)
    else:
        return pd.DataFrame()

    return query_to_df(sql, params)
