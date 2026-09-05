"""使用 PostgreSQL 管理 Prompt 进化任务和版本。"""

from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from evodev.agents.schemas import PromptOptimization
from evodev.domain.evolution import (
    EvolutionJobStatus,
    PromptEvaluationComparison,
    PromptEvolutionJob,
    PromptVersion,
    PromptVersionStatus,
)
from evodev.persistence.checkpoints import validate_postgres_url


class PostgresPromptEvolutionStore:
    """持久化候选 Prompt，并通过数据库行锁分发 Worker 任务。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = validate_postgres_url(database_url)
        self._initialized = False

    def setup(self) -> None:
        if self._initialized:
            return
        with connect(self.database_url, autocommit=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_prompt_versions (
                    id UUID PRIMARY KEY,
                    agent_role TEXT NOT NULL,
                    base_prompt_version TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    guidance TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    expected_effects JSONB NOT NULL DEFAULT '[]'::jsonb,
                    risks JSONB NOT NULL DEFAULT '[]'::jsonb,
                    source_experience_ids UUID[] NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    evaluation JSONB,
                    rejection_reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    activated_at TIMESTAMPTZ,
                    UNIQUE (agent_role, revision)
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS evodev_one_active_prompt_per_role_idx
                ON evodev_prompt_versions (agent_role)
                WHERE status = 'active'
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_prompt_evolution_jobs (
                    id UUID PRIMARY KEY,
                    agent_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    min_experiences INTEGER NOT NULL DEFAULT 1,
                    candidate_version_id UUID REFERENCES evodev_prompt_versions(id),
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    finished_at TIMESTAMPTZ
                )
                """
            )
        self._initialized = True

    def enqueue(self, *, agent_role: str, min_experiences: int = 1) -> PromptEvolutionJob:
        """创建等待独立 Worker 处理的进化任务。"""
        self.setup()
        job = PromptEvolutionJob(agent_role=agent_role, min_experiences=min_experiences)
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO evodev_prompt_evolution_jobs (
                    id, agent_role, status, min_experiences, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    job.id,
                    job.agent_role,
                    job.status.value,
                    job.min_experiences,
                    job.created_at,
                ),
            ).fetchone()
            connection.commit()
        return self._job_from_row(row)

    def enqueue_if_absent(
        self,
        *,
        agent_role: str,
        min_experiences: int,
    ) -> PromptEvolutionJob | None:
        """没有同角色待处理任务时才投递，供主任务轻量触发。"""
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"prompt-job:{agent_role}",),
            )
            existing = connection.execute(
                """
                SELECT id FROM evodev_prompt_evolution_jobs
                WHERE agent_role = %s AND status IN ('pending', 'running')
                LIMIT 1
                """,
                (agent_role,),
            ).fetchone()
            if existing is not None:
                return None
            job = PromptEvolutionJob(
                agent_role=agent_role,
                min_experiences=min_experiences,
            )
            row = connection.execute(
                """
                INSERT INTO evodev_prompt_evolution_jobs (
                    id, agent_role, status, min_experiences, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    job.id,
                    job.agent_role,
                    job.status.value,
                    job.min_experiences,
                    job.created_at,
                ),
            ).fetchone()
            connection.commit()
        return self._job_from_row(row)

    def claim_next(self, agent_role: str | None = None) -> PromptEvolutionJob | None:
        """通过 SKIP LOCKED 原子领取一个待处理任务。"""
        self.setup()
        role_filter = "AND agent_role = %s" if agent_role is not None else ""
        parameters = (agent_role,) if agent_role is not None else ()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                f"""
                WITH next_job AS (
                    SELECT id FROM evodev_prompt_evolution_jobs
                    WHERE status = 'pending' {role_filter}
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE evodev_prompt_evolution_jobs AS job
                SET status = 'running', started_at = NOW()
                FROM next_job
                WHERE job.id = next_job.id
                RETURNING job.*
                """,
                parameters,
            ).fetchone()
            connection.commit()
        return self._job_from_row(row) if row else None

    def create_candidate(
        self,
        *,
        job_id: UUID,
        agent_role: str,
        base_prompt_version: str,
        optimization: PromptOptimization,
        source_experience_ids: list[UUID],
    ) -> PromptVersion:
        """创建候选版本，并关联正在执行的进化任务。"""
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"prompt:{agent_role}",),
            )
            revision_row = connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) + 1 AS next_revision
                FROM evodev_prompt_versions
                WHERE agent_role = %s
                """,
                (agent_role,),
            ).fetchone()
            revision = revision_row["next_revision"]
            candidate = PromptVersion(
                agent_role=agent_role,
                base_prompt_version=base_prompt_version,
                revision=revision,
                guidance=optimization.guidance,
                hypothesis=optimization.hypothesis,
                expected_effects=optimization.expected_effects,
                risks=optimization.risks,
                source_experience_ids=source_experience_ids,
            )
            row = connection.execute(
                """
                INSERT INTO evodev_prompt_versions (
                    id, agent_role, base_prompt_version, revision, guidance,
                    hypothesis, expected_effects, risks, source_experience_ids,
                    status, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    candidate.id,
                    candidate.agent_role,
                    candidate.base_prompt_version,
                    candidate.revision,
                    candidate.guidance,
                    candidate.hypothesis,
                    Jsonb(candidate.expected_effects),
                    Jsonb(candidate.risks),
                    candidate.source_experience_ids,
                    candidate.status.value,
                    candidate.created_at,
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE evodev_prompt_evolution_jobs
                SET candidate_version_id = %s
                WHERE id = %s
                """,
                (candidate.id, job_id),
            )
            connection.commit()
        return self._version_from_row(row)

    def finish_evaluation(
        self,
        *,
        job_id: UUID,
        candidate_id: UUID,
        comparison: PromptEvaluationComparison,
    ) -> PromptVersion:
        """保存 A/B 结果，并原子激活或拒绝候选版本。"""
        self.setup()
        version_status = (
            PromptVersionStatus.ACTIVE if comparison.promoted else PromptVersionStatus.REJECTED
        )
        job_status = (
            EvolutionJobStatus.SUCCEEDED if comparison.promoted else EvolutionJobStatus.REJECTED
        )
        with connect(self.database_url, row_factory=dict_row) as connection:
            candidate = connection.execute(
                "SELECT agent_role FROM evodev_prompt_versions WHERE id = %s FOR UPDATE",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise RuntimeError("找不到待评测的候选 Prompt")
            agent_role = candidate["agent_role"]
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"prompt:{agent_role}",),
            )
            if comparison.promoted:
                connection.execute(
                    """
                    UPDATE evodev_prompt_versions
                    SET status = 'retired'
                    WHERE agent_role = %s AND status = 'active'
                    """,
                    (agent_role,),
                )
            row = connection.execute(
                """
                UPDATE evodev_prompt_versions
                SET status = %s,
                    evaluation = %s,
                    rejection_reason = %s,
                    activated_at = CASE WHEN %s = 'active' THEN NOW() ELSE NULL END
                WHERE id = %s
                RETURNING *
                """,
                (
                    version_status.value,
                    Jsonb(comparison.model_dump(mode="json")),
                    None if comparison.promoted else comparison.reason,
                    version_status.value,
                    candidate_id,
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE evodev_prompt_evolution_jobs
                SET status = %s, finished_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                (
                    job_status.value,
                    None if comparison.promoted else comparison.reason,
                    job_id,
                ),
            )
            connection.commit()
        return self._version_from_row(row)

    def fail_job(self, job_id: UUID, message: str) -> None:
        """记录 Worker 无法完成的进化任务。"""
        self.setup()
        with connect(self.database_url) as connection:
            connection.execute(
                """
                UPDATE evodev_prompt_evolution_jobs
                SET status = 'failed', error_message = %s, finished_at = NOW()
                WHERE id = %s
                """,
                (message[:4_000], job_id),
            )
            connection.commit()

    def get_active_guidance(self, agent_role: str) -> tuple[str, str] | None:
        """返回运行时需要的指导内容和有效版本号。"""
        active = self.get_active(agent_role)
        if active is None:
            return None
        return active.guidance, active.effective_version

    def get_active(self, agent_role: str) -> PromptVersion | None:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT * FROM evodev_prompt_versions
                WHERE agent_role = %s AND status = 'active'
                """,
                (agent_role,),
            ).fetchone()
        return self._version_from_row(row) if row else None

    def list_versions(self, agent_role: str) -> list[PromptVersion]:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT * FROM evodev_prompt_versions
                WHERE agent_role = %s
                ORDER BY revision DESC
                """,
                (agent_role,),
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def list_jobs(self, *, limit: int = 20) -> list[PromptEvolutionJob]:
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT * FROM evodev_prompt_evolution_jobs
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def rollback(self, agent_role: str) -> PromptVersion | None:
        """把当前版本退役，并重新启用上一个曾激活的版本。"""
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"prompt:{agent_role}",),
            )
            current = connection.execute(
                """
                SELECT id FROM evodev_prompt_versions
                WHERE agent_role = %s AND status = 'active'
                FOR UPDATE
                """,
                (agent_role,),
            ).fetchone()
            previous = connection.execute(
                """
                SELECT id FROM evodev_prompt_versions
                WHERE agent_role = %s AND status = 'retired'
                ORDER BY activated_at DESC NULLS LAST, revision DESC
                LIMIT 1 FOR UPDATE
                """,
                (agent_role,),
            ).fetchone()
            if current is None or previous is None:
                return None
            connection.execute(
                "UPDATE evodev_prompt_versions SET status = 'retired' WHERE id = %s",
                (current["id"],),
            )
            row = connection.execute(
                """
                UPDATE evodev_prompt_versions
                SET status = 'active', activated_at = NOW()
                WHERE id = %s RETURNING *
                """,
                (previous["id"],),
            ).fetchone()
            connection.commit()
        return self._version_from_row(row)

    @staticmethod
    def _version_from_row(row: dict[str, object] | None) -> PromptVersion:
        if row is None:
            raise RuntimeError("PostgreSQL 未返回 Prompt 版本")
        return PromptVersion.model_validate(row)

    @staticmethod
    def _job_from_row(row: dict[str, object] | None) -> PromptEvolutionJob:
        if row is None:
            raise RuntimeError("PostgreSQL 未返回 Prompt 进化任务")
        return PromptEvolutionJob.model_validate(row)
