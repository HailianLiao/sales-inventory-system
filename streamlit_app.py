# -*- coding: utf-8 -*-
# Streamlit Cloud entry point
import os,sys
project_root=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,project_root)
from interface.app import *