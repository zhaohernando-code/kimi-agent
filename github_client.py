"""
GitHub API 客户端
封装 GitHub REST API，用于管理 Issues、标签、评论
"""
import os
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime

import requests

from config import config


@dataclass
class GHIssue:
    """GitHub Issue 数据类"""
    number: int
    title: str
    body: str
    state: str  # open, closed
    labels: List[str]
    comments_count: int
    created_at: str
    updated_at: str
    html_url: str
    
    @property
    def status_label(self) -> Optional[str]:
        """获取状态标签"""
        for label in self.labels:
            if label.startswith('status:'):
                return label
        return None
    
    @property
    def is_pending(self) -> bool:
        return self.status_label == 'status:pending'
    
    @property
    def is_running(self) -> bool:
        return self.status_label == 'status:running'
    
    @property
    def is_completed(self) -> bool:
        return self.status_label == 'status:completed'
    
    @property
    def is_failed(self) -> bool:
        return self.status_label == 'status:failed'


@dataclass
class GHComment:
    """GitHub Issue 评论"""
    id: int
    body: str
    created_at: str
    user_login: str


class GitHubClientError(Exception):
    """GitHub API 错误"""
    pass


class GitHubClient:
    """GitHub API 客户端"""
    
    BASE_URL = "https://api.github.com"
    STATUS_LABELS = ['status:pending', 'status:running', 'status:completed', 'status:failed']
    
    def __init__(self, token: str = None, username: str = None):
        self.token = token or config.GITHUB_TOKEN
        self.username = username or config.GITHUB_USERNAME
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json'
        })
        # 配置代理
        if config.PROXY_HOST:
            proxy_url = f"http://{config.PROXY_USER}:{config.PROXY_PASS}@{config.PROXY_HOST}:{config.PROXY_PORT}"
            self.session.proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
    
    def _request(self, method: str, path: str, **kwargs) -> Any:
        """发送请求"""
        url = f"{self.BASE_URL}{path}"
        try:
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 204:
                return None
            if not response.ok:
                raise GitHubClientError(
                    f"GitHub API {method} {path} failed: {response.status_code} - {response.text}"
                )
            return response.json() if response.text else None
        except requests.exceptions.RequestException as e:
            raise GitHubClientError(f"Request failed: {e}")
    
    def _get(self, path: str, **kwargs) -> Any:
        return self._request('GET', path, **kwargs)
    
    def _post(self, path: str, **kwargs) -> Any:
        return self._request('POST', path, **kwargs)
    
    def _patch(self, path: str, **kwargs) -> Any:
        return self._request('PATCH', path, **kwargs)
    
    # ========== 仓库 ==========
    
    def list_repos(self) -> List[Dict]:
        """列出用户的仓库"""
        return self._get(f'/users/{self.username}/repos?per_page=100&sort=updated')
    
    def get_repo(self, repo: str) -> Dict:
        """获取仓库详情"""
        return self._get(f'/repos/{self.username}/{repo}')
    
    # ========== Issues ==========
    
    def list_issues(self, repo: str, state: str = 'all', labels: str = None) -> List[GHIssue]:
        """
        列出仓库的 Issues
        
        Args:
            repo: 仓库名
            state: open, closed, all
            labels: 标签筛选，如 "status:pending"
        """
        url = f'/repos/{self.username}/{repo}/issues?state={state}&per_page=100&sort=created&direction=desc'
        if labels:
            url += f'&labels={labels}'
        
        data = self._get(url)
        return [self._parse_issue(item) for item in data]
    
    def get_issue(self, repo: str, number: int) -> GHIssue:
        """获取单个 Issue"""
        data = self._get(f'/repos/{self.username}/{repo}/issues/{number}')
        return self._parse_issue(data)
    
    def create_issue(self, repo: str, title: str, body: str, labels: List[str] = None) -> GHIssue:
        """创建 Issue"""
        data = {
            'title': title,
            'body': body,
            'labels': labels or ['status:pending']
        }
        result = self._post(f'/repos/{self.username}/{repo}/issues', json=data)
        return self._parse_issue(result)
    
    def update_issue(self, repo: str, number: int, **kwargs) -> GHIssue:
        """更新 Issue"""
        result = self._patch(f'/repos/{self.username}/{repo}/issues/{number}', json=kwargs)
        return self._parse_issue(result)
    
    def set_issue_labels(self, repo: str, number: int, labels: List[str]) -> None:
        """设置 Issue 标签"""
        self._request('PUT', f'/repos/{self.username}/{repo}/issues/{number}/labels', json=labels)
    
    def _parse_issue(self, data: Dict) -> GHIssue:
        """解析 Issue 数据"""
        return GHIssue(
            number=data['number'],
            title=data['title'],
            body=data.get('body', ''),
            state=data['state'],
            labels=[label['name'] for label in data.get('labels', [])],
            comments_count=data['comments'],
            created_at=data['created_at'],
            updated_at=data['updated_at'],
            html_url=data['html_url']
        )
    
    # ========== 评论 ==========
    
    def list_comments(self, repo: str, issue_number: int) -> List[GHComment]:
        """列出 Issue 评论"""
        data = self._get(f'/repos/{self.username}/{repo}/issues/{issue_number}/comments?per_page=100')
        return [self._parse_comment(item) for item in data]
    
    def create_comment(self, repo: str, issue_number: int, body: str) -> GHComment:
        """创建评论"""
        result = self._post(f'/repos/{self.username}/{repo}/issues/{issue_number}/comments', json={'body': body})
        return self._parse_comment(result)
    
    def _parse_comment(self, data: Dict) -> GHComment:
        """解析评论数据"""
        return GHComment(
            id=data['id'],
            body=data['body'],
            created_at=data['created_at'],
            user_login=data['user']['login']
        )
    
    # ========== 标签 ==========
    
    def ensure_status_labels(self, repo: str) -> None:
        """确保状态标签存在"""
        colors = {
            'status:pending': 'e4e669',    # 黄色
            'status:running': '0075ca',    # 蓝色
            'status:completed': '0e8a16',  # 绿色
            'status:failed': 'd73a4a'      # 红色
        }
        
        for label in self.STATUS_LABELS:
            try:
                self._post(f'/repos/{self.username}/{repo}/labels', json={
                    'name': label,
                    'color': colors[label]
                })
            except GitHubClientError:
                # 标签已存在，忽略 422 错误
                pass
    
    # ========== 便捷方法 ==========
    
    def update_issue_status(self, repo: str, number: int, status: str, comment: str = None) -> None:
        """
        更新 Issue 状态
        
        Args:
            repo: 仓库名
            number: Issue 编号
            status: pending, running, completed, failed
            comment: 可选的评论内容
        """
        # 更新标签
        labels = [f'status:{status}']
        self.set_issue_labels(repo, number, labels)
        
        # 添加评论
        if comment:
            self.create_comment(repo, number, comment)
    
    def append_log(self, repo: str, issue_number: int, log_content: str) -> None:
        """追加执行日志到 Issue 评论"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        body = f"**[{timestamp}]**\n```\n{log_content}\n```"
        self.create_comment(repo, issue_number, body)
    
    def get_pending_issues(self, repo: str) -> List[GHIssue]:
        """获取待执行的 Issues"""
        return self.list_issues(repo, state='open', labels='status:pending')
    
    def get_running_issues(self, repo: str) -> List[GHIssue]:
        """获取执行中的 Issues"""
        return self.list_issues(repo, state='open', labels='status:running')


# 全局客户端实例
github_client = GitHubClient()


if __name__ == '__main__':
    # 测试
    print("Testing GitHub Client...")
    client = GitHubClient()
    
    # 列出仓库
    repos = client.list_repos()
    print(f"Found {len(repos)} repos")
    
    # 检查 claude-dashboard 是否存在
    claude_repos = [r for r in repos if 'claude' in r['name'].lower()]
    if claude_repos:
        repo_name = claude_repos[0]['name']
        print(f"\nChecking issues in {repo_name}...")
        issues = client.list_issues(repo_name)
        print(f"Found {len(issues)} issues")
        for issue in issues[:3]:
            print(f"  #{issue.number}: {issue.title} [{issue.status_label or 'no status'}]")
