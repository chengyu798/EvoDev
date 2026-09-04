"""使用真实 PostgreSQL 验证 LangGraph 检查点读写。"""

import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from evodev.persistence.checkpoints import PostgresCheckpointStore


class CounterState(TypedDict):
    value: int


@pytest.mark.skipif(
    not os.getenv("EVODEV_TEST_DATABASE_URL"),
    reason="未配置 PostgreSQL 集成测试数据库",
)
def test_postgres_checkpointer_persists_and_deletes_thread() -> None:
    database_url = os.environ["EVODEV_TEST_DATABASE_URL"]
    store = PostgresCheckpointStore(database_url)
    builder = StateGraph(CounterState)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    thread_id = f"integration-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        with store.open() as checkpointer:
            graph = builder.compile(checkpointer=checkpointer)
            result = graph.invoke({"value": 1}, config=config)
            checkpoints = list(checkpointer.list(config))

        assert result == {"value": 2}
        assert checkpoints
    finally:
        store.delete_thread(thread_id)

    assert store.delete_thread(thread_id) is False
