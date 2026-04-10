"""
数据库操作封装
提供高层次的 CRUD 操作
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Generator

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine, desc

from config import config
from models import (
    Base, Project, Task, TaskLog,
    TaskStatus, TaskType, LogType,
    create_engine_instance, init_database
)


class Database:
    """数据库操作类"""
    
    def __init__(self):
        self.engine = create_engine_instance()
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """提供事务范围的 session 上下文管理器"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    # ========== 项目操作 ==========
    
    def create_project(self, name: str, repo_url: str, local_path: Optional[str] = None) -> Project:
        """创建项目"""
        with self.session_scope() as session:
            project = Project(name=name, repo_url=repo_url, local_path=local_path)
            session.add(project)
            session.flush()  # 获取生成的 ID
            # 刷新以保持对象在 session 中
            session.refresh(project)
            #  detached 对象才能返回
            session.expunge(project)
            return project
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目详情"""
        with self.session_scope() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                session.expunge(project)
            return project
    
    def list_projects(self, limit: int = 100, offset: int = 0) -> List[Project]:
        """列出所有项目"""
        with self.session_scope() as session:
            projects = session.query(Project).order_by(desc(Project.created_at)).offset(offset).limit(limit).all()
            for p in projects:
                session.expunge(p)
            return projects
    
    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        with self.session_scope() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                session.delete(project)
                return True
            return False
    
    def update_project(self, project_id: str, **kwargs) -> Optional[Project]:
        """更新项目信息"""
        with self.session_scope() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                for key, value in kwargs.items():
                    if hasattr(project, key):
                        setattr(project, key, value)
                project.updated_at = datetime.utcnow()
                session.refresh(project)
                session.expunge(project)
            return project
    
    # ========== 任务操作 ==========
    
    def create_task(
        self,
        project_id: str,
        title: str,
        task_type: TaskType = TaskType.FEATURE,
        description: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Task:
        """创建任务"""
        with self.session_scope() as session:
            task = Task(
                project_id=project_id,
                title=title,
                type=task_type,
                description=description,
                parent_task_id=parent_task_id,
                status=TaskStatus.PENDING
            )
            session.add(task)
            session.flush()
            session.refresh(task)
            session.expunge(task)
            return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务详情"""
        with self.session_scope() as session:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                session.expunge(task)
            return task
    
    def list_tasks(
        self,
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Task]:
        """列出任务"""
        with self.session_scope() as session:
            query = session.query(Task)
            if project_id:
                query = query.filter(Task.project_id == project_id)
            if status:
                query = query.filter(Task.status == status)
            tasks = query.order_by(desc(Task.created_at)).offset(offset).limit(limit).all()
            for t in tasks:
                session.expunge(t)
            return tasks
    
    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        commit_sha: Optional[str] = None,
        error_message: Optional[str] = None,
        result_summary: Optional[str] = None
    ) -> Optional[Task]:
        """更新任务状态"""
        with self.session_scope() as session:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = status
                if status == TaskStatus.RUNNING and not task.started_at:
                    task.started_at = datetime.utcnow()
                if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    task.completed_at = datetime.utcnow()
                if commit_sha:
                    task.commit_sha = commit_sha
                if error_message:
                    task.error_message = error_message
                if result_summary:
                    task.result_summary = result_summary
                session.refresh(task)
                session.expunge(task)
            return task
    
    def set_task_branch(self, task_id: str, branch_name: str) -> Optional[Task]:
        """设置任务分支名"""
        with self.session_scope() as session:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.branch_name = branch_name
                session.refresh(task)
                session.expunge(task)
            return task
    
    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """获取待执行的任务"""
        return self.list_tasks(status=TaskStatus.PENDING, limit=limit)
    
    def get_running_tasks(self) -> List[Task]:
        """获取正在执行的任务"""
        return self.list_tasks(status=TaskStatus.RUNNING)
    
    # ========== 任务日志操作 ==========
    
    def add_task_log(self, task_id: str, content: str, log_type: LogType = LogType.STDOUT) -> TaskLog:
        """添加任务日志"""
        with self.session_scope() as session:
            log = TaskLog(task_id=task_id, content=content, log_type=log_type)
            session.add(log)
            session.flush()
            session.refresh(log)
            session.expunge(log)
            return log
    
    def get_task_logs(self, task_id: str, limit: int = 1000, offset: int = 0) -> List[TaskLog]:
        """获取任务日志"""
        with self.session_scope() as session:
            logs = session.query(TaskLog).filter(
                TaskLog.task_id == task_id
            ).order_by(TaskLog.created_at).offset(offset).limit(limit).all()
            for log in logs:
                session.expunge(log)
            return logs
    
    def get_task_tree(self, project_id: str) -> List[Task]:
        """获取项目的任务树（仅顶级任务）"""
        with self.session_scope() as session:
            tasks = session.query(Task).filter(
                Task.project_id == project_id,
                Task.parent_task_id == None
            ).order_by(desc(Task.created_at)).all()
            for t in tasks:
                session.expunge(t)
            return tasks


# 全局数据库实例
db = Database()


if __name__ == "__main__":
    # 测试数据库操作
    init_database()
    
    # 创建测试项目
    project = db.create_project("test-project", "https://github.com/test/repo.git")
    print(f"Created project: {project.to_dict()}")
    
    # 创建测试任务
    task = db.create_task(project.id, "Test Task", TaskType.FEATURE, "This is a test task")
    print(f"Created task: {task.to_dict()}")
    
    # 更新任务状态
    db.update_task_status(task.id, TaskStatus.RUNNING)
    task = db.get_task(task.id)
    print(f"Updated task: {task.to_dict()}")
    
    # 添加日志
    log = db.add_task_log(task.id, "Starting task execution...")
    print(f"Added log: {log.to_dict()}")
    
    print("\nAll tests passed!")
