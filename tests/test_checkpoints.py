"""验证 PostgreSQL Checkpointer 的连接地址和生命周期。"""

import pytest

from evodev.persistence.checkpoints import (
    InvalidDatabaseUrlError,
    PostgresCheckpointStore,
    validate_postgres_url,
)


def test_checkpoint_store_only_accepts_postgres_url() -> None:
    with pytest.raises(InvalidDatabaseUrlError, match="PostgreSQL"):
        validate_postgres_url("sqlite:///data/evodev.db")

    assert (
        validate_postgres_url("postgresql://evodev:evodev@localhost:55432/evodev")
        == "postgresql://evodev:evodev@localhost:55432/evodev"
    )


def test_checkpoint_store_runs_setup_before_use(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            events.append("connect")
            return self

        def __exit__(self, *_: object) -> None:
            events.append("close")

    class FakeSaver:
        def __init__(self, connection: object, *, serde: object) -> None:
            del connection, serde

        def setup(self) -> None:
            events.append("setup")

    def fake_connection(*_: object, **__: object) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("evodev.persistence.checkpoints.connect", fake_connection)
    monkeypatch.setattr("evodev.persistence.checkpoints.PostgresSaver", FakeSaver)
    store = PostgresCheckpointStore("postgresql://evodev:evodev@localhost:55432/evodev")

    with store.open():
        events.append("use")

    assert events == ["connect", "setup", "use", "close"]


def test_checkpoint_availability_returns_false_when_connection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connection(*_: object, **__: object) -> None:
        raise OSError("数据库不可达")

    monkeypatch.setattr("evodev.persistence.checkpoints.connect", fail_connection)
    store = PostgresCheckpointStore("postgresql://evodev:evodev@localhost:55432/evodev")

    assert store.is_available() is False
