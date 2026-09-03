"""管理 LangGraph 使用的 SQLite 检查点连接。"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


class InvalidDatabaseUrlError(ValueError):
    """数据库地址不是当前支持的 SQLite 地址。"""


def sqlite_path_from_url(database_url: str) -> Path | str:
    """把 SQLite URL 转换为检查点组件可使用的连接字符串。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise InvalidDatabaseUrlError("首版 Checkpointer 仅支持 SQLite 数据库")
    value = database_url.removeprefix(prefix)
    if value == ":memory:":
        return value
    if not value:
        raise InvalidDatabaseUrlError("SQLite 数据库路径不能为空")
    return Path(value).expanduser().resolve()


class SqliteCheckpointStore:
    """按运行需要打开并关闭 SQLite Checkpointer。"""

    def __init__(self, database_url: str) -> None:
        self.database_path = sqlite_path_from_url(database_url)

    @contextmanager
    def open(self) -> Iterator[SqliteSaver]:
        if isinstance(self.database_path, Path):
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with SqliteSaver.from_conn_string(str(self.database_path)) as saver:
            yield saver

    def delete_thread(self, thread_id: str) -> bool:
        """删除一个运行线程的全部 LangGraph 检查点和待写入数据。"""
        with self.open() as saver:
            saver.setup()
            row = saver.conn.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM checkpoints WHERE thread_id = ?
                    UNION ALL
                    SELECT 1 FROM writes WHERE thread_id = ?
                    LIMIT 1
                )
                """,
                (thread_id, thread_id),
            ).fetchone()
            saver.delete_thread(thread_id)
        return bool(row and row[0])
