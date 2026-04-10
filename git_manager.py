"""
Git 管理模块
封装 GitPython，提供任务树分支管理
"""
import os
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import git
from git import Repo, GitCommandError

from config import config


@dataclass
class GitConfig:
    """Git 配置"""
    username: str
    email: str
    token: str


class GitManagerError(Exception):
    """Git 管理错误"""
    pass


class GitManager:
    """Git 仓库管理器"""
    
    def __init__(self, workspace_root: str = None):
        self.workspace_root = workspace_root or config.WORKSPACE_ROOT
        self.github_token = config.GITHUB_TOKEN
        self.github_username = config.GITHUB_USERNAME
        self.proxy_url = config.proxy_url if config.PROXY_HOST else None
        
        # 确保工作目录存在
        os.makedirs(self.workspace_root, exist_ok=True)
    
    def _get_repo_path(self, project_name: str) -> str:
        """获取项目本地路径"""
        # 清理项目名称，避免路径问题
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name)
        return os.path.join(self.workspace_root, safe_name)
    
    def _get_authenticated_url(self, repo_url: str) -> str:
        """获取带认证的仓库 URL"""
        if not self.github_token:
            return repo_url
        
        # 将 https://github.com/user/repo.git 转换为带 token 的格式
        if 'github.com' in repo_url and repo_url.startswith('https://'):
            # 移除可能的已存在认证信息
            clean_url = repo_url.replace(f"https://{self.github_username}:{self.github_token}@", "https://")
            clean_url = clean_url.replace("https://", f"https://{self.github_username}:{self.github_token}@")
            return clean_url
        return repo_url
    
    def clone_or_pull(self, project_name: str, repo_url: str) -> Repo:
        """
        克隆或拉取仓库
        
        Args:
            project_name: 项目名称
            repo_url: 仓库 URL
        
        Returns:
            GitPython Repo 对象
        """
        repo_path = self._get_repo_path(project_name)
        auth_url = self._get_authenticated_url(repo_url)
        
        # 设置代理环境变量
        env = config.get_env_with_proxy()
        
        if os.path.exists(os.path.join(repo_path, '.git')):
            # 已存在，执行 pull
            try:
                repo = Repo(repo_path)
                origin = repo.remotes.origin
                
                # 配置代理
                if self.proxy_url:
                    repo.git.config('http.proxy', self.proxy_url)
                    repo.git.config('https.proxy', self.proxy_url)
                
                # 尝试切换到 main/master 分支并拉取
                try:
                    # 检查当前分支
                    current_branch = repo.active_branch.name
                    if current_branch.startswith('task/'):
                        # 如果在任务分支，先切换到 main
                        if 'main' in [b.name for b in repo.branches]:
                            repo.git.checkout('main')
                        elif 'master' in [b.name for b in repo.branches]:
                            repo.git.checkout('master')
                except Exception:
                    pass  # 忽略切换分支错误
                
                # 拉取最新代码
                with repo.git.custom_environment(**env):
                    origin.pull()
                
                return repo
            except GitCommandError as e:
                # Pull 失败，尝试强制重置到 origin/main
                try:
                    repo = Repo(repo_path)
                    # 获取远程分支
                    repo.git.fetch('origin')
                    # 强制重置到 origin/main 或 origin/master
                    try:
                        repo.git.reset('--hard', 'origin/main')
                    except GitCommandError:
                        repo.git.reset('--hard', 'origin/master')
                    return repo
                except Exception as reset_error:
                    # 重置也失败，删除目录重新克隆
                    import shutil
                    shutil.rmtree(repo_path, ignore_errors=True)
                    os.makedirs(repo_path, exist_ok=True)
                    # 继续执行克隆逻辑
            except Exception as e:
                # 其他错误，删除重新克隆
                import shutil
                shutil.rmtree(repo_path, ignore_errors=True)
                os.makedirs(repo_path, exist_ok=True)
        else:
            # 不存在，执行 clone
            try:
                os.makedirs(repo_path, exist_ok=True)
                
                # 配置全局代理（临时）
                if self.proxy_url:
                    os.environ['HTTP_PROXY'] = self.proxy_url
                    os.environ['HTTPS_PROXY'] = self.proxy_url
                
                repo = Repo.clone_from(auth_url, repo_path, env=env)
                
                # 配置本地代理
                if self.proxy_url:
                    repo.git.config('http.proxy', self.proxy_url)
                    repo.git.config('https.proxy', self.proxy_url)
                
                return repo
            except GitCommandError as e:
                raise GitManagerError(f"Failed to clone repository: {e}")
    
    def create_task_branch(self, project_name: str, task_id: str, parent_branch: Optional[str] = None) -> str:
        """
        创建任务分支
        
        Args:
            project_name: 项目名称
            task_id: 任务 ID
            parent_branch: 父分支名（可选，默认从 main 或 master 切出）
        
        Returns:
            分支名
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        # 确定基础分支
        base_branch = parent_branch
        if not base_branch:
            # 优先使用 main，其次 master
            if 'main' in [b.name for b in repo.branches]:
                base_branch = 'main'
            elif 'master' in [b.name for b in repo.branches]:
                base_branch = 'master'
            else:
                base_branch = repo.active_branch.name
        
        # 检出基础分支并拉取最新代码
        try:
            repo.git.checkout(base_branch)
            repo.remotes.origin.pull(base_branch)
        except GitCommandError as e:
            raise GitManagerError(f"Failed to checkout base branch {base_branch}: {e}")
        
        # 创建任务分支
        branch_name = f"task/{task_id}"
        
        # 如果分支已存在，先删除
        if branch_name in [b.name for b in repo.branches]:
            repo.delete_head(branch_name, force=True)
        
        # 创建新分支
        new_branch = repo.create_head(branch_name)
        new_branch.checkout()
        
        return branch_name
    
    def commit_changes(self, project_name: str, message: str, task_id: Optional[str] = None) -> str:
        """
        提交更改
        
        Args:
            project_name: 项目名称
            message: 提交信息
            task_id: 任务 ID（可选，会附加到提交信息）
        
        Returns:
            commit SHA
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        # 检查是否有更改
        if not repo.is_dirty() and not repo.untracked_files:
            return repo.head.commit.hexsha  # 没有更改，返回当前 commit
        
        # 配置 Git 用户信息（如果未配置）
        if not repo.config_reader().has_option('user', 'name'):
            repo.config_writer().set_value('user', 'name', 'Kimi Agent').release()
        if not repo.config_reader().has_option('user', 'email'):
            repo.config_writer().set_value('user', 'email', 'kimi-agent@noreply.github.com').release()
        
        # 添加所有更改
        repo.git.add('.')
        
        # 构建提交信息
        full_message = message
        if task_id:
            full_message = f"[{task_id}] {message}\n\nTask: {task_id}"
        
        # 提交
        commit = repo.index.commit(full_message)
        return commit.hexsha
    
    def push_branch(self, project_name: str, branch_name: Optional[str] = None) -> None:
        """
        推送分支到远程
        
        Args:
            project_name: 项目名称
            branch_name: 分支名（可选，默认推送当前分支）
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        if not branch_name:
            branch_name = repo.active_branch.name
        
        # 设置代理环境变量
        env = config.get_env_with_proxy()
        
        try:
            with repo.git.custom_environment(**env):
                repo.remotes.origin.push(branch_name)
        except GitCommandError as e:
            raise GitManagerError(f"Failed to push branch {branch_name}: {e}")
    
    def commit_and_push(self, project_name: str, message: str, task_id: Optional[str] = None) -> str:
        """
        提交并推送
        
        Returns:
            commit SHA
        """
        commit_sha = self.commit_changes(project_name, message, task_id)
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        self.push_branch(project_name, repo.active_branch.name)
        return commit_sha
    
    def get_task_tree(self, project_name: str) -> Dict[str, Any]:
        """
        获取任务分支树结构
        
        Returns:
            树形结构字典
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        # 获取所有 task/ 开头的分支
        task_branches = [b for b in repo.branches if b.name.startswith('task/')]
        
        tree = {
            "main": [],
            "master": [],
        }
        
        for branch in task_branches:
            # 解析任务 ID
            task_id = branch.name.replace('task/', '')
            
            # 找出父任务（通过 commit 历史）
            # 简化版本：直接从分支名解析，假设 task/abc_def 的父任务可能是 abc
            parent_id = None
            if '_' in task_id:
                parent_id = task_id.rsplit('_', 1)[0]
                parent_branch = f"task/{parent_id}"
                if parent_branch in [b.name for b in task_branches]:
                    if parent_branch not in tree:
                        tree[parent_branch] = []
                    tree[parent_branch].append(branch.name)
                else:
                    tree.setdefault("main", []).append(branch.name)
            else:
                tree.setdefault("main", []).append(branch.name)
        
        return tree
    
    def get_branch_commits(self, project_name: str, branch_name: str, max_count: int = 10) -> List[Dict]:
        """
        获取分支提交历史
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        commits = []
        for commit in repo.iter_commits(branch_name, max_count=max_count):
            commits.append({
                "sha": commit.hexsha[:8],
                "full_sha": commit.hexsha,
                "message": commit.message.strip(),
                "author": str(commit.author),
                "date": commit.committed_datetime.isoformat()
            })
        
        return commits
    
    def cleanup_task_branch(self, project_name: str, task_id: str) -> None:
        """
        清理任务分支（任务失败或取消时）
        """
        repo_path = self._get_repo_path(project_name)
        repo = Repo(repo_path)
        
        branch_name = f"task/{task_id}"
        
        try:
            # 切回主分支
            if 'main' in [b.name for b in repo.branches]:
                repo.git.checkout('main')
            elif 'master' in [b.name for b in repo.branches]:
                repo.git.checkout('master')
            
            # 删除本地分支
            if branch_name in [b.name for b in repo.branches]:
                repo.delete_head(branch_name, force=True)
        
        except GitCommandError as e:
            raise GitManagerError(f"Failed to cleanup branch {branch_name}: {e}")


# 全局 GitManager 实例
git_manager = GitManager()


if __name__ == "__main__":
    # 测试代码
    print("GitManager test - requires valid GitHub repo")
    print(f"Workspace: {config.WORKSPACE_ROOT}")
    print(f"Token configured: {bool(config.GITHUB_TOKEN)}")
