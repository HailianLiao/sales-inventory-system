# Streamlit Cloud 入口文件
import os
import sys

# 将项目根目录加入路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 导入 Streamlit 应用
from interface.app import *

# Streamlit Cloud 入口
if __name__ == '__main__':
    pass  # app.py 中的代码会在导入时自动执行

