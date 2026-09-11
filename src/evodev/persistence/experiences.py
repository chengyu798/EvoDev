"""使用 PostgreSQL 保存、检索和评估可复用经验。"""

from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from evodev.domain.experiences import Experience, ExperienceMatch, ExperienceOutcome
from evodev.evaluation.retrieval import rank_experience_matches
from evodev.persistence.checkpoints import validate_postgres_url


class ExperienceStoreProtocol(Protocol):
    """工作流依赖的经验仓库接口。"""

    def save(self, experience: Experience) -> Experience: ...

    def search(
        self,
        *,
        task_type: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[ExperienceMatch]: ...

    def get_many(self, experience_ids: Iterable[UUID]) -> list[Experience]: ...

    def record_usage(self, experience_ids: Iterable[UUID], run_id: UUID) -> int: ...

    def finalize_run_usage(self, run_id: UUID, outcome: ExperienceOutcome) -> int: ...

    def list_for_evolution(self, *, limit: int = 5) -> list[Experience]: ...


class PostgresExperienceStore:
    """提供标签检索、效果回写和质量排序的经验仓库。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = validate_postgres_url(database_url)
        self._initialized = False

    def setup(self) -> None:
        """创建或升级经验表；重复执行不会清空现有数据。"""
        if self._initialized:
            return
        with connect(self.database_url, autocommit=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_experiences (
                    id UUID PRIMARY KEY,
                    source_run_id UUID NOT NULL UNIQUE,
                    task_type TEXT NOT NULL,
                    tags TEXT[] NOT NULL DEFAULT '{}',
                    failure_pattern TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    recommended_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
                    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
                    success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
                    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
                    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            self._upgrade_experience_table(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS evodev_experiences_tags_idx
                ON evodev_experiences USING GIN (tags)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evodev_experience_usages (
                    experience_id UUID NOT NULL REFERENCES evodev_experiences(id)
                        ON DELETE CASCADE,
                    run_id UUID NOT NULL,
                    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    outcome TEXT NOT NULL DEFAULT 'pending',
                    feedback_at TIMESTAMPTZ,
                    PRIMARY KEY (experience_id, run_id)
                )
                """
            )
            connection.execute(
                "ALTER TABLE evodev_experience_usages ADD COLUMN IF NOT EXISTS "
                "outcome TEXT NOT NULL DEFAULT 'pending'"
            )
            connection.execute(
                "ALTER TABLE evodev_experience_usages ADD COLUMN IF NOT EXISTS "
                "feedback_at TIMESTAMPTZ"
            )
        self._initialized = True

    @staticmethod
    def _upgrade_experience_table(connection: Any) -> None:
        statements = [
            "ADD COLUMN IF NOT EXISTS success_count INTEGER NOT NULL DEFAULT 0",
            "ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0",
            "ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.5",
            "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'",
            "ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ",
        ]
        for statement in statements:
            connection.execute(f"ALTER TABLE evodev_experiences {statement}")

    def save(self, experience: Experience) -> Experience:
        """按来源运行幂等保存经验。"""
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO evodev_experiences (
                    id, source_run_id, task_type, tags, failure_pattern, lesson,
                    recommended_actions, usage_count, success_count, failure_count,
                    quality_score, status, last_used_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_run_id) DO UPDATE SET
                    task_type = EXCLUDED.task_type,
                    tags = EXCLUDED.tags,
                    failure_pattern = EXCLUDED.failure_pattern,
                    lesson = EXCLUDED.lesson,
                    recommended_actions = EXCLUDED.recommended_actions
                RETURNING *
                """,
                (
                    experience.id,
                    experience.source_run_id,
                    experience.task_type,
                    experience.tags,
                    experience.failure_pattern,
                    experience.lesson,
                    Jsonb(experience.recommended_actions),
                    experience.usage_count,
                    experience.success_count,
                    experience.failure_count,
                    experience.quality_score,
                    experience.status.value,
                    experience.last_used_at,
                    experience.created_at,
                ),
            ).fetchone()
            connection.commit()
        return self._from_row(row)

    def search(
        self,
        *,
        task_type: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[ExperienceMatch]:
        """按标签相关度和历史有效性检索启用经验。"""
        if limit < 1 or not tags:
            return []
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM evodev_experiences
                WHERE task_type = %s AND status = 'active' AND tags && %s
                """,
                (task_type, tags),
            ).fetchall()
        return rank_experience_matches(
            (self._from_row(row) for row in rows),
            tags,
            limit=limit,
        )

    def get_many(self, experience_ids: Iterable[UUID]) -> list[Experience]:
        """按传入顺序读取多条经验。"""
        ids = list(experience_ids)
        if not ids:
            return []
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                "SELECT * FROM evodev_experiences WHERE id = ANY(%s)",
                (ids,),
            ).fetchall()
        by_id = {row["id"]: self._from_row(row) for row in rows}
        return [by_id[experience_id] for experience_id in ids if experience_id in by_id]

    def record_usage(self, experience_ids: Iterable[UUID], run_id: UUID) -> int:
        """每条经验在一次运行中只增加一次使用次数。"""
        ids = list(dict.fromkeys(experience_ids))
        if not ids:
            return 0
        self.setup()
        recorded = 0
        with connect(self.database_url) as connection:
            for experience_id in ids:
                inserted = connection.execute(
                    """
                    INSERT INTO evodev_experience_usages (experience_id, run_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING experience_id
                    """,
                    (experience_id, run_id),
                ).fetchone()
                if inserted is None:
                    continue
                connection.execute(
                    """
                    UPDATE evodev_experiences
                    SET usage_count = usage_count + 1, last_used_at = NOW()
                    WHERE id = %s
                    """,
                    (experience_id,),
                )
                recorded += 1
            connection.commit()
        return recorded

    def finalize_run_usage(self, run_id: UUID, outcome: ExperienceOutcome) -> int:
        """回写运行结果；非业务错误不会改变经验质量分。"""
        self.setup()
        with connect(self.database_url) as connection:
            rows = connection.execute(
                """
                UPDATE evodev_experience_usages
                SET outcome = %s, feedback_at = NOW()
                WHERE run_id = %s AND outcome = 'pending'
                RETURNING experience_id
                """,
                (outcome.value, run_id),
            ).fetchall()
            experience_ids = [row[0] for row in rows]
            if outcome in {ExperienceOutcome.SUCCESS, ExperienceOutcome.FAILURE}:
                for experience_id in experience_ids:
                    self._update_quality(connection, experience_id, outcome)
            connection.commit()
        return len(experience_ids)

    @staticmethod
    def _update_quality(
        connection: Any,
        experience_id: UUID,
        outcome: ExperienceOutcome,
    ) -> None:
        success_delta = int(outcome is ExperienceOutcome.SUCCESS)
        failure_delta = int(outcome is ExperienceOutcome.FAILURE)
        row = connection.execute(
            """
            UPDATE evodev_experiences
            SET success_count = success_count + %s,
                failure_count = failure_count + %s
            WHERE id = %s
            RETURNING success_count, failure_count, status
            """,
            (success_delta, failure_delta, experience_id),
        ).fetchone()
        success_count, failure_count, current_status = row
        quality_score = (success_count + 1) / (success_count + failure_count + 2)
        status = (
            "disabled"
            if success_count + failure_count >= 3 and quality_score < 0.35
            else current_status
        )
        connection.execute(
            """
            UPDATE evodev_experiences
            SET quality_score = %s, status = %s
            WHERE id = %s
            """,
            (quality_score, status, experience_id),
        )

    def list_for_evolution(self, *, limit: int = 5) -> list[Experience]:
        """返回可用于生成候选 Prompt 的最高质量经验。"""
        if limit < 1:
            return []
        self.setup()
        with connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT * FROM evodev_experiences
                WHERE status = 'active'
                ORDER BY quality_score DESC, success_count DESC, usage_count DESC,
                    created_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: dict[str, object] | None) -> Experience:
        if row is None:
            raise RuntimeError("PostgreSQL 未返回经验记录")
        return Experience.model_validate(row)
