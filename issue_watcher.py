"""
Issue 监听器
轮询 GitHub Issues 检测新任务
"""
import time
import threading
from typing import Callable, List, Dict, Optional
from datetime import datetime, timedelta

from github_client import github_client, GHIssue, GitHubClientError


class IssueWatcherError(Exception):
    """监听器错误"""
    pass


class IssueWatcher:
    """
    Issue 监听器
    
    负责：
    1. 轮询指定仓库的 Issues
    2. 检测新任务（status:pending）
    3. 处理状态变更
    4. 任务分发
    """
    
    def __init__(
        self,
        repo: str,
        poll_interval: int = 60,
        on_new_task: Callable[[GHIssue], None] = None,
        on_task_cancelled: Callable[[GHIssue], None] = None
    ):
        """
        初始化监听器
        
        Args:
            repo: 监听的仓库名
            poll_interval: 轮询间隔（秒）
            on_new_task: 新任务回调
            on_task_cancelled: 任务取消回调
        """
        self.repo = repo
        self.poll_interval = poll_interval
        self.on_new_task = on_new_task
        self.on_task_cancelled = on_task_cancelled
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_check_time: Optional[datetime] = None
        self._known_issues: Dict[int, GHIssue] = {}
        self._lock = threading.Lock()
        
        # 确保状态标签存在
        try:
            github_client.ensure_status_labels(repo)
        except GitHubClientError as e:
            print(f"Warning: Failed to ensure status labels: {e}")
    
    def start(self) -> None:
        """启动监听"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        print(f"[Watcher] Started watching {self.repo} (interval: {self.poll_interval}s)")
    
    def stop(self) -> None:
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print(f"[Watcher] Stopped watching {self.repo}")
    
    def _watch_loop(self) -> None:
        """监听循环"""
        while self._running:
            try:
                self._check_issues()
            except Exception as e:
                print(f"[Watcher] Error checking issues: {e}")
            
            # 等待下次轮询
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                time.sleep(1)
    
    def _check_issues(self) -> None:
        """检查 Issues 变化"""
        # 获取所有带状态标签的 open issues
        issues = self._fetch_issues_with_status()
        
        with self._lock:
            current_issue_ids = set()
            
            for issue in issues:
                current_issue_ids.add(issue.number)
                
                # 检查是否是新任务
                if issue.number not in self._known_issues:
                    if issue.is_pending:
                        print(f"[Watcher] New pending task detected: #{issue.number} - {issue.title}")
                        if self.on_new_task:
                            self.on_new_task(issue)
                else:
                    # 检查状态变化
                    old_issue = self._known_issues[issue.number]
                    if old_issue.status_label != issue.status_label:
                        print(f"[Watcher] Status changed for #{issue.number}: {old_issue.status_label} -> {issue.status_label}")
                        
                        # 检测取消（从 pending/running 变为 failed）
                        if issue.is_failed and (old_issue.is_pending or old_issue.is_running):
                            if self.on_task_cancelled:
                                self.on_task_cancelled(issue)
                
                # 更新已知 issues
                self._known_issues[issue.number] = issue
            
            # 清理已关闭的 issues
            closed_ids = set(self._known_issues.keys()) - current_issue_ids
            for issue_id in closed_ids:
                del self._known_issues[issue_id]
        
        self._last_check_time = datetime.now()
    
    def _fetch_issues_with_status(self) -> List[GHIssue]:
        """获取带状态标签的 Issues"""
        all_issues = []
        
        # 分别获取各种状态的 issues
        for status in ['pending', 'running', 'completed', 'failed']:
            try:
                issues = github_client.list_issues(
                    self.repo,
                    state='open',
                    labels=f'status:{status}'
                )
                all_issues.extend(issues)
            except GitHubClientError as e:
                print(f"[Watcher] Failed to fetch {status} issues: {e}")
        
        return all_issues
    
    def get_stats(self) -> Dict:
        """获取监听统计"""
        with self._lock:
            stats = {
                'pending': sum(1 for i in self._known_issues.values() if i.is_pending),
                'running': sum(1 for i in self._known_issues.values() if i.is_running),
                'completed': sum(1 for i in self._known_issues.values() if i.is_completed),
                'failed': sum(1 for i in self._known_issues.values() if i.is_failed),
                'total': len(self._known_issues),
                'last_check': self._last_check_time.isoformat() if self._last_check_time else None
            }
        return stats
    
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running


class MultiRepoWatcher:
    """多仓库监听器"""
    
    def __init__(self, poll_interval: int = 60):
        self.poll_interval = poll_interval
        self.watchers: Dict[str, IssueWatcher] = {}
        self._on_new_task: Optional[Callable[[str, GHIssue], None]] = None
    
    def set_callback(self, callback: Callable[[str, GHIssue], None]) -> None:
        """设置新任务回调"""
        self._on_new_task = callback
    
    def add_repo(self, repo: str) -> None:
        """添加监听仓库"""
        if repo in self.watchers:
            return
        
        def on_task(issue: GHIssue):
            if self._on_new_task:
                self._on_new_task(repo, issue)
        
        watcher = IssueWatcher(
            repo=repo,
            poll_interval=self.poll_interval,
            on_new_task=on_task
        )
        self.watchers[repo] = watcher
        watcher.start()
    
    def remove_repo(self, repo: str) -> None:
        """移除监听仓库"""
        if repo in self.watchers:
            self.watchers[repo].stop()
            del self.watchers[repo]
    
    def stop_all(self) -> None:
        """停止所有监听"""
        for watcher in self.watchers.values():
            watcher.stop()
        self.watchers.clear()
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """获取所有仓库统计"""
        return {repo: watcher.get_stats() for repo, watcher in self.watchers.items()}


if __name__ == '__main__':
    # 测试监听器
    import sys
    
    def on_new_task(issue: GHIssue):
        print(f"\n>>> New task: #{issue.number} - {issue.title}")
        print(f">>> Body: {issue.body[:200]}...")
    
    # 使用 claude-dashboard 测试
    watcher = IssueWatcher(
        repo='claude-dashboard',
        poll_interval=10,
        on_new_task=on_new_task
    )
    
    print("Starting watcher... Press Ctrl+C to stop")
    watcher.start()
    
    try:
        while True:
            time.sleep(5)
            stats = watcher.get_stats()
            print(f"\rStats: {stats['pending']} pending, {stats['running']} running, {stats['completed']} completed", end='')
    except KeyboardInterrupt:
        print("\nStopping...")
        watcher.stop()
