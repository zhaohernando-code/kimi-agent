"""
Kimi Agent 配置管理
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """应用配置类"""
    
    # 认证配置
    API_KEY: str = field(default_factory=lambda: os.getenv("KIMI_AGENT_KEY", "change-me-in-production"))
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = field(default_factory=lambda: int(os.getenv("KIMI_AGENT_PORT", "8000")))
    DEBUG: bool = field(default_factory=lambda: os.getenv("KIMI_AGENT_DEBUG", "false").lower() == "true")
    
    # 数据库配置
    DATABASE_PATH: str = field(default_factory=lambda: os.path.expanduser("~/kimi/data/tasks.db"))
    
    # GitHub 配置
    GITHUB_TOKEN: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    GITHUB_USERNAME: str = field(default_factory=lambda: os.getenv("GITHUB_USERNAME", "zhaohernando-code"))
    
    # 代理配置
    PROXY_HOST: str = "168.158.103.246"
    PROXY_PORT: int = 12323
    PROXY_USER: str = "14ad864674363"
    PROXY_PASS: str = "7559d165cd"
    
    # Kimi CLI 配置
    KIMI_TIMEOUT: int = 3600  # 任务超时时间(秒)
    MAX_CONCURRENT_TASKS: int = 3
    
    # Issue Watcher 配置
    POLL_INTERVAL: int = 60  # 轮询间隔(秒)
    
    # 工作目录配置
    WORKSPACE_ROOT: str = field(default_factory=lambda: os.path.expanduser("~/kimi/workspace"))
    
    @property
    def proxy_url(self) -> str:
        """生成代理 URL"""
        return f"http://{self.PROXY_USER}:{self.PROXY_PASS}@{self.PROXY_HOST}:{self.PROXY_PORT}"
    
    @property
    def database_url(self) -> str:
        """生成数据库 URL"""
        return f"sqlite:///{self.DATABASE_PATH}"
    
    def get_env_with_proxy(self) -> dict:
        """获取包含代理设置的环境变量"""
        env = os.environ.copy()
        env["HTTP_PROXY"] = self.proxy_url
        env["HTTPS_PROXY"] = self.proxy_url
        return env


# 全局配置实例
config = Config()
