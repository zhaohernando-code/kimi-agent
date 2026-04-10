"""
数据模型定义
使用 SQLAlchemy ORM
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List

from sqlalchemy import create_engine, ForeignKey, Index, Enum
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column, Session

from config import config

Base = declarative_base()


class TaskStatus(str, PyEnum):
    """任务状态枚举"""
    PENDING = "pending"           # 待执行
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消


class TaskType(str, PyEnum):
    """任务类型枚举"""
    FEATURE = "feature"           # 新功能
    FIX = "fix"                   # Bug 修复
    REFACTOR = "refactor"         # 重构
    DOCS = "docs"                 # 文档
    TEST = "test"                 # 测试
    OTHER = "other"               # 其他


class LogType(str, PyEnum):
    """日志类型枚举"""
    STDOUT = "stdout"             # 标准输出
    STDERR = "stderr"             # 标准错误
    SYSTEM = "system"             # 系统日志


class Project(Base):
    """项目表 - 对应 GitHub 仓库"""
    __tablename__ = "projects"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    name: Mapped[str] = mapped_column(nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(nullable=False)
    local_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "repo_url": self.repo_url,
            "local_path": self.local_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "task_count": len(self.tasks) if self.tasks else 0
        }


class Task(Base):
    """任务表"""
    __tablename__ = "tasks"
    
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4())[:8])
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    parent_task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False, default=TaskType.FEATURE)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING, index=True)
    branch_name: Mapped[Optional[str]] = mapped_column(nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    # 关系
    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    parent_task: Mapped[Optional["Task"]] = relationship("Task", remote_side="Task.id", back_populates="sub_tasks")
    sub_tasks: Mapped[List["Task"]] = relationship("Task", back_populates="parent_task")
    logs: Mapped[List["TaskLog"]] = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "parent_task_id": self.parent_task_id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "sub_task_count": len(self.sub_tasks) if self.sub_tasks else 0
        }


class TaskLog(Base):
    """任务日志表 - 流式输出"""
    __tablename__ = "task_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    log_type: Mapped[LogType] = mapped_column(Enum(LogType), nullable=False, default=LogType.STDOUT)
    content: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    
    # 关系
    task: Mapped["Task"] = relationship("Task", back_populates="logs")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "log_type": self.log_type.value,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# 创建数据库引擎
def create_engine_instance():
    """创建数据库引擎"""
    return create_engine(config.database_url, echo=config.DEBUG)


def init_database():
    """初始化数据库，创建所有表"""
    engine = create_engine_instance()
    Base.metadata.create_all(engine)
    return engine


if __name__ == "__main__":
    # 测试：初始化数据库
    print(f"Initializing database at: {config.DATABASE_PATH}")
    engine = init_database()
    print("Database initialized successfully!")
