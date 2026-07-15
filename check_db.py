import sqlite3
import traceback
import os

db = os.path.join(os.path.dirname(__file__), 'database', 'sales.db')
out = os.path.join(os.environ.get('TEMP', 'C:/Temp'), 'sales_check.txt')

try:
    conn = sqlite3.connect(db)
    lines = []
    
    total = conn.execute('SELECT COUNT(*) FROM sales_history').fetchone()[0]
    lines.append('Total: %d' % total)
    
    # pragma to get column info
    cols = conn.execute('PRAGMA table_info(sales_history)').fetchall()
    col_names = [c[1] for c in cols]
    lines.append('Columns: %d' % len(col_names))
    
    # year distribution using positional column (年 is column index 20)
    year_col = col_names[20] if len(col_names) > 20 else 'unknown'
    lines.append('Year column name: %s' % year_col)
    
    cursor = conn.execute('SELECT * FROM sales_history LIMIT 2')
    desc = [d[0] for d in cursor.description]
    lines.append('Query desc: %s' % str(desc[:5]))
    sample = cursor.fetchall()
    for row in sample:
        lines.append('Row: %s' % str(row[:8]))
    
    # year counts
    yr_rows = conn.execute(
        "SELECT * FROM ("
        "  SELECT *, ROW_NUMBER() OVER() as rn FROM ("
        "    SELECT CAST(substr(日期,1,4) AS INTEGER) as yr, COUNT(*) as cnt "
        "    FROM sales_history WHERE 日期 IS NOT NULL "
        "    GROUP BY CAST(substr(日期,1,4) AS INTEGER)"
        "  )"
        ")"
    ).fetchall()
    lines.append('Year groups: %d' % len(yr_rows))
    for r in yr_rows:
        lines.append('  yr=%s cnt=%s' % (str(r[0]), str(r[1])))
    
    conn.close()
    
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        
except Exception:
    with open(out, 'w', encoding='utf-8') as f:
        f.write(traceback.format_exc())
