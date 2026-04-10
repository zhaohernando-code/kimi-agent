"""
Kimi Agent 主入口
GitHub Issues 驱动的任务执行代理
"""
import os
import sys
import time
import signal
from typing import Dict, Set
from dataclasses import dataclass

from config import config
from github_client import github_client, GHIssue, GitHubClientError
from issue_watcher import MultiRepoWatcher
from task_executor import TaskExecutor


@dataclass
class AgentStats:
    """Agent 统计"""
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    start_time: float = 0
    
    @property
    def uptime(self) -> float:
        return time.time() - self.start_time


class KimiAgent:
    """
    Kimi Agent
    
    核心功能：
    1. 监听多个仓库的 Issues
    2. 执行 pending 任务
    3. 管理并发（最多 3 个同时执行）
    4. 报告状态
    """
    
    def __init__(self):
        self.watcher = MultiRepoWatcher(poll_interval=60)
        self.running_executors: Dict[int, TaskExecutor] = {}
        self.stats = AgentStats()
        self._shutdown = False
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理退出信号"""
        print(f"\n[Agent] Received signal {signum}, shutting down...")
        self._shutdown = True
    
    def add_repo(self, repo: str) -> None:
        """添加监听仓库"""
        print(f"[Agent] Adding repo: {repo}")
        self.watcher.add_repo(repo)
    
    def start(self) -> None:
        """启动 Agent"""
        print("=" * 60)
        print("  🤖 Kimi Agent - GitHub Issues 驱动")
        print("=" * 60)
        print(f"\n配置信息:")
        print(f"  GitHub 用户: {config.GITHUB_USERNAME}")
        print(f"  最大并发: {config.MAX_CONCURRENT_TASKS}")
        print(f"  轮询间隔: 60 秒")
        print(f"\n监听仓库:")
        for repo in self.watcher.watchers.keys():
            print(f"  - {repo}")
        print(f"\n按 Ctrl+C 停止\n")
        
        self.stats.start_time = time.time()
        
        # 设置新任务回调
        self.watcher.set_callback(self._on_new_task)
        
        # 启动时检查所有 pending 任务
        self._check_pending_on_startup()
        
        # 主循环
        try:
            while not self._shutdown:
                self._main_loop()
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    def stop(self) -> None:
        """停止 Agent"""
        print("\n[Agent] Stopping...")
        
        # 停止所有 watcher
        self.watcher.stop_all()
        
        # 停止所有执行中的任务
        for executor in self.running_executors.values():
            executor.stop()
        
        # 打印统计
        print("\n执行统计:")
        print(f"  总任务: {self.stats.tasks_executed}")
        print(f"  成功: {self.stats.tasks_succeeded}")
        print(f"  失败: {self.stats.tasks_failed}")
        print(f"  运行时间: {self.stats.uptime:.0f} 秒")
        
        print("\n[Agent] Stopped")
    
    def _main_loop(self) -> None:
        """主循环"""
        # 清理已完成的任务
        self._cleanup_finished_tasks()
        
        # 打印状态（每分钟）
        if int(time.time()) % 60 == 0:
            self._print_status()
    
    def _on_new_task(self, repo: str, issue: GHIssue) -> None:
        """新任务回调"""
        # 检查是否已在执行
        if issue.number in self.running_executors:
            return
        
        # 检查并发限制
        if len(self.running_executors) >= config.MAX_CONCURRENT_TASKS:
            print(f"[Agent] Concurrent limit reached, delaying task #{issue.number}")
            return
        
        print(f"\n[Agent] New task: #{issue.number} - {issue.title}")
        print(f"[Agent] Starting execution...")
        
        # 创建执行器
        executor = TaskExecutor(repo, issue)
        self.running_executors[issue.number] = executor
        
        # 在后台线程执行
        import threading
        thread = threading.Thread(target=self._execute_task, args=(repo, issue.number, executor))
        thread.daemon = True
        thread.start()
    
    def _execute_task(self, repo: str, issue_number: int, executor: TaskExecutor) -> None:
        """执行任务"""
        try:
            success = executor.execute()
            
            self.stats.tasks_executed += 1
            if success:
                self.stats.tasks_succeeded += 1
                print(f"[Agent] Task #{issue_number} completed successfully")
            else:
                self.stats.tasks_failed += 1
                print(f"[Agent] Task #{issue_number} failed")
        
        except Exception as e:
            print(f"[Agent] Task #{issue_number} error: {e}")
            self.stats.tasks_failed += 1
        
        finally:
            # 从运行列表移除
            if issue_number in self.running_executors:
                del self.running_executors[issue_number]
    
    def _cleanup_finished_tasks(self) -> None:
        """清理已完成的任务"""
        # 执行器会在完成后自动从字典移除
        pass
    
    def _check_pending_on_startup(self) -> None:
        """启动时检查所有 pending 任务"""
        print("[Agent] Checking pending tasks on startup...")
        
        for repo in self.watcher.watchers.keys():
            try:
                issues = github_client.get_pending_issues(repo)
                print(f"  {repo}: {len(issues)} pending tasks")
                
                for issue in issues:
                    # 模拟新任务事件
                    self._on_new_task(repo, issue)
            
            except GitHubClientError as e:
                print(f"  Error checking {repo}: {e}")
    
    def _print_status(self) -> None:
        """打印状态"""
        stats = self.watcher.get_all_stats()
        total_pending = sum(s['pending'] for s in stats.values())
        total_running = sum(s['running'] for s in stats.values())
        
        local_running = len(self.running_executors)
        uptime = self.stats.uptime
        
        print(f"[{time.strftime('%H:%M:%S')}] "
              f"Agent: {uptime/60:.0f}m up | "
              f"Pending: {total_pending} | "
              f"Running: {local_running}/{config.MAX_CONCURRENT_TASKS} | "
              f"Executed: {self.stats.tasks_executed}")


def main():
    """主函数"""
    # 检查环境变量
    if not config.GITHUB_TOKEN:
        print("错误: 未设置 GITHUB_TOKEN")
        print("请执行: export GITHUB_TOKEN=ghp_xxx")
        sys.exit(1)
    
    if not config.GITHUB_USERNAME:
        print("错误: 未设置 GITHUB_USERNAME")
        print("请执行: export GITHUB_USERNAME=your-username")
        sys.exit(1)
    
    # 创建 Agent
    agent = KimiAgent()
    
    # 添加默认仓库
    default_repos = ['claude-dashboard']
    
    # 也可以从命令行参数添加
    if len(sys.argv) > 1:
        default_repos = sys.argv[1:]
    
    for repo in default_repos:
        agent.add_repo(repo)
    
    # 启动
    agent.start()


if __name__ == '__main__':
    main()
