"""
任务管理器
负责任务的生命周期管理、并发控制和状态流转
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass

from config import config
from database import db
from models import Task, TaskStatus, TaskType, LogType, Project
from git_manager import git_manager, GitManagerError
from kimi_runner import kimi_runner, TaskResult, ExecutionResult


@dataclass
class TaskStats:
    """任务统计"""
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0


class TaskManagerError(Exception):
    """任务管理器错误"""
    pass


class TaskManager:
    """任务管理器"""
    
    def __init__(self, max_concurrent: int = None):
        self.max_concurrent = max_concurrent or config.MAX_CONCURRENT_TASKS
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent + 1)
        self.running_futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._scheduler_thread = None
        
        # 启动调度线程
        self._start_scheduler()
    
    def _start_scheduler(self):
        """启动后台调度线程"""
        def scheduler_loop():
            while not self._shutdown:
                try:
                    self._schedule_pending_tasks()
                except Exception as e:
                    print(f"Scheduler error: {e}")
                time.sleep(2)  # 每 2 秒检查一次
        
        self._scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self._scheduler_thread.start()
    
    def _schedule_pending_tasks(self):
        """调度待处理任务"""
        with self._lock:
            current_running = len(self.running_futures)
            available_slots = self.max_concurrent - current_running
            
            if available_slots <= 0:
                return
        
        # 获取待处理任务
        pending_tasks = db.get_pending_tasks(limit=available_slots)
        
        for task in pending_tasks:
            self._start_task(task)
    
    def _start_task(self, task: Task):
        """启动单个任务"""
        with self._lock:
            if task.id in self.running_futures:
                return  # 已经在运行
            
            # 提交到线程池
            future = self.executor.submit(self._execute_task, task)
            self.running_futures[task.id] = future
            
            # 添加完成回调
            future.add_done_callback(lambda f, tid=task.id: self._on_task_complete(tid, f))
        
        # 更新状态为运行中
        db.update_task_status(task.id, TaskStatus.RUNNING)
    
    def _execute_task(self, task: Task):
        """执行任务的核心逻辑"""
        task_id = task.id
        
        try:
            # 1. 获取项目信息
            project = db.get_project(task.project_id)
            if not project:
                raise TaskManagerError(f"Project {task.project_id} not found")
            
            db.add_task_log(task_id, f"Starting task: {task.title}", LogType.SYSTEM)
            db.add_task_log(task_id, f"Project: {project.name} ({project.repo_url})", LogType.SYSTEM)
            
            # 2. 克隆/拉取仓库
            db.add_task_log(task_id, "Cloning/Pulling repository...", LogType.SYSTEM)
            try:
                repo = git_manager.clone_or_pull(project.name, project.repo_url)
                db.add_task_log(task_id, f"Repository ready at: {repo.working_dir}", LogType.SYSTEM)
            except GitManagerError as e:
                raise TaskManagerError(f"Git operation failed: {e}")
            
            # 3. 创建任务分支
            db.add_task_log(task_id, "Creating task branch...", LogType.SYSTEM)
            try:
                parent_branch = None
                if task.parent_task_id:
                    parent_task = db.get_task(task.parent_task_id)
                    if parent_task and parent_task.branch_name:
                        parent_branch = parent_task.branch_name
                
                branch_name = git_manager.create_task_branch(project.name, task_id, parent_branch)
                db.set_task_branch(task_id, branch_name)
                db.add_task_log(task_id, f"Created branch: {branch_name}", LogType.SYSTEM)
            except GitManagerError as e:
                raise TaskManagerError(f"Failed to create branch: {e}")
            
            # 4. 执行 Kimi 任务
            db.add_task_log(task_id, "Starting Kimi task execution...", LogType.SYSTEM)
            db.add_task_log(task_id, "=" * 50, LogType.SYSTEM)
            
            result = kimi_runner.run_task(
                task_id=task_id,
                task_title=task.title,
                task_description=task.description,
                working_dir=repo.working_dir
            )
            
            db.add_task_log(task_id, "=" * 50, LogType.SYSTEM)
            db.add_task_log(task_id, f"Task execution completed in {result.duration_seconds:.1f}s", LogType.SYSTEM)
            
            # 5. 处理结果
            if result.result == TaskResult.SUCCESS:
                # 提交更改
                try:
                    db.add_task_log(task_id, "Committing changes...", LogType.SYSTEM)
                    commit_sha = git_manager.commit_and_push(
                        project.name,
                        f"Complete task: {task.title}",
                        task_id
                    )
                    db.update_task_status(
                        task_id=task_id,
                        status=TaskStatus.COMPLETED,
                        commit_sha=commit_sha,
                        result_summary=f"Completed in {result.duration_seconds:.1f}s, {result.lines_processed} lines output"
                    )
                    db.add_task_log(task_id, f"Changes committed: {commit_sha[:8]}", LogType.SYSTEM)
                except GitManagerError as e:
                    db.update_task_status(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error_message=f"Git commit/push failed: {e}"
                    )
            
            elif result.result == TaskResult.CANCELLED:
                db.update_task_status(task_id, TaskStatus.CANCELLED)
                # 清理分支
                try:
                    git_manager.cleanup_task_branch(project.name, task_id)
                except:
                    pass
            
            else:  # FAILED or TIMEOUT
                db.update_task_status(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error_message=result.error_message or f"Task failed with code {result.return_code}"
                )
        
        except TaskManagerError as e:
            error_msg = str(e)
            db.add_task_log(task_id, f"Task error: {error_msg}", LogType.SYSTEM)
            db.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error_message=error_msg
            )
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            db.add_task_log(task_id, error_msg, LogType.SYSTEM)
            db.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error_message=error_msg
            )
    
    def _on_task_complete(self, task_id: str, future: Future):
        """任务完成回调"""
        with self._lock:
            if task_id in self.running_futures:
                del self.running_futures[task_id]
        
        # 检查是否有异常
        try:
            future.result()
        except Exception as e:
            print(f"Task {task_id} raised exception: {e}")
    
    def submit_task(
        self,
        project_id: str,
        title: str,
        task_type: TaskType = TaskType.FEATURE,
        description: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Task:
        """
        提交新任务
        
        Args:
            project_id: 项目 ID
            title: 任务标题
            task_type: 任务类型
            description: 任务描述
            parent_task_id: 父任务 ID（可选）
        
        Returns:
            创建的 Task 对象
        """
        # 验证项目存在
        project = db.get_project(project_id)
        if not project:
            raise TaskManagerError(f"Project {project_id} not found")
        
        # 验证父任务存在（如果指定）
        if parent_task_id:
            parent = db.get_task(parent_task_id)
            if not parent:
                raise TaskManagerError(f"Parent task {parent_task_id} not found")
            if parent.project_id != project_id:
                raise TaskManagerError("Parent task must belong to the same project")
        
        # 创建任务
        task = db.create_task(
            project_id=project_id,
            title=title,
            task_type=task_type,
            description=description,
            parent_task_id=parent_task_id
        )
        
        # 立即尝试调度
        self._schedule_pending_tasks()
        
        return task
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Returns:
            是否成功取消
        """
        task = db.get_task(task_id)
        if not task:
            return False
        
        if task.status == TaskStatus.PENDING:
            # 待处理任务直接取消
            db.update_task_status(task_id, TaskStatus.CANCELLED)
            return True
        
        if task.status == TaskStatus.RUNNING:
            # 运行中任务需要中断
            if kimi_runner.cancel_task(task_id):
                # 回调会更新状态
                return True
        
        return False
    
    def get_task_status(self, task_id: str) -> Optional[Task]:
        """获取任务状态"""
        return db.get_task(task_id)
    
    def get_stats(self) -> TaskStats:
        """获取任务统计"""
        stats = TaskStats()
        
        # 简单统计各种状态的任务数量
        for status in TaskStatus:
            tasks = db.list_tasks(status=status, limit=10000)
            count = len(tasks)
            if status == TaskStatus.PENDING:
                stats.pending = count
            elif status == TaskStatus.RUNNING:
                stats.running = count
            elif status == TaskStatus.COMPLETED:
                stats.completed = count
            elif status == TaskStatus.FAILED:
                stats.failed = count
            elif status == TaskStatus.CANCELLED:
                stats.cancelled = count
        
        stats.total = stats.pending + stats.running + stats.completed + stats.failed + stats.cancelled
        return stats
    
    def get_running_tasks(self) -> List[str]:
        """获取正在运行的任务 ID 列表"""
        with self._lock:
            return list(self.running_futures.keys())
    
    def shutdown(self):
        """关闭任务管理器"""
        self._shutdown = True
        
        # 取消所有运行中的任务
        with self._lock:
            for task_id in list(self.running_futures.keys()):
                self.cancel_task(task_id)
        
        # 关闭线程池
        self.executor.shutdown(wait=True)


# 全局任务管理器实例
task_manager = TaskManager()


if __name__ == "__main__":
    print("TaskManager initialized")
    print(f"Max concurrent tasks: {task_manager.max_concurrent}")
