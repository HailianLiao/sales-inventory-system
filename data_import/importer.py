"""销售数据导入模块 - 兼容 2020-2026 各年度 Excel 差异"""
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SALES_FILES, COLUMN_MAPPING, STANDARD_COLUMNS, EXCEL_SERIAL_DATE_YEARS
from database.db_init import get_connection, init_database


def excel_serial_to_date(serial):
    """将 Excel 序列号转为日期字符串"""
    if pd.isna(serial):
        return None
    try:
        serial = int(serial)
        # Excel 日期起点: 1899-12-30
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=serial)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_date(value, year):
    """统一日期格式为 YYYY-MM-DD 字符串"""
    if pd.isna(value):
        return None

    # 已经是 datetime 类型
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")

    # Excel 序列号 (整数)
    if isinstance(value, (int, float, np.integer, np.floating)):
        if value > 40000:  # 合理的 Excel 日期范围
            return excel_serial_to_date(value)
        return None

    # 字符串日期
    if isinstance(value, str):
        value = value.strip()
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y.%m.%d"]:
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # 尝试 pandas 自动解析
        try:
            return pd.to_datetime(value).strftime("%Y-%m-%d")
        except Exception:
            return None

    return None


def load_excel_file(filepath, year):
    """加载并标准化单个 Excel 文件"""
    print(f"  正在读取: {os.path.basename(filepath)} ...", end=" ", flush=True)
    df = pd.read_excel(filepath)
    row_count = len(df)
    print(f"{row_count:,} 行")

    # 重命名列到标准名
    rename_map = {}
    for col in df.columns:
        if col in COLUMN_MAPPING:
            rename_map[col] = COLUMN_MAPPING[col]
    df = df.rename(columns=rename_map)

    # 统一日期处理
    if "日期" in df.columns:
        df["日期"] = df["日期"].apply(lambda v: normalize_date(v, year))

    # ===== 年/月字段处理：优先使用 Excel 原始值（内部销售周期） =====
    #
    # 2020-2023: 有 年(短年:20,21..), 月(1-12), 年和月("20-12")
    # 2024-2026: 有 年份("24-01") = 等价于 年和月
    #
    if "年和月" in df.columns:
        # 2020-2023: 直接用原始的 年和月
        # 年 字段是短年(20,21...)，转为完整年份
        if "年" in df.columns:
            df["年"] = df["年"].apply(lambda v: int(v) + 2000 if pd.notna(v) and int(v) < 100 else int(v) if pd.notna(v) else year)
        if "月" not in df.columns:
            df["月"] = 0
    elif "年份" in df.columns:
        # 2024-2026: 年份字段格式为 "YY-MM"，拆解为 年、月、年和月
        df["年和月"] = df["年份"]  # 直接用作年和月
        def parse_nianfen(val):
            if pd.isna(val):
                return year, 0
            s = str(val).strip()
            parts = s.split("-")
            if len(parts) == 2:
                y = int(parts[0]) + 2000
                m = int(parts[1])
                return y, m
            return year, 0
        parsed = df["年份"].apply(parse_nianfen)
        df["年"] = parsed.apply(lambda x: x[0])
        df["月"] = parsed.apply(lambda x: x[1])
    else:
        # 没有年月字段时，从日期推导作为 fallback
        if "日期" in df.columns:
            date_series = pd.to_datetime(df["日期"], errors="coerce")
            df["年"] = date_series.dt.year.fillna(year).astype(int)
            df["月"] = date_series.dt.month.fillna(0).astype(int)
        else:
            df["年"] = year
            df["月"] = 0
        # 生成年和月字段
        df["年和月"] = df.apply(
            lambda r: f"{int(r['年']) % 100:02d}-{int(r['月']):02d}" if r["月"] > 0 else None,
            axis=1
        )

    # 确保年/月为整数
    df["年"] = pd.to_numeric(df["年"], errors="coerce").fillna(year).astype(int)
    df["月"] = pd.to_numeric(df["月"], errors="coerce").fillna(0).astype(int)

    # 添加数据来源
    df["数据来源"] = f"{year}年销售数据"

    # 只保留标准列
    final_cols = [c for c in STANDARD_COLUMNS if c in df.columns]
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        for c in missing:
            df[c] = None
        final_cols = STANDARD_COLUMNS

    return df[final_cols]


def import_all_sales_data(progress_callback=None):
    """导入所有年度销售数据到数据库"""
    init_database()
    conn = get_connection()

    # 检查是否已有数据
    existing = conn.execute("SELECT COUNT(*) FROM sales_history").fetchone()[0]
    if existing > 0:
        print(f"数据库已有 {existing:,} 条记录")
        resp = input("是否清空后重新导入? (y/N): ").strip().lower()
        if resp != "y":
            print("跳过导入")
            conn.close()
            return existing
        conn.execute("DELETE FROM sales_history")
        conn.commit()
        print("已清空旧数据")

    total_imported = 0
    years = sorted(SALES_FILES.keys())

    for i, year in enumerate(years):
        filepath = SALES_FILES[year]
        if not os.path.exists(filepath):
            print(f"  [跳过] 文件不存在: {filepath}")
            continue

        df = load_excel_file(filepath, year)

        # 分批写入数据库 (每批 50000 行)
        batch_size = 50000
        for start in range(0, len(df), batch_size):
            batch = df.iloc[start:start + batch_size]
            batch.to_sql("sales_history", conn, if_exists="append", index=False)

        total_imported += len(df)
        pct = (i + 1) / len(years) * 100
        print(f"  -> 已导入 {len(df):,} 行 (累计 {total_imported:,}，进度 {pct:.0f}%)")

        if progress_callback:
            progress_callback(i + 1, len(years), year, len(df))

    conn.commit()
    conn.close()
    print(f"\n导入完成! 共 {total_imported:,} 条销售记录")
    return total_imported


def import_without_prompt(clear_existing=True, progress_callback=None):
    """
    无交互式导入 (供前端调用)
    progress_callback: callable(phase, year, year_imported, year_total, total_imported, message)
    """
    init_database()
    conn = get_connection()

    if clear_existing:
        if progress_callback:
            progress_callback("clear", 0, 0, 0, 0, "正在清空旧数据(秒级)...")
        # 用 DROP TABLE 代替 DELETE，速度快一万倍 (秒级 vs 分钟级)
        conn.execute("DROP TABLE IF EXISTS sales_history")
        conn.commit()
        conn.close()
        # 调用 init_database 重建表结构
        init_database()
        conn = get_connection()

    total_imported = 0
    results = []
    years = sorted(SALES_FILES.keys())
    batch_size = 50000

    for idx, year in enumerate(years):
        filepath = SALES_FILES[year]
        if not os.path.exists(filepath):
            results.append((year, 0, "文件不存在"))
            continue
        try:
            if progress_callback:
                progress_callback("read", year, 0, 0, total_imported,
                    f"正在读取 {year}年Excel文件 ({idx+1}/{len(years)})，请耐心等待...")
            df = load_excel_file(filepath, year)
            year_total = len(df)
            year_imported = 0
            if progress_callback:
                progress_callback("loaded", year, 0, year_total, total_imported,
                    f"{year}年已读取 {year_total:,} 行，开始写入数据库...")
            for start in range(0, len(df), batch_size):
                batch = df.iloc[start:start + batch_size]
                batch.to_sql("sales_history", conn, if_exists="append", index=False)
                year_imported += len(batch)
                total_imported += len(batch)
                if progress_callback:
                    progress_callback("import", year, year_imported, year_total, total_imported,
                                      f"{year}年: {year_imported:,}/{year_total:,}")
            results.append((year, len(df), "成功"))
        except Exception as e:
            results.append((year, 0, f"错误: {e}"))

    conn.commit()
    conn.close()
    return total_imported, results


def batch_replace_field(table, field, old_value, new_value):
    """批量替换指定表的指定字段值"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE {table} SET {field} = ? WHERE {field} = ?",
        (new_value, old_value)
    )
    affected = cursor.rowcount
    # 记录替换日志
    cursor.execute(
        "INSERT INTO field_replace_log (表名, 字段名, 原值, 新值, 影响行数) VALUES (?, ?, ?, ?, ?)",
        (table, field, old_value, new_value, affected)
    )
    conn.commit()
    conn.close()
    return affected


if __name__ == "__main__":
    import_all_sales_data()
