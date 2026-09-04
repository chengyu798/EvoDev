"""管理 LangGraph 使用的 PostgreSQL 检查点连接。"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Error, connect
from psycopg.rows import dict_row


class InvalidDatabaseUrlError(ValueError):
    """数据库地址不是 PostgreSQL 连接地址。"""


class CheckpointStoreProtocol(Protocol):
    """应用服务依赖的检查点存储接口。"""

    def open(self) -> AbstractContextManager[BaseCheckpointSaver]: ...

    def delete_thread(self, thread_id: str) -> bool: ...


def validate_postgres_url(database_url: str) -> str:
    """校验并返回 PostgreSQL 数据库连接地址。"""
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise InvalidDatabaseUrlError("检查点数据库必须使用 PostgreSQL 连接地址")
    return database_url


class PostgresCheckpointStore:
    """按运行需要打开 LangGraph 官方 PostgreSQL Checkpointer。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = validate_postgres_url(database_url)
        self.serializer = JsonPlusSerializer(allowed_msgpack_modules=())

    @contextmanager
    def open(self) -> Iterator[PostgresSaver]:
        with connect(
            self.database_url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        ) as connection:
            saver = PostgresSaver(connection, serde=self.serializer)
            # setup 会创建或升级官方检查点表，重复调用是幂等的。
            saver.setup()
            yield saver

    def is_available(self) -> bool:
        """检查 PostgreSQL 是否可以连接，不创建或修改数据表。"""
        try:
            with connect(self.database_url, connect_timeout=3):
                return True
        except (Error, OSError):
            return False

    def delete_thread(self, thread_id: str) -> bool:
        """删除一个运行线程的全部检查点，返回删除前是否存在记录。"""
        config = {"configurable": {"thread_id": thread_id}}
        with self.open() as saver:
            existed = next(saver.list(config, limit=1), None) is not None
            saver.delete_thread(thread_id)
        return existed
