"""销售库存管理系统 - Streamlit 交互界面"""
import os
import sys
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH, SALES_FILES, COLUMN_MAPPING, STANDARD_COLUMNS
from database.db_init import init_database, get_connection, refresh_precomputed_stats
from data_import.importer import import_without_prompt, batch_replace_field
from analysis.queries import (
    get_data_overview, get_year_distribution, get_monthly_summary,
    get_unique_values,
    monthly_avg_sales, year_over_year, monthly_trend,
    top_sku, top_department, forecast_deviation,
    purchase_order_analysis, query_to_df, visual_query
)

st.set_page_config(page_title="销售库存管理系统", page_icon="📊", layout="wide")

# 隐藏 Streamlit 默认的 Deploy 按钮和页脚
st.markdown("""
<style>
    .stDeployButton {display: none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# Plotly 图表统一中文配置
PLOTLY_CONFIG = {"locale": "zh-CN"}

# 数据库表名中英文映射
TABLE_NAME_MAP = {
    "历史销售数据": "sales_history",
    "每日库存": "daily_inventory",
    "每日未交订单": "daily_pending_orders",
    "每日销售汇总": "daily_sales",
    "月度预测": "monthly_forecast",
}

st.set_page_config(page_title="销售库存管理系统", page_icon="📊", layout="wide")

# =================== 侧边栏导航 ===================
st.sidebar.title("销售库存管理系统")
page = st.sidebar.radio("功能导航", [
    "📊 数据概览",
    "📥 数据导入",
    "📈 销量分析",
    "🔄 同比分析",
    "🏆 排行榜",
    "🔮 采购订单分析",
    "📋 预测偏差",
    "🔧 字段批量替换",
    "🔍 自定义查询",
])


def ensure_db():
    """确保数据库已初始化"""
    if not os.path.exists(DB_PATH):
        init_database()


ensure_db()


# =================== 缓存函数 ===================
@st.cache_data(ttl=300)
def cached_overview():
    return get_data_overview()

@st.cache_data(ttl=300)
def cached_year_dist():
    return get_year_distribution()

@st.cache_data(ttl=300)
def cached_monthly_summary():
    return get_monthly_summary()

@st.cache_data(ttl=300)
def cached_unique_values(field):
    return get_unique_values(field)


# =================== 数据概览 ===================
if page == "📊 数据概览":
    st.title("数据概览")

    try:
        stats = cached_overview()

        # 第1行：数据年份、SKU数量、客户数量
        col1, col2, col3 = st.columns(3)
        year_range = stats.get("年份范围", (0, 0))
        col1.metric("数据年份", f"{year_range[0]}-{year_range[1]}" if year_range[0] else "无数据")
        col2.metric("SKU 数量", f"{stats['SKU数量']:,}")
        col3.metric("客户数量", f"{stats['客户数量']:,}")

        # 第2行：部门数量、总销售收入（折扣后）、总价税合计（折扣后）
        col4, col5, col6 = st.columns(3)
        col4.metric("部门数量", f"{stats['部门数量']:,}")
        col5.metric("总销售收入(折扣后)", f"{stats['总销售收入']:,.2f}")
        col6.metric("总价税合计(折扣后)", f"{stats['总价税合计']:,.2f}")

        if stats["总记录数"] > 0:
            st.subheader("各年度数据")
            year_dist = cached_year_dist()
            st.dataframe(year_dist, use_container_width=True)

            # 年度销量趋势图
            fig = px.bar(year_dist, x="年份", y="总销量", title="年度总销量趋势",
                         text="总销量")
            fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

            # 月度趋势 (从预聚合表读取，秒出)
            st.subheader("月度销量趋势")
            ms = cached_monthly_summary()
            if not ms.empty:
                fig2 = px.line(ms, x="年和月", y="总销量", title="全品月度销量趋势 (内部销售周期)")
                st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG)
        else:
            st.info("数据库为空，请先导入数据")
    except Exception as e:
        st.error(f"加载数据失败: {e}")
        st.info("请先导入销售数据")


# =================== 数据导入 ===================
elif page == "📥 数据导入":
    st.title("数据导入")

    st.subheader("历史销售数据导入")
    st.write("数据源目录: `F:\\原D盘文件-E\\每日库存、采购、入库表\\`")

    # 显示可用文件
    file_status = []
    for year, path in sorted(SALES_FILES.items()):
        exists = os.path.exists(path)
        file_status.append({
            "年份": year,
            "文件": os.path.basename(path),
            "状态": "✅ 存在" if exists else "❌ 不存在"
        })
    st.dataframe(pd.DataFrame(file_status), use_container_width=True)

    # 当前数据库状态
    stats = cached_overview()
    st.info(f"当前数据库已有 {stats['总记录数']:,} 条销售记录")

    # 导入方式说明
    st.markdown("""
    **导入方式说明：**
    - **全量重新导入**：清空数据库中所有历史销售记录，从上述 Excel 文件重新导入全部数据（约258万条）。导入过程需要几分钟，请耐心等待。
    - **增量追加导入**：保留现有数据，将 Excel 文件中的数据追加到数据库。注意：可能导致重复数据，一般不建议使用。
    """)

    col1, col2 = st.columns(2)

    # ---- 导入进度回调 ----
    def _make_progress_cb(progress_bar, status_text, total_batches):
        """生成实时进度回调，每写入一个批次更新一次 UI"""
        def cb(global_batch, total_b, year, batch_rows, year_imported, year_total):
            pct = global_batch / total_b if total_b > 0 else 0
            progress_bar.progress(pct, text=f"正在导入 {year}年: {year_imported:,}/{year_total:,} 行")
            status_text.text(f"批次 {global_batch}/{total_b} | 本年已导入 {year_imported:,} 行")
        return cb

    # 全量导入 + 确认机制
    with col1:
        confirm_clear = st.checkbox("我确认要清空现有数据并重新导入", key="confirm_clear")
        if st.button("🔄 全量重新导入", type="primary", disabled=not confirm_clear):
            with st.status("正在全量导入...", expanded=True) as status:
                progress_bar = st.progress(0, text="准备导入...")
                status_text = st.empty()
                cb = _make_progress_cb(progress_bar, status_text, 0)  # 总批次在回调中动态计算
                # 需要重新创建回调（因为 total_batches 在 import 内部计算）
                # 使用共享列表来传递 total_batches
                shared = {"total_batches": 0}
                def dynamic_cb(gb, tb, year, br, yi, yt):
                    shared["total_batches"] = tb
                    pct = gb / tb if tb > 0 else 0
                    progress_bar.progress(min(pct, 1.0), text=f"正在导入 {year}年: {yi:,}/{yt:,} 行")
                    status_text.text(f"批次 {gb}/{tb} | 本年已导入 {yi:,} 行")

                total, results = import_without_prompt(clear_existing=True, progress_callback=dynamic_cb)
                progress_bar.progress(1.0, text="导入完成")
                status_text.text("")
                st.write("**导入结果：**")
                for year, cnt, s in results:
                    st.write(f"  {year}年: {cnt:,} 行 - {s}")

                status.update(label="正在刷新统计缓存...", state="running")
                refresh_bar = st.progress(0, text="刷新中...")
                def refresh_cb(step, total_s, desc):
                    refresh_bar.progress(step / total_s, text=f"[{step}/{total_s}] {desc}")
                refresh_precomputed_stats(progress_callback=refresh_cb)
                refresh_bar.progress(1.0, text="刷新完成")
                st.cache_data.clear()
                status.update(label=f"全量导入完成！共 {total:,} 条记录", state="complete")

    # 追加导入
    with col2:
        if st.button("➕ 增量追加导入"):
            with st.status("正在追加导入...", expanded=True) as status:
                progress_bar = st.progress(0, text="准备追加导入...")
                status_text = st.empty()
                def dynamic_cb2(gb, tb, year, br, yi, yt):
                    pct = gb / tb if tb > 0 else 0
                    progress_bar.progress(min(pct, 1.0), text=f"正在导入 {year}年: {yi:,}/{yt:,} 行")
                    status_text.text(f"批次 {gb}/{tb} | 本年已导入 {yi:,} 行")

                total, results = import_without_prompt(clear_existing=False, progress_callback=dynamic_cb2)
                progress_bar.progress(1.0, text="追加完成")
                status_text.text("")
                st.write("**导入结果：**")
                for year, cnt, s in results:
                    st.write(f"  {year}年: {cnt:,} 行 - {s}")

                status.update(label="正在刷新统计缓存...", state="running")
                refresh_bar = st.progress(0, text="刷新中...")
                def refresh_cb2(step, total_s, desc):
                    refresh_bar.progress(step / total_s, text=f"[{step}/{total_s}] {desc}")
                refresh_precomputed_stats(progress_callback=refresh_cb2)
                refresh_bar.progress(1.0, text="刷新完成")
                st.cache_data.clear()
                status.update(label=f"追加导入完成！共 {total:,} 条记录", state="complete")

    # 自定义文件上传（改进4：字段映射预览）
    st.subheader("上传自定义数据")
    st.markdown("""
    系统会自动识别 Excel 列名并匹配标准字段。支持一定程度的字段名差异（如"税率%"会自动映射为"税率"）。
    上传后可预览字段匹配情况，确认无误后再导入。
    """)

    uploaded = st.file_uploader("上传 Excel 文件", type=["xlsx", "xls"])
    table_display = st.selectbox("目标表", list(TABLE_NAME_MAP.keys()))
    target_table = TABLE_NAME_MAP[table_display]

    if uploaded:
        try:
            df = pd.read_excel(uploaded)
            st.write(f"文件包含 {len(df)} 行, {len(df.columns)} 列")

            # 字段映射预览
            st.write("**字段匹配情况：**")
            mapping_info = []
            for col in df.columns:
                matched = COLUMN_MAPPING.get(col, col)
                is_standard = matched in STANDARD_COLUMNS
                mapping_info.append({
                    "Excel列名": col,
                    "映射为": matched if is_standard else "—",
                    "状态": "✅ 已匹配" if is_standard else "⚠️ 未匹配(将忽略)"
                })
            st.dataframe(pd.DataFrame(mapping_info), use_container_width=True)

            st.write("数据预览 (前5行):")
            st.dataframe(df.head(), use_container_width=True)

            if st.button("确认导入", type="primary"):
                import datetime
                # 库存表和在途订单表缺少日期列时自动补充当天日期
                if target_table in ("daily_inventory", "daily_pending_orders") and "日期" not in df.columns:
                    today = datetime.date.today().isoformat()
                    df.insert(0, "日期", today)
                    st.info(f"已自动补充日期: {today}")
                # 过滤掉物料编码为空的行（如汇总行）
                if "物料编码" in df.columns:
                    before = len(df)
                    df = df.dropna(subset=["物料编码"])
                    removed = before - len(df)
                    if removed > 0:
                        st.info(f"已过滤 {removed} 行物料编码为空的数据（如汇总行）")
                conn = get_connection()
                df.to_sql(target_table, conn, if_exists="append", index=False)
                conn.close()
                st.success(f"成功导入 {len(df)} 行到 {table_display}")
        except Exception as e:
            st.error(f"读取失败: {e}")


# =================== 销量分析 ===================
elif page == "📈 销量分析":
    st.title("销量分析")

    has_data = cached_overview()["总记录数"] > 0

    if not has_data:
        st.warning("暂无数据，请先导入")
    else:
        tab1, tab2 = st.tabs(["月均销量", "月度趋势"])

        with tab1:
            st.subheader("月均销量分析")
            col1, col2, col3 = st.columns(3)
            months = col1.number_input("近几个月", min_value=1, max_value=36, value=3)

            skus = ["全部"] + cached_unique_values("物料编码")
            depts = ["全部"] + cached_unique_values("销售部门")
            sel_sku = col2.selectbox("物料编码", skus, key="avg_sku")
            sel_dept = col3.selectbox("销售部门", depts, key="avg_dept")

            if st.button("查询月均销量", key="btn_avg", type="primary"):
                sku_param = None if sel_sku == "全部" else sel_sku
                dept_param = None if sel_dept == "全部" else sel_dept
                with st.spinner("正在查询..."):
                    df = monthly_avg_sales(sku=sku_param, department=dept_param, months=months)
                if not df.empty:
                    st.dataframe(df, use_container_width=True)
                    st.download_button("下载结果", df.to_csv(index=False).encode("utf-8-sig"),
                                       "月均销量.csv", "text/csv")
                else:
                    st.info("无匹配数据")

        with tab2:
            st.subheader("月度销量趋势")
            col1, col2 = st.columns(2)
            sel_sku2 = col1.selectbox("物料编码", skus, key="trend_sku")
            sel_dept2 = col2.selectbox("销售部门", depts, key="trend_dept")

            if st.button("查询趋势", key="btn_trend", type="primary"):
                sku_p = None if sel_sku2 == "全部" else sel_sku2
                dept_p = None if sel_dept2 == "全部" else sel_dept2
                with st.spinner("正在查询..."):
                    trend = monthly_trend(sku=sku_p, department=dept_p)
                if not trend.empty:
                    fig = px.line(trend, x="年月", y="销量", title="月度销量趋势")
                    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
                    fig2 = px.bar(trend, x="年月", y="销售额", title="月度销售额")
                    st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CONFIG)
                else:
                    st.info("无匹配数据")


# =================== 同比分析 ===================
elif page == "🔄 同比分析":
    st.title("同比分析")

    col1, col2, col3 = st.columns(3)
    year1 = col1.number_input("对比年份1", min_value=2020, max_value=2026, value=2024)
    year2 = col2.number_input("对比年份2", min_value=2020, max_value=2026, value=2025)
    month = col3.number_input("月份 (0=全年)", min_value=0, max_value=12, value=0)

    month_param = month if month > 0 else None

    if st.button("执行对比"):
        df = year_over_year(year1, year2, month=month_param)
        if not df.empty:
            st.dataframe(df, use_container_width=True)

            # 高亮增长/下降
            growth_col = f"同比增长率%"
            if growth_col in df.columns:
                positive = df[df[growth_col] > 0]
                negative = df[df[growth_col] < 0]
                col1, col2 = st.columns(2)
                col1.metric("增长 SKU 数", len(positive))
                col2.metric("下降 SKU 数", len(negative))

            st.download_button("下载结果", df.to_csv(index=False).encode("utf-8-sig"),
                               f"同比分析_{year1}vs{year2}.csv", "text/csv")
        else:
            st.info("无匹配数据")


# =================== 排行榜 ===================
elif page == "🏆 排行榜":
    st.title("排行榜")

    tab1, tab2 = st.tabs(["SKU 排行", "部门/渠道排行"])

    with tab1:
        col1, col2, col3, col4 = st.columns(4)
        year = col1.number_input("年份 (0=全部)", min_value=0, max_value=2026, value=2025, key="rank_year")
        month = col2.number_input("月份 (0=全年)", min_value=0, max_value=12, value=0, key="rank_month")
        top_n = col3.number_input("显示条数", min_value=5, max_value=100, value=20)
        metric = col4.selectbox("排序指标", ["销量", "销售额"])

        year_p = year if year > 0 else None
        month_p = month if month > 0 else None

        if st.button("查询 SKU 排行", key="btn_sku_rank", type="primary"):
            with st.spinner("正在查询..."):
                df = top_sku(year=year_p, month=month_p, top_n=top_n, metric=metric)
            if not df.empty:
                st.dataframe(df, use_container_width=True)
                fig = px.bar(df.head(20), x="物料名称", y=metric, title=f"Top {min(20, len(df))} SKU ({metric})")
                fig.update_xaxes(tickangle=45)
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("无匹配数据")

    with tab2:
        col1, col2 = st.columns(2)
        year2 = col1.number_input("年份 (0=全部)", min_value=0, max_value=2026, value=2025, key="dept_year")
        month2 = col2.number_input("月份 (0=全年)", min_value=0, max_value=12, value=0, key="dept_month")

        year_p2 = year2 if year2 > 0 else None
        month_p2 = month2 if month2 > 0 else None

        if st.button("查询部门排行", key="btn_dept_rank", type="primary"):
            with st.spinner("正在查询..."):
                df2 = top_department(year=year_p2, month=month_p2)
            if not df2.empty:
                st.dataframe(df2, use_container_width=True)
                fig = px.pie(df2.head(10), values="销量", names="销售部门", title="部门销量占比 (Top 10)")
                st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info("无匹配数据")


# =================== 采购订单分析 ===================
elif page == "🔮 采购订单分析":
    st.title("采购订单分析")

    st.write("输入拟采购 SKU 和数量，系统将基于历史数据进行多维分析")

    col1, col2 = st.columns(2)
    sku_input = col1.text_input("物料编码", placeholder="输入物料编码")
    qty_input = col2.number_input("拟采购数量", min_value=0, value=0)

    if st.button("分析", type="primary") and sku_input:
        result = purchase_order_analysis(sku_input, qty_input)

        # 展示分析结果
        col1, col2, col3 = st.columns(3)
        col1.metric("近3月月均销量", f"{result['近3月月均销量']:,.0f}")
        col2.metric("近6月月均销量", f"{result['近6月月均销量']:,.0f}")
        col3.metric("当前库存", f"{result['当前库存']:,.0f}")

        col4, col5, col6 = st.columns(3)
        col4.metric("未交订单", f"{result['未交订单']:,.0f}")
        col5.metric("拟采购数量", f"{result['拟采购数量']:,.0f}")
        col6.metric("预估可售月数", result["预估可售月数"])

        # 该 SKU 历史趋势
        st.subheader(f"{sku_input} 历史销量趋势")
        trend = monthly_trend(sku=sku_input)
        if not trend.empty:
            fig = px.line(trend, x="年月", y="销量", title="月度销量")
            st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    # 批量分析
    st.subheader("批量采购分析")
    uploaded = st.file_uploader("上传采购清单 (需含 物料编码、采购数量 列)", type=["xlsx", "xls", "csv"])
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                order_df = pd.read_csv(uploaded)
            else:
                order_df = pd.read_excel(uploaded)
            st.write("预览:")
            st.dataframe(order_df.head())

            if st.button("批量分析"):
                results = []
                for _, row in order_df.iterrows():
                    sku = row.get("物料编码", "")
                    qty = row.get("采购数量", 0)
                    if sku:
                        r = purchase_order_analysis(str(sku), qty)
                        r["物料编码"] = sku
                        results.append(r)
                if results:
                    result_df = pd.DataFrame(results)
                    st.dataframe(result_df, use_container_width=True)
                    st.download_button("下载分析结果",
                                       result_df.to_csv(index=False).encode("utf-8-sig"),
                                       "采购分析结果.csv", "text/csv")
        except Exception as e:
            st.error(f"读取失败: {e}")


# =================== 预测偏差 ===================
elif page == "📋 预测偏差":
    st.title("预测偏差分析")
    st.write("对比月度预测与实际销量，标记偏差 >30% 的 SKU")

    forecast_month = st.text_input("预测月份 (格式: YYYY-MM)", placeholder="2025-03")
    if st.button("分析偏差") and forecast_month:
        df = forecast_deviation(forecast_month)
        if not df.empty:
            abnormal = df[df["状态"] == "异常"]
            col1, col2 = st.columns(2)
            col1.metric("总 SKU", len(df))
            col2.metric("异常 SKU (偏差>30%)", len(abnormal))

            st.subheader("异常 SKU 列表")
            if not abnormal.empty:
                st.dataframe(abnormal, use_container_width=True)

            st.subheader("全部数据")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("该月份无预测数据")


# =================== 字段批量替换 ===================
elif page == "🔧 字段批量替换":
    st.title("字段批量替换")
    st.write("批量替换数据库中指定字段的值")

    replace_table_display = st.selectbox("目标表", list(TABLE_NAME_MAP.keys()), key="replace_table")
    table = TABLE_NAME_MAP[replace_table_display]
    field = st.text_input("字段名", placeholder="例: 销售部门")
    old_val = st.text_input("原值", placeholder="例: 厨电雄狮团队")
    new_val = st.text_input("新值", placeholder="例: 康佳厨电事业部KA客户业务部")

    if field and old_val:
        # 预览影响
        try:
            conn = get_connection()
            preview_count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {field} = ?", (old_val,)
            ).fetchone()[0]
            conn.close()
            st.info(f"将影响 {preview_count:,} 条记录")
        except Exception as e:
            st.error(f"查询失败: {e}")

    if st.button("执行替换", type="primary"):
        if not all([table, field, old_val, new_val]):
            st.error("请填写所有字段")
        else:
            affected = batch_replace_field(table, field, old_val, new_val)
            st.success(f"替换完成! 共更新 {affected:,} 条记录")

    # 替换历史
    st.subheader("替换历史")
    try:
        log_df = query_to_df("SELECT * FROM field_replace_log ORDER BY 操作时间 DESC LIMIT 50")
        if not log_df.empty:
            st.dataframe(log_df, use_container_width=True)
        else:
            st.info("暂无替换记录")
    except Exception:
        pass


# =================== 自定义查询（可视化筛选器） ===================
elif page == "🔍 自定义查询":
    st.title("数据筛选查询")
    st.write("通过下方筛选条件查询销售数据，无需编写任何代码")

    # 查询类型
    query_type = st.selectbox("查询类型", ["销售明细", "按SKU汇总", "按部门汇总", "按客户汇总", "按月汇总"])

    # 筛选条件
    st.subheader("筛选条件（均为可选）")
    fc1, fc2 = st.columns(2)
    year_start = fc1.number_input("起始年份 (0=不限)", min_value=0, max_value=2026, value=0, key="vq_ys")
    year_end = fc2.number_input("结束年份 (0=不限)", min_value=0, max_value=2026, value=0, key="vq_ye")

    month_options = list(range(1, 13))
    selected_months = st.multiselect("月份（可多选，不选=全部）", month_options, default=[], key="vq_months")

    fc3, fc4 = st.columns(2)
    skus = ["不限"] + cached_unique_values("物料编码")
    depts = ["不限"] + cached_unique_values("销售部门")
    sel_sku = fc3.selectbox("物料编码", skus, key="vq_sku")
    sel_dept = fc4.selectbox("销售部门", depts, key="vq_dept")

    fc5, fc6 = st.columns(2)
    customers = ["不限"] + cached_unique_values("客户")
    categories = ["不限"] + cached_unique_values("产品类别")
    sel_cust = fc5.selectbox("客户", customers, key="vq_cust")
    sel_cat = fc6.selectbox("产品类别", categories, key="vq_cat")

    fc7, _ = st.columns(2)
    cust_categories = ["不限"] + cached_unique_values("客户类别")
    sel_cust_cat = fc7.selectbox("客户类别", cust_categories, key="vq_cust_cat")

    # 排序和限制
    st.subheader("排序与显示")
    sc1, sc2, sc3 = st.columns(3)

    sort_options_map = {
        "销售明细": ["日期", "销售数量", "销售收入_折扣后", "价税合计_折扣后", "物料编码", "客户", "销售部门"],
        "按SKU汇总": ["总销量", "销售收入", "价税合计", "物料编码"],
        "按部门汇总": ["总销量", "销售收入", "价税合计", "销售部门", "SKU数", "客户数"],
        "按客户汇总": ["总销量", "销售收入", "价税合计", "客户", "SKU数"],
        "按月汇总": ["年", "月", "总销量", "销售收入", "价税合计", "SKU数", "客户数"],
    }
    sort_options = sort_options_map.get(query_type, ["总销量"])
    sort_field = sc1.selectbox("排序字段", sort_options, key="vq_sort")
    sort_order = sc2.selectbox("排序方向", ["降序", "升序"], key="vq_dir")
    limit = sc3.number_input("最多显示条数", min_value=10, max_value=5000, value=500, key="vq_limit")

    if st.button("查询", key="btn_vq", type="primary"):
        with st.spinner("正在查询..."):
            df = visual_query(
                query_type=query_type,
                year_start=year_start if year_start > 0 else None,
                year_end=year_end if year_end > 0 else None,
                months=selected_months if selected_months else None,
                sku=sel_sku if sel_sku != "不限" else None,
                department=sel_dept if sel_dept != "不限" else None,
                customer=sel_cust if sel_cust != "不限" else None,
                category=sel_cat if sel_cat != "不限" else None,
                customer_category=sel_cust_cat if sel_cust_cat != "不限" else None,
                sort_field=sort_field,
                sort_order="DESC" if sort_order == "降序" else "ASC",
                limit=limit,
            )
        if not df.empty:
            st.success(f"查询返回 {len(df)} 条记录")
            st.dataframe(df, use_container_width=True)
            st.download_button("下载结果", df.to_csv(index=False).encode("utf-8-sig"),
                               "查询结果.csv", "text/csv")
        else:
            st.info("无匹配数据")
