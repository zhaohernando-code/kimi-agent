"""
Kimi CLI 任务执行模块
封装 Kimi CLI 调用，提供流式输出和日志记录
"""
import os
import subprocess
import threading
import time
from typing import Iterator, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from config import config
from enum import Enum


class LogType(Enum):
    """日志类型"""
    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"


class TaskResult(Enum):
    """任务执行结果"""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """执行结果"""
    result: TaskResult
    return_code: int
    duration_seconds: float
    lines_processed: int
    error_message: Optional[str] = None


class KimiRunnerError(Exception):
    """Kimi 运行错误"""
    pass


class KimiRunner:
    """Kimi CLI 运行器"""
    
    def __init__(self):
        self.running_processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
    
    def _build_prompt(self, task_title: str, task_description: Optional[str], working_dir: str) -> str:
        """
        构建 Kimi 提示词
        
        提示词结构：
        1. 系统角色定义
        2. 任务目标
        3. 工作目录
        4. 约束条件
        5. 输出要求
        """
        prompt = f"""## 角色
你是一个自动化开发助手，正在执行一个编程任务。

## 任务
标题: {task_title}
"""
        if task_description:
            prompt += f"\n描述:\n{task_description}\n"
        
        prompt += f"""
## 工作目录
{working_dir}

## 约束条件
1. 所有代码和文件修改必须在指定的工作目录内进行
2. 使用 --yolo 模式运行，不会停止索要确认
3. 完成后必须提交所有更改到 Git
4. 如果任务无法完成，记录详细错误信息
5. 遵循项目的编码规范和目录结构

## 执行步骤
1. 首先查看工作目录结构和现有代码
2. 理解任务需求
3. 实现功能或修复问题
4. 编写/更新测试（如果有）
5. 运行测试验证（如果有）
6. 提交更改到 Git

## 输出要求
1. 简明扼要地描述你做了什么
2. 列出修改的文件
3. 说明测试结果（如果有）

请开始执行任务。
"""
        return prompt
    
    def run_task(
        self,
        task_id: str,
        task_title: str,
        task_description: Optional[str],
        working_dir: str,
        on_log: Optional[Callable[[str, LogType], None]] = None
    ) -> ExecutionResult:
        """
        运行 Kimi 任务
        
        Args:
            task_id: 任务 ID
            task_title: 任务标题
            task_description: 任务描述
            working_dir: 工作目录
            on_log: 日志回调函数 (content, log_type) -> None
        
        Returns:
            ExecutionResult 执行结果
        """
        start_time = time.time()
        lines_processed = 0
        
        # 构建提示词
        prompt = self._build_prompt(task_title, task_description, working_dir)
        
        # 构建命令
        # 使用 subprocess 直接调用 kimi 命令
        cmd = ["kimi", "--yolo"]  # --yolo 模式全自动
        
        # 设置环境变量
        env = config.get_env_with_proxy()
        env["KIMI_NO_INTERACTIVE"] = "1"
        
        try:
            # 启动进程
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # 行缓冲
                cwd=working_dir,
                env=env
            )
            
            with self._lock:
                self.running_processes[task_id] = process
            
            # 发送提示词
            if process.stdin:
                process.stdin.write(prompt)
                process.stdin.close()
            
            # 读取输出
            if process.stdout:
                for line in process.stdout:
                    lines_processed += 1
                    line = line.rstrip('\n')
                    
                    # 判断日志类型
                    log_type = LogType.STDOUT
                    if "error" in line.lower() or "failed" in line.lower():
                        log_type = LogType.STDERR
                    elif line.startswith("[") or line.startswith("*"):
                        log_type = LogType.SYSTEM
                    
                    # 调用回调传递日志
                    if on_log:
                        on_log(line, log_type)
            
            # 等待进程结束
            try:
                return_code = process.wait(timeout=config.KIMI_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = -1
                # 超时处理
                return ExecutionResult(
                    result=TaskResult.TIMEOUT,
                    return_code=-1,
                    duration_seconds=time.time() - start_time,
                    lines_processed=lines_processed,
                    error_message="Task execution timeout"
                )
            
            duration = time.time() - start_time
            
            # 判断结果
            if return_code == 0:
                result = TaskResult.SUCCESS
                # 成功完成
            else:
                result = TaskResult.FAILED
                error_msg = f"Task failed with return code {return_code}"
                # 记录失败
            
            return ExecutionResult(
                result=result,
                return_code=return_code,
                duration_seconds=duration,
                lines_processed=lines_processed,
                error_message=None if result == TaskResult.SUCCESS else f"Exit code: {return_code}"
            )
        
        except Exception as e:
            error_msg = str(e)
            # 记录执行错误
            return ExecutionResult(
                result=TaskResult.FAILED,
                return_code=-1,
                duration_seconds=time.time() - start_time,
                lines_processed=lines_processed,
                error_message=error_msg
            )
        
        finally:
            with self._lock:
                if task_id in self.running_processes:
                    del self.running_processes[task_id]
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消正在运行的任务
        
        Returns:
            是否成功取消
        """
        with self._lock:
            process = self.running_processes.get(task_id)
        
        if process and process.poll() is None:
            try:
                process.terminate()
                # 等待最多 5 秒
                process.wait(timeout=5)
                # 任务已取消
                return True
            except subprocess.TimeoutExpired:
                process.kill()
                # 任务被强制终止
                return True
            except Exception as e:
                # 取消任务出错
                return False
        
        return False
    
    def stream_logs(self, task_id: str, last_id: int = 0) -> Iterator[dict]:
        """
        流式获取任务日志 (已弃用 - 使用 Issue 评论替代)
        """
        return
        yield


# 全局 KimiRunner 实例
kimi_runner = KimiRunner()


if __name__ == "__main__":
    print("KimiRunner test")
    print(f"Workspace root: {config.WORKSPACE_ROOT}")
    print(f"Kimi timeout: {config.KIMI_TIMEOUT}s")
    print(f"Max concurrent tasks: {config.MAX_CONCURRENT_TASKS}")
