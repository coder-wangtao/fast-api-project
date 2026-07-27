from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import os
from pathlib import Path
import re
import getpass

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 基础配置
    DEBUG: bool = Field(default=True)
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    ALLOWED_ORIGINS: List[str] = Field(default_factory=lambda: ["*"])


    MONGODB_HOST: str = Field(default="localhost")
    MONGODB_PORT: int = Field(default=27017)
    MONGODB_USERNAME: str = Field(default="")
    MONGODB_PASSWORD: str = Field(default="")
    MONGODB_DATABASE: str = Field(default="tradingagentscn")
    MONGODB_DATABASE_SCOPE: str = Field(default="auto")
    MONGODB_DATABASE_INSTANCE: str = Field(default="")
    MONGODB_AUTH_SOURCE: str = Field(default="admin")

    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: str = Field(default="")
    REDIS_DB: int = Field(default=0)
    REDIS_MAX_CONNECTIONS: int = Field(default=20)
    REDIS_RETRY_ON_TIMEOUT: bool = Field(default=True)
    MONGO_MAX_CONNECTIONS: int = Field(default=100)
    MONGO_MIN_CONNECTIONS: int = Field(default=10)
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int = Field(default=5000)  # 服务器选择超时：5秒
    MONGO_CONNECT_TIMEOUT_MS: int = Field(default=30000)  # 连接超时：30秒（原为10秒）
    MONGO_SOCKET_TIMEOUT_MS: int = Field(default=60000)   # 套接字超时：60秒（原为20秒）

    QUOTES_INGEST_INTERVAL_SECONDS: int = Field(
        default=360,
        description="实时行情采集间隔（秒）。默认360秒（6分钟），免费用户建议>=300秒，付费用户可设置5-60秒"
    )

    ALLOW_SHARED_DB_IN_DEBUG: bool = Field(default=False)

    JWT_SECRET: str = Field(default="change-me-in-production")

    # 休市期/启动兜底补数（填充上一笔快照）
    QUOTES_BACKFILL_ON_STARTUP: bool = Field(default=True)

    JWT_ALGORITHM: str = Field(default="HS256")
    TUSHARE_ENABLED: bool = Field(default=False, description="启用Tushare数据源")

    LOG_LEVEL: str = Field(default="INFO")
    TIMEZONE: str = Field(default="Asia/Shanghai")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)

    # 数据目录配置
    TRADINGAGENTS_DATA_DIR: str = Field(default="./data")

    
    # DEBUG→major_instance；生产环境→explicit
    # explicit             用配置原名                             tradingagentscn_explicit
    # major                原名 + 主版本                        tradingagentscn_major
    # major_instance 原名 + 主版本 + 本机实例                tradingagentscn_major_instance_wang-pc  
    @property
    def MONGO_DB_IDENTITY(self) -> dict:
        scope = (self.MONGODB_DATABASE_SCOPE or "").strip().lower() or "auto"
        if scope == "auto":
            resolved_scope = "major_instance" if self.DEBUG else "explicit"
        else:
            resolved_scope = scope

        major = _read_major_version()
        instance = (self.MONGODB_DATABASE_INSTANCE or "").strip()
        if resolved_scope == "major_instance" and not instance:
            instance = _default_instance_tag()

        return {
            "base_database": self.MONGODB_DATABASE,
            "scope_configured": scope,
            "scope_effective": resolved_scope,
            "major_version": major,
            "instance": instance,
            "database": self.MONGO_DB,
        }

    @property
    def MONGO_URI(self) -> str:
        """构建MongoDB URI"""
        if self.MONGODB_USERNAME and self.MONGODB_PASSWORD:
            return f"mongodb://{self.MONGODB_USERNAME}:{self.MONGODB_PASSWORD}@{self.MONGODB_HOST}:{self.MONGODB_PORT}/{self.MONGO_DB}?authSource={self.MONGODB_AUTH_SOURCE}"
        else:
            return f"mongodb://{self.MONGODB_HOST}:{self.MONGODB_PORT}/{self.MONGO_DB}"

    @property
    def REDIS_URL(self) -> str:
        """构建 Redis URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def MONGO_DB(self) -> str:
        """获取数据库名称"""
        scope = (self.MONGODB_DATABASE_SCOPE or "").strip().lower()
        if not scope or scope == "auto":
            scope = "major_instance" if self.DEBUG else "explicit"

        if scope == "explicit":
            return self.MONGODB_DATABASE

        base = self.MONGODB_DATABASE
        major = _read_major_version()

        if scope == "major":
            name = f"{base}_v{major}"
            return _sanitize_mongo_db_name(name)

        if scope == "major_instance":
            instance = (self.MONGODB_DATABASE_INSTANCE or "").strip()
            if not instance:
                instance = _default_instance_tag()
            name = f"{base}_v{major}_{instance}"
            return _sanitize_mongo_db_name(name)

        return _sanitize_mongo_db_name(base)

settings = Settings()


def _read_major_version() -> str:
    v = os.getenv("TRADINGAGENTS_VERSION", "").strip() or os.getenv("APP_VERSION", "").strip()
    if not v:
        try:
            v = Path(__file__).resolve().parents[3].joinpath("VERSION").read_text(encoding="utf-8").strip()
        except Exception:
            v = ""

    m = re.match(r"^\s*(\d+)", v)
    return m.group(1) if m else "0"

def _default_instance_tag() -> str:
    user = os.getenv("TRADINGAGENTS_DB_USER", "").strip() or getpass.getuser()
    host = os.getenv("TRADINGAGENTS_DB_HOST", "").strip() or os.getenv("COMPUTERNAME", "").strip() or os.getenv("HOSTNAME", "").strip()
    tag = f"{user}-{host}" if host else user
    return _sanitize_mongo_db_name(tag).strip("_-").lower() or "local"


def _sanitize_mongo_db_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(name)).strip("._-")
    if not cleaned:
        return "tradingagentscn"

    max_len = 63
    if len(cleaned) <= max_len:
        return cleaned

    suffix = str(abs(hash(cleaned)) % (10**8)).rjust(8, "0")
    return f"{cleaned[:max_len-9]}_{suffix}"


def get_settings() -> Settings:
    """获取配置实例"""
    return settings
