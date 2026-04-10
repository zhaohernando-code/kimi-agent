"""
任务执行器
协调任务执行流程：检测 Issue → 执行 Kimi → 更新结果
"""
import os
import re
import time
import threading
from typing import Optional, Dict
from datetime import datetime

from github_client import github_client, GHIssue, GitHubClientError
from git_manager import git_manager, GitManagerError
from kimi_runner import kimi_runner, TaskResult


class TaskExecutorError(Exception):
    """任务执行错误"""
    pass


class TaskExecutor:
    """
    任务执行器
    
    负责：
    1. 执行单个 Issue 任务
    2. 管理执行状态（running/completed/failed）
    3. 更新 Issue 评论作为日志
    4. 处理 Git 操作
    """
    
    def __init__(self, repo: str, issue: GHIssue):
        self.repo = repo
        self.issue = issue
        self.issue_number = issue.number
        self.task_id = f"issue-{issue.number}"
        
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.branch_name: Optional[str] = None
        self.commit_sha: Optional[str] = None
        
        self._stopped = False
    
    def execute(self) -> bool:
        """
        执行任务
        
        Returns:
            是否成功
        """
        self.start_time = datetime.now()
        
        try:
            # 1. 更新状态为 running
            self._update_status('running', f"开始执行任务...\n\n**任务**: {self.issue.title}\n**时间**: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 2. 解析任务元数据
            metadata = self._parse_metadata(self.issue.body)
            is_frontend_task = metadata.get('type') == 'frontend-update'
            target_repo = metadata.get('target', self.repo)
            
            self._log(f"任务类型: {'前端更新' if is_frontend_task else '普通开发'}")
            self._log(f"目标仓库: {target_repo}")
            
            # 3. 克隆/更新仓库
            self._log(f"准备仓库 {target_repo}...")
            repo_url = f"https://github.com/{github_client.username}/{target_repo}.git"
            try:
                git_manager.clone_or_pull(target_repo, repo_url)
                self._log(f"仓库准备完成")
            except GitManagerError as e:
                raise TaskExecutorError(f"Git 操作失败: {e}")
            
            # 4. 创建任务分支
            self.branch_name = f"task/issue-{self.issue_number}"
            try:
                git_manager.create_task_branch(target_repo, self.task_id)
                self._log(f"创建分支: {self.branch_name}")
            except GitManagerError as e:
                raise TaskExecutorError(f"创建分支失败: {e}")
            
            # 5. 构建 Kimi 提示词
            prompt = self._build_prompt(self.issue.title, self.issue.body, is_frontend_task, target_repo)
            
            # 6. 执行 Kimi 任务
            self._log("启动 Kimi CLI 执行任务...")
            self._log("=" * 50)
            
            # 使用实时日志回调
            log_buffer = []
            last_log_time = time.time()
            
            def on_log(line: str, log_type):
                log_buffer.append(line)
                # 每 5 秒或积累 20 行发送一次
                nonlocal last_log_time
                if time.time() - last_log_time > 5 or len(log_buffer) >= 20:
                    self._flush_logs(log_buffer)
                    log_buffer.clear()
                    last_log_time = time.time()
            
            result = kimi_runner.run_task(
                task_id=self.task_id,
                task_title=self.issue.title,
                task_description=self.issue.body,
                working_dir=git_manager._get_repo_path(target_repo),
                on_log=on_log
            )
            
            # 刷新剩余日志
            if log_buffer:
                self._flush_logs(log_buffer)
            
            self._log("=" * 50)
            self._log(f"Kimi 执行完成，结果: {result.result.value}")
            
            # 7. 处理结果
            if result.result == TaskResult.SUCCESS:
                # 提交更改
                try:
                    self._log("提交更改...")
                    commit_msg = f"[{self.task_id}] {self.issue.title}"
                    self.commit_sha = git_manager.commit_and_push(target_repo, commit_msg, self.task_id)
                    self._log(f"提交成功: {self.commit_sha[:8]}")
                    
                    # 如果是前端任务，合并到 main 触发部署
                    if is_frontend_task:
                        self._log("前端任务，合并到 main 分支触发部署...")
                        self._merge_to_main(target_repo)
                    
                    # 更新状态为 completed
                    summary = self._build_summary(result, True)
                    self._update_status('completed', summary)
                    
                    # 添加用量统计
                    self._add_usage_comment(result)
                    
                    return True
                    
                except GitManagerError as e:
                    raise TaskExecutorError(f"提交失败: {e}")
            
            else:
                # 执行失败
                error_msg = result.error_message or f"退出码: {result.return_code}"
                summary = self._build_summary(result, False, error_msg)
                self._update_status('failed', summary)
                
                # 清理分支
                try:
                    git_manager.cleanup_task_branch(target_repo, self.task_id)
                except:
                    pass
                
                return False
        
        except TaskExecutorError as e:
            self._update_status('failed', f"任务执行失败: {e}")
            return False
        
        except Exception as e:
            self._update_status('failed', f"未知错误: {e}")
            return False
        
        finally:
            self.end_time = datetime.now()
    
    def stop(self) -> None:
        """停止任务"""
        self._stopped = True
        kimi_runner.cancel_task(self.task_id)
    
    def _parse_metadata(self, body: str) -> Dict[str, str]:
        """解析 Issue body 中的元数据"""
        metadata = {}
        if not body:
            return metadata
        
        # 查找元数据部分
        meta_match = re.search(r'## 元数据\s*\n(.*?)(?:\n##|$)', body, re.DOTALL)
        if meta_match:
            meta_section = meta_match.group(1)
            for line in meta_section.strip().split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    line = line[2:]
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
        
        return metadata
    
    def _load_kimi_md(self) -> str:
        """加载 KIMI.md 规范内容"""
        try:
            kimi_md_path = os.path.join(os.path.dirname(__file__), '..', 'KIMI.md')
            if os.path.exists(kimi_md_path):
                with open(kimi_md_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception:
            pass
        return ""
    
    def _build_prompt(self, title: str, body: str, is_frontend: bool, target_repo: str) -> str:
        """构建 Kimi 提示词"""
        # 动态加载 KIMI.md
        kimi_md_content = self._load_kimi_md()
        
        prompt = f"""## 角色
你是一个自动化开发助手，正在执行一个 GitHub Issue 任务。

## 任务信息
- Issue: #{self.issue_number}
- 标题: {title}
- 目标仓库: {target_repo}
{"- 类型: 前端更新（修改后需要可部署到 GitHub Pages）" if is_frontend else "- 类型: 普通开发任务"}

## 详细描述
{body or "(无详细描述)"}

## 工作目录
{git_manager._get_repo_path(target_repo)}

## KIMI.md 规范要求（必须遵守）
{kimi_md_content or "(请遵守项目规范，错误处理原则：遇到错误优先解决，不主动停止任务)"}

## 约束条件
1. 所有修改必须在指定工作目录内
2. 遵循现有代码风格和项目结构
3. 确保代码可正常运行
{"4. 修改完成后，代码应可直接部署到 GitHub Pages" if is_frontend else ""}
{"5. 如修改前端代码，确保 npm run build 能成功" if is_frontend else ""}

## 输出要求
1. 说明完成了什么修改
2. 列出修改的文件
3. 如有测试，说明测试结果

请开始执行任务。
"""
        return prompt
    
    def _update_status(self, status: str, comment: str) -> None:
        """更新 Issue 状态"""
        try:
            github_client.update_issue_status(self.repo, self.issue_number, status, comment)
        except GitHubClientError as e:
            print(f"[Executor] Failed to update status: {e}")
    
    def _log(self, message: str) -> None:
        """记录日志到 Issue"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        try:
            github_client.create_comment(
                self.repo,
                self.issue_number,
                f"`[{timestamp}]` {message}"
            )
        except GitHubClientError as e:
            print(f"[Executor] Failed to log: {e}")
    
    def _flush_logs(self, logs: list) -> None:
        """批量发送日志"""
        if not logs:
            return
        timestamp = datetime.now().strftime('%H:%M:%S')
        content = '\n'.join(logs)
        try:
            github_client.create_comment(
                self.repo,
                self.issue_number,
                f"`[{timestamp}]`\n```\n{content}\n```"
            )
        except GitHubClientError as e:
            print(f"[Executor] Failed to flush logs: {e}")
    
    def _build_summary(self, result, success: bool, error: str = None) -> str:
        """构建执行结果摘要"""
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        
        lines = [
            "## 执行结果",
            "",
            f"- **状态**: {'✅ 成功' if success else '❌ 失败'}",
            f"- **耗时**: {duration:.1f} 秒",
        ]
        
        if self.branch_name:
            lines.append(f"- **分支**: `{self.branch_name}`")
        
        if self.commit_sha:
            lines.append(f"- **Commit**: `{self.commit_sha[:8]}`")
        
        if error:
            lines.extend(["", f"- **错误**: {error}"])
        
        lines.extend([
            "",
            f"- **输出行数**: {result.lines_processed}",
        ])
        
        return '\n'.join(lines)
    
    def _add_usage_comment(self, result) -> None:
        """添加用量统计评论"""
        import json
        
        # 模拟用量数据（实际应从 Kimi CLI 获取）
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        
        # 估算用量（实际应用中应从 Kimi CLI 的输出解析）
        estimated_input = result.lines_processed * 100  # 粗略估算
        estimated_output = result.lines_processed * 50
        estimated_cost = (estimated_input + estimated_output) / 1000000 * 0.15  # $0.15 per 1M tokens
        
        usage_data = {
            "input_tokens": estimated_input,
            "output_tokens": estimated_output,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": round(estimated_cost, 6),
            "duration_ms": int(duration * 1000)
        }
        
        comment = f"""## 用量统计

```usage-json
{json.dumps(usage_data, indent=2)}
```

- **输入 Tokens**: {estimated_input:,}
- **输出 Tokens**: {estimated_output:,}
- **总费用**: ${estimated_cost:.6f}
- **执行时间**: {duration:.1f}秒
"""
        
        try:
            github_client.create_comment(self.repo, self.issue_number, comment)
        except GitHubClientError as e:
            print(f"[Executor] Failed to add usage comment: {e}")
    
    def _merge_to_main(self, repo: str) -> None:
        """合并分支到 main 触发部署"""
        try:
            import subprocess
            repo_path = git_manager._get_repo_path(repo)
            
            # 切换到 main
            subprocess.run(['git', 'checkout', 'main'], cwd=repo_path, check=True, capture_output=True)
            
            # 合并任务分支
            subprocess.run(['git', 'merge', self.branch_name, '--no-ff', '-m', f'Merge {self.task_id}'], 
                         cwd=repo_path, check=True, capture_output=True)
            
            # 推送
            subprocess.run(['git', 'push', 'origin', 'main'], cwd=repo_path, check=True, capture_output=True)
            
            self._log(f"已合并到 main 分支，GitHub Actions 将自动部署")
        
        except Exception as e:
            self._log(f"⚠️ 合并到 main 失败: {e}，请手动合并")


if __name__ == '__main__':
    # 测试执行器
    print("Testing Task Executor...")
    
    # 获取一个 pending issue
    issues = github_client.get_pending_issues('claude-dashboard')
    if not issues:
        print("No pending issues found")
    else:
        issue = issues[0]
        print(f"Executing issue #{issue.number}: {issue.title}")
        
        executor = TaskExecutor('claude-dashboard', issue)
        success = executor.execute()
        print(f"Execution {'succeeded' if success else 'failed'}")
