"""使用真实 PostgreSQL 验证检查点和经验存储。"""

import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from psycopg import connect

from evodev.agents.schemas import PromptOptimization
from evodev.domain.evolution import PromptEvaluationComparison, PromptVersionStatus
from evodev.domain.experiences import Experience, ExperienceOutcome, ExperienceStatus
from evodev.domain.runs import RunEvent, TaskRunRead
from evodev.domain.tasks import TaskRead
from evodev.persistence.checkpoints import PostgresCheckpointStore
from evodev.persistence.evolution import PostgresPromptEvolutionStore
from evodev.persistence.experiences import PostgresExperienceStore
from evodev.persistence.tasks import (
    PostgresRunStore,
    PostgresTaskRunStore,
    PostgresTaskStore,
)


class CounterState(TypedDict):
    value: int


@pytest.mark.skipif(
    not os.getenv("EVODEV_TEST_DATABASE_URL"),
    reason="未配置 PostgreSQL 集成测试数据库",
)
def test_postgres_task_run_store_persists_summary_and_events(tmp_path) -> None:
    database_url = os.environ["EVODEV_TEST_DATABASE_URL"]
    shared_store = PostgresTaskRunStore(database_url)
    task_store = PostgresTaskStore(shared_store)
    run_store = PostgresRunStore(shared_store)
    task = TaskRead(
        repository_path=tmp_path,
        issue_title="持久化任务",
        issue_body="验证任务和运行记录。",
        test_command="pytest -q",
        constraints=[],
        max_iterations=3,
    )
    run = TaskRunRead(task_id=task.id)

    try:
        task_store.save(task)
        run_store.save(run, {"status": "created"})
        run_store.add_event(
            RunEvent(
                run_id=run.id,
                event_type="run.created",
                payload={"status": "created"},
            )
        )

        assert task_store.get(task.id) == task
        assert run_store.get(run.id) == run
        assert run_store.get_result(run.id) == {"status": "created"}
        assert run_store.events(run.id)[0].event_type == "run.created"
    finally:
        with connect(database_url) as connection:
            connection.execute("DELETE FROM evodev_run_events WHERE run_id = %s", (run.id,))
            connection.execute("DELETE FROM evodev_task_runs WHERE id = %s", (run.id,))
            connection.execute("DELETE FROM evodev_tasks WHERE id = %s", (task.id,))
            connection.commit()


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


@pytest.mark.skipif(
    not os.getenv("EVODEV_TEST_DATABASE_URL"),
    reason="未配置 PostgreSQL 集成测试数据库",
)
def test_postgres_experience_store_searches_and_counts_usage_once() -> None:
    database_url = os.environ["EVODEV_TEST_DATABASE_URL"]
    store = PostgresExperienceStore(database_url)
    experience = Experience(
        source_run_id=uuid4(),
        tags=["task:bug_fix", "term:unique_calculator"],
        failure_pattern="计算结果断言失败",
        lesson="核对运算符和边界条件",
        recommended_actions=["读取实现", "运行定向测试"],
    )
    consumer_run_id = uuid4()

    try:
        saved = store.save(experience)
        found = store.search(
            task_type="bug_fix",
            tags=["task:bug_fix", "term:unique_calculator"],
        )
        first_count = store.record_usage([saved.id], consumer_run_id)
        second_count = store.record_usage([saved.id], consumer_run_id)
        feedback_count = store.finalize_run_usage(
            consumer_run_id,
            ExperienceOutcome.SUCCESS,
        )
        repeated_feedback_count = store.finalize_run_usage(
            consumer_run_id,
            ExperienceOutcome.FAILURE,
        )
        reloaded = store.get_many([saved.id])[0]

        assert found[0].id == saved.id
        assert first_count == 1
        assert second_count == 0
        assert feedback_count == 1
        assert repeated_feedback_count == 0
        assert reloaded.usage_count == 1
        assert reloaded.success_count == 1
        assert reloaded.failure_count == 0
        assert reloaded.quality_score == pytest.approx(2 / 3)

        for _ in range(3):
            failed_run_id = uuid4()
            store.record_usage([saved.id], failed_run_id)
            store.finalize_run_usage(failed_run_id, ExperienceOutcome.FAILURE)
        disabled = store.get_many([saved.id])[0]
        no_longer_retrieved = store.search(
            task_type="bug_fix",
            tags=["term:unique_calculator"],
        )
        assert disabled.status is ExperienceStatus.DISABLED
        assert disabled.quality_score == pytest.approx(2 / 6)
        assert all(item.id != saved.id for item in no_longer_retrieved)
    finally:
        with connect(database_url) as connection:
            connection.execute(
                "DELETE FROM evodev_experiences WHERE id = %s",
                (experience.id,),
            )
            connection.commit()


@pytest.mark.skipif(
    not os.getenv("EVODEV_TEST_DATABASE_URL"),
    reason="未配置 PostgreSQL 集成测试数据库",
)
def test_postgres_prompt_versions_activate_and_rollback() -> None:
    database_url = os.environ["EVODEV_TEST_DATABASE_URL"]
    store = PostgresPromptEvolutionStore(database_url)
    role = f"integration-{uuid4().hex}"
    job_ids = []
    version_ids = []

    try:
        first_job = store.enqueue(agent_role=role)
        job_ids.append(first_job.id)
        claimed = store.claim_next(role)
        assert claimed is not None
        assert claimed.id == first_job.id
        first = store.create_candidate(
            job_id=claimed.id,
            agent_role=role,
            base_prompt_version="3",
            optimization=PromptOptimization(
                hypothesis="减少无效修改",
                guidance="修改前先核对失败断言与当前实现，确认根因后只修改必要代码。",
                expected_effects=["减少重试"],
            ),
            source_experience_ids=[],
        )
        version_ids.append(first.id)
        first = store.finish_evaluation(
            job_id=claimed.id,
            candidate_id=first.id,
            comparison=PromptEvaluationComparison(
                baseline=[], candidate=[], promoted=True, reason="集成测试激活"
            ),
        )
        assert first.status is PromptVersionStatus.ACTIVE

        second_job = store.enqueue(agent_role=role)
        job_ids.append(second_job.id)
        claimed = store.claim_next(role)
        assert claimed is not None
        second = store.create_candidate(
            job_id=claimed.id,
            agent_role=role,
            base_prompt_version="3",
            optimization=PromptOptimization(
                hypothesis="进一步减少无效修改",
                guidance="先运行定向测试，再检查差异范围并避免修改与问题无关的文件。",
                expected_effects=["缩小补丁"],
            ),
            source_experience_ids=[],
        )
        version_ids.append(second.id)
        store.finish_evaluation(
            job_id=claimed.id,
            candidate_id=second.id,
            comparison=PromptEvaluationComparison(
                baseline=[], candidate=[], promoted=True, reason="集成测试升级"
            ),
        )

        active = store.get_active(role)
        assert active is not None
        assert active.id == second.id
        rolled_back = store.rollback(role)
        assert rolled_back is not None
        assert rolled_back.id == first.id
        assert store.get_active_guidance(role) == (
            first.guidance,
            first.effective_version,
        )
    finally:
        with connect(database_url) as connection:
            connection.execute(
                "DELETE FROM evodev_prompt_evolution_jobs WHERE id = ANY(%s)",
                (job_ids,),
            )
            connection.execute(
                "DELETE FROM evodev_prompt_versions WHERE id = ANY(%s)",
                (version_ids,),
            )
            connection.commit()
