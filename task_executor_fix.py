#!/usr/bin/env python3
"""
临时脚本：修复 task_executor.py 的缩进问题
"""

import re

with open('task_executor.py', 'r') as f:
    content = f.read()

# 找到 _execute_core 方法并提取
pattern = r'(    def _execute_core\(self\) -> bool:\s*\n        """核心执行逻辑"""\s*\n)(.*?)(?=\n    def |\nclass |\Z)'
match = re.search(pattern, content, re.DOTALL)

if match:
    print("找到 _execute_core 方法")
    # 这里需要手动修复，直接打印出来让用户处理
    print("需要手动修复缩进")
else:
    print("未找到方法")
