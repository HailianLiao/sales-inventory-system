"""销售库存管理系统 - Flask 版"""
import os, sys, io, json, datetime, threading
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, SALES_FILES, COLUMN_MAPPING, STANDARD_COLUMNS
from database.db_init import init_database, get_connection, refresh_precomputed_stats
from data_import.importer import import_without_prompt, batch_replace_field, load_excel_file
from analysis.queries import (
    get_data_overview, get_year_distribution, get_monthly_summary,
    get_unique_values,
    monthly_avg_sales, year_over_year, monthly_trend,
    top_sku, top_department, forecast_deviation,
    purchase_order_analysis, query_to_df, visual_query
)

app = Flask(__name__)
app.secret_key = "sales-inventory-2026"

# 全局导入任务状态
import_status = {
    "running": False,
    "phase": "",
    "year": 0,
    "year_imported": 0,
    "year_total": 0,
    "total_imported": 0,
    "message": "",
    "done": False,
    "results": [],
    "total": 0,
    "error": ""
}

def _import_progress(phase, year, year_imported, year_total, total_imported, message):
    """导入进度回调，更新全局状态"""
    import_status["phase"] = phase
    import_status["year"] = year
    import_status["year_imported"] = year_imported
    import_status["year_total"] = year_total
    import_status["total_imported"] = total_imported
    import_status["message"] = message

def _run_import(clear_existing):
    """后台线程执行导入"""
    global import_status
    try:
        print("[导入线程] 开始执行导入...", flush=True)
        import_status["running"] = True
        import_status["done"] = False
        import_status["error"] = ""
        import_status["message"] = "导入已启动..."
        total, results = import_without_prompt(clear_existing=clear_existing, progress_callback=_import_progress)
        print(f"[导入线程] 数据导入完成, 共 {total} 行", flush=True)
        # 刷新统计
        import_status["message"] = "正在刷新统计缓存..."
        import_status["phase"] = "stats"
        refresh_precomputed_stats()
        import_status["total"] = total
        import_status["results"] = results
        import_status["done"] = True
        import_status["running"] = False
        print("[导入线程] 全部完成!", flush=True)
    except Exception as e:
        import traceback
        print(f"[导入线程] 出错: {e}", flush=True)
        traceback.print_exc()
        import_status["error"] = str(e)
        import_status["done"] = True
        import_status["running"] = False

# 确保数据库已初始化
init_database()


def get_unique_list(field):
    """获取字段唯一值列表"""
    return get_unique_values(field)


# =================== 页面路由 ===================

@app.route("/")
def index():
    """数据概览"""
    stats = get_data_overview()
    year_dist_df = get_year_distribution()
    monthly_df = get_monthly_summary()
    year_dist = year_dist_df.to_dict("records") if not year_dist_df.empty else []
    monthly = monthly_df.to_dict("records") if not monthly_df.empty else []
    return render_template("overview.html", stats=stats, year_dist=year_dist, monthly=monthly)


@app.route("/import", methods=["GET", "POST"])
def import_page():
    """数据导入"""
    if request.method == "POST":
        action = request.form.get("action")
        if action in ("full_import", "append_import"):
            if import_status["running"]:
                return jsonify({"success": False, "error": "已有导入任务在运行中"})
            clear = (action == "full_import")
            thread = threading.Thread(target=_run_import, args=(clear,), daemon=True)
            thread.start()
            print(f"[POST /import] 后台线程已启动, thread alive: {thread.is_alive()}", flush=True)
            return jsonify({"success": True, "message": "导入已启动"})
        elif action == "upload":
            import pandas as pd
            target_table = request.form.get("target_table", "sales_history")
            file = request.files.get("file")
            if not file:
                return jsonify({"success": False, "error": "未选择文件"})
            try:
                df = pd.read_excel(file)
                # 过滤物料编码为空的行
                if "物料编码" in df.columns:
                    before = len(df)
                    df = df.dropna(subset=["物料编码"])
                # 库存/未交订单表补充日期
                if target_table in ("daily_inventory", "daily_pending_orders") and "日期" not in df.columns:
                    df.insert(0, "日期", datetime.date.today().isoformat())
                conn = get_connection()
                df.to_sql(target_table, conn, if_exists="append", index=False)
                conn.close()
                return jsonify({"success": True, "rows": len(df)})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

    # GET: 显示导入页面
    stats = get_data_overview()
    file_status = []
    for year, path in sorted(SALES_FILES.items()):
        file_status.append({
            "year": year,
            "file": os.path.basename(path),
            "exists": os.path.exists(path)
        })
    table_map = {
        "历史销售数据": "sales_history",
        "每日库存": "daily_inventory",
        "每日未交订单": "daily_pending_orders",
        "每日销售汇总": "daily_sales",
        "月度预测": "monthly_forecast",
    }
    return render_template("import.html", stats=stats, file_status=file_status, table_map=table_map)


@app.route("/sales-analysis")
def sales_analysis():
    """销量分析"""
    return render_template("sales_analysis.html")


@app.route("/yoy-analysis")
def yoy_analysis():
    """同比分析"""
    return render_template("yoy_analysis.html")


@app.route("/rankings")
def rankings():
    """排行榜"""
    return render_template("rankings.html")


@app.route("/purchase-analysis")
def purchase_analysis():
    """采购订单分析"""
    return render_template("purchase_analysis.html")


@app.route("/forecast-deviation")
def forecast_deviation_page():
    """预测偏差"""
    return render_template("forecast_deviation.html")


@app.route("/field-replace")
def field_replace():
    """字段批量替换"""
    table_map = {
        "历史销售数据": "sales_history",
        "每日库存": "daily_inventory",
        "每日未交订单": "daily_pending_orders",
        "每日销售汇总": "daily_sales",
        "月度预测": "monthly_forecast",
    }
    # 获取替换历史
    try:
        log_df = query_to_df("SELECT * FROM field_replace_log ORDER BY 操作时间 DESC LIMIT 50")
        log_data = log_df.to_dict("records") if not log_df.empty else []
    except Exception:
        log_data = []
    return render_template("field_replace.html", table_map=table_map, log_data=log_data)


@app.route("/custom-query")
def custom_query():
    """自定义查询"""
    return render_template("custom_query.html")


# =================== API 接口 (AJAX) ===================

@app.route("/api/unique-values/<field>")
def api_unique_values(field):
    """获取字段唯一值 (支持下拉框搜索)"""
    search = request.args.get("q", "").strip()
    values = get_unique_list(field)
    if search:
        values = [v for v in values if search.lower() in str(v).lower()][:200]
    else:
        values = values[:500]
    return jsonify(values)


@app.route("/api/monthly-avg", methods=["POST"])
def api_monthly_avg():
    """月均销量查询"""
    data = request.json
    df = monthly_avg_sales(
        sku=data.get("sku") or None,
        department=data.get("department") or None,
        months=data.get("months", 3)
    )
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/monthly-trend", methods=["POST"])
def api_monthly_trend():
    """月度趋势查询"""
    data = request.json
    df = monthly_trend(
        sku=data.get("sku") or None,
        department=data.get("department") or None
    )
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/yoy", methods=["POST"])
def api_yoy():
    """同比分析"""
    data = request.json
    df = year_over_year(
        data.get("year1", 2024), data.get("year2", 2025),
        month=data.get("month") or None
    )
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/top-sku", methods=["POST"])
def api_top_sku():
    """SKU排行"""
    data = request.json
    df = top_sku(
        year=data.get("year") or None,
        month=data.get("month") or None,
        department=data.get("department") or None,
        top_n=data.get("top_n", 20),
        metric=data.get("metric", "销量")
    )
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/top-dept", methods=["POST"])
def api_top_dept():
    """部门排行"""
    data = request.json
    df = top_department(
        year=data.get("year") or None,
        month=data.get("month") or None
    )
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/purchase-analysis", methods=["POST"])
def api_purchase():
    """采购订单分析"""
    data = request.json
    result = purchase_order_analysis(data["sku"], data.get("quantity", 0))
    # 获取趋势
    trend = monthly_trend(sku=data["sku"])
    result["trend"] = trend.to_dict("records") if not trend.empty else []
    return jsonify(result)


@app.route("/api/forecast-deviation", methods=["POST"])
def api_forecast():
    """预测偏差"""
    data = request.json
    df = forecast_deviation(data["month"])
    return jsonify(df.to_dict("records") if not df.empty else [])


@app.route("/api/field-replace", methods=["POST"])
def api_field_replace():
    """字段批量替换 (支持按年份筛选)"""
    data = request.json
    try:
        conn = get_connection()
        table = data["table"]
        field = data["field"]
        old_val = data["old_value"]
        new_val = data["new_value"]
        filter_year = data.get("filter_year")
        where = f"{field} = ?"
        params = [old_val]
        if filter_year:
            where += " AND 年 = ?"
            params.append(int(filter_year))
        preview = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()[0]
        if data.get("confirm"):
            update_sql = f"UPDATE {table} SET {field} = ? WHERE {where}"
            update_params = [new_val] + params
            cursor = conn.execute(update_sql, update_params)
            affected = cursor.rowcount
            conn.execute(
                "INSERT INTO field_replace_log (表名, 字段名, 原值, 新值, 影响行数) VALUES (?, ?, ?, ?, ?)",
                (table, field, old_val, new_val, affected)
            )
            conn.commit()
            conn.close()
            return jsonify({"success": True, "affected": affected})
        conn.close()
        return jsonify({"preview": preview})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/custom-query", methods=["POST"])
def api_custom_query():
    """自定义查询"""
    data = request.json
    df = visual_query(
        query_type=data.get("query_type", "销售明细"),
        year_start=data.get("year_start") or None,
        year_end=data.get("year_end") or None,
        months=data.get("months") or None,
        sku=data.get("sku") or None,
        department=data.get("department") or None,
        customer=data.get("customer") or None,
        category=data.get("category") or None,
        customer_category=data.get("customer_category") or None,
        sort_field=data.get("sort_field", "总销量"),
        sort_order=data.get("sort_order", "DESC"),
        limit=data.get("limit", 500)
    )
    return jsonify(df.to_dict("records") if not df.empty else [])




@app.route("/api/delete-by-year", methods=["POST"])
def api_delete_by_year():
    """按年份删除销售数据"""
    data = request.json
    year = data.get("year")
    if not year:
        return jsonify({"success": False, "error": "请选择年份"})
    try:
        year = int(year)
        conn = get_connection()
        # 先查影响行数
        count = conn.execute("SELECT COUNT(*) FROM sales_history WHERE 年 = ?", (year,)).fetchone()[0]
        if data.get("confirm"):
            conn.execute("DELETE FROM sales_history WHERE 年 = ?", (year,))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "deleted": count, "year": year})
        conn.close()
        return jsonify({"success": True, "preview": count, "year": year})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/year-distribution")
def api_year_distribution():
    """获取各年份数据量"""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT 年, COUNT(*) as cnt FROM sales_history GROUP BY 年 ORDER BY 年"
        ).fetchall()
        conn.close()
        return jsonify([{"year": r[0], "count": r[1]} for r in rows])
    except Exception as e:
        return jsonify([])

@app.route("/api/import-progress")
def api_import_progress():
    """查询导入进度"""
    return jsonify({
        "running": import_status["running"],
        "phase": import_status["phase"],
        "year": import_status["year"],
        "year_imported": import_status["year_imported"],
        "year_total": import_status["year_total"],
        "total_imported": import_status["total_imported"],
        "message": import_status["message"],
        "done": import_status["done"],
        "total": import_status["total"],
        "results": import_status["results"],
        "error": import_status["error"]
    })

@app.route("/api/download")
def api_download():
    """下载查询结果为CSV"""
    query_type = request.args.get("type", "query")
    # 从查询参数重建查询
    data = json.loads(request.args.get("params", "{}"))
    if query_type == "custom":
        df = visual_query(
            query_type=data.get("query_type", "销售明细"),
            year_start=data.get("year_start") or None,
            year_end=data.get("year_end") or None,
            months=data.get("months") or None,
            sku=data.get("sku") or None,
            department=data.get("department") or None,
            customer=data.get("customer") or None,
            category=data.get("category") or None,
            customer_category=data.get("customer_category") or None,
            sort_field=data.get("sort_field", "总销量"),
            sort_order=data.get("sort_order", "DESC"),
            limit=data.get("limit", 5000)
        )
    else:
        return "不支持的下载类型", 400

    csv_data = df.to_csv(index=False).encode("utf-8-sig")
    return send_file(
        io.BytesIO(csv_data),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"{query_type}_result.csv"
    )


if __name__ == "__main__":
    print("=" * 50)
    print("  销售库存管理系统 (Flask版)")
    print("  访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
