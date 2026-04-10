"""
自动修复系统
当任务失败时，自动分析问题并尝试修复
"""
import os
import re
import shutil
import subprocess
from typing import Optional, Tuple


class AutoFixer:
    """
    自动修复器
    """
    
    ERROR_PATTERNS = {
        'git_pull_failed': [
            r'Failed to pull repository',
            r'git pull.*exit code\(1\)',
        ],
        'git_branch_conflict': [
            r'could not switch branch',
            r'A branch named.*already exists',
        ],
        'agent_code_error': [
            r"name '.*' is not defined",
            r'AttributeError:',
            r'SyntaxError:',
        ],
        'timeout_error': [
            r'TASK_TIMEOUT is not defined',
            r'timeout',
        ],
        'workspace_deleted': [
            r'working directory was deleted',
        ],
    }
    
    def __init__(self):
        self.fix_count = 0
        self.max_auto_fix = 3
    
    def analyze_error(self, error_msg: str) -> Tuple[str, str]:
        """分析错误类型"""
        for error_type, patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_msg, re.IGNORECASE):
                    return error_type, f"检测到 {error_type}"
        return 'unknown', '未知错误'
    
    def try_fix(self, error_type: str, repo: str, error_msg: str) -> Tuple[bool, str]:
        """尝试修复"""
        self.fix_count += 1
        if self.fix_count > self.max_auto_fix:
            return False, f"超过最大修复次数 ({self.max_auto_fix})"
        
        workspace_root = os.path.expanduser("~/kimi/workspace")
        repo_path = os.path.join(workspace_root, repo)
        
        try:
            if error_type == 'git_pull_failed' or error_type == 'git_branch_conflict':
                # 清理并重新克隆
                if os.path.exists(repo_path):
                    shutil.rmtree(repo_path, ignore_errors=True)
                return True, "已清理仓库目录，将重新克隆"
            
            elif error_type == 'agent_code_error' or error_type == 'timeout_error':
                # 清除 Python 缓存
                agent_dir = os.path.dirname(os.path.abspath(__file__))
                for root, dirs, files in os.walk(agent_dir):
                    for d in dirs:
                        if d == '__pycache__':
                            cache_path = os.path.join(root, d)
                            shutil.rmtree(cache_path, ignore_errors=True)
                return True, "已清除 Python 缓存"
            
            elif error_type == 'workspace_deleted':
                # 重新创建目录
                os.makedirs(repo_path, exist_ok=True)
                return True, "已重新创建工作目录"
            
            return False, "没有可用的修复方法"
        
        except Exception as e:
            return False, f"修复失败: {e}"
    
    def should_retry(self, error_type: str) -> bool:
        """是否应该重试"""
        return error_type in ['git_pull_failed', 'git_branch_conflict', 
                              'agent_code_error', 'timeout_error', 'workspace_deleted']


auto_fixer = AutoFixer()
