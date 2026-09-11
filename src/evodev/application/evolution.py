"""在独立进程中生成、评测并激活候选 Prompt。"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, TypeAdapter

from evodev.agents.catalog import default_agent_catalog
from evodev.agents.client import LiteLLMClient
from evodev.agents.executor import AgentExecutor
from evodev.agents.prompting import PromptRepository
from evodev.agents.schemas import ImplementationResult, IssueAnalysis, PromptOptimization
from evodev.agents.tools import AgentToolbox
from evodev.application.repair import build_repair_workflow_service
from evodev.config import Settings
from evodev.domain.evolution import (
    PromptBenchmarkResult,
    PromptEvaluationComparison,
    PromptEvolutionJob,
    PromptVersion,
)
from evodev.domain.experiences import Experience, ExperienceMatch, ExperienceOutcome
from evodev.domain.tasks import TaskRead
from evodev.persistence.artifacts import LocalArtifactStore
from evodev.persistence.checkpoints import PostgresCheckpointStore
from evodev.persistence.evolution import PostgresPromptEvolutionStore
from evodev.persistence.experiences import PostgresExperienceStore
from evodev.runtime.workspace import WorkspaceManager
from evodev.tools.edit import EditTools
from evodev.tools.git import GitTools
from evodev.tools.repository import RepositoryTools

EVOLVABLE_SCHEMAS = {
    "analyst": IssueAnalysis,
    "developer": ImplementationResult,
}
FORBIDDEN_GUIDANCE_PATTERNS = (
    r"忽略.{0,8}(系统|安全|权限|测试)",
    r"绕过.{0,8}(测试|权限|限制)",
    r"(允许|可以|可直接|应该|应当|需要|优先|通过).{0,8}修改.{0,4}测试文件",
    r"(允许|可以|自行|扩大|放宽|绕过).{0,8}(更改|修改).{0,4}工具权限",
    r"无需.{0,8}真实测试",
    r"ignore.{0,12}(system|previous|safety)",
)


class PromptBenchmarkCase(BaseModel):
    """一条可重复执行的 Prompt 对照评测任务。"""

    name: str
    source_directory: Path
    issue_title: str
    issue_body: str
    test_command: str = "pytest -q"
    max_iterations: int = Field(default=3, ge=1, le=3)


class PromptOptimizerProtocol(Protocol):
    def optimize(
        self,
        *,
        agent_role: str,
        current_prompt: str,
        experiences: list[Experience],
    ) -> PromptOptimization: ...


class PromptBenchmarkEvaluatorProtocol(Protocol):
    def evaluate(
        self,
        *,
        agent_role: str,
        candidate: PromptVersion,
    ) -> PromptEvaluationComparison: ...


class NullExperienceStore:
    """A/B 评测期间关闭经验读写，保证两个版本输入一致。"""

    def save(self, experience: Experience) -> Experience:
        return experience

    def search(
        self,
        *,
        task_type: str,
        tags: list[str],
        limit: int = 3,
    ) -> list[ExperienceMatch]:
        del task_type, tags, limit
        return []

    def get_many(self, experience_ids: list[UUID]) -> list[Experience]:
        del experience_ids
        return []

    def record_usage(self, experience_ids: list[UUID], run_id: UUID) -> int:
        del experience_ids, run_id
        return 0

    def finalize_run_usage(self, run_id: UUID, outcome: ExperienceOutcome) -> int:
        del run_id, outcome
        return 0

    def list_for_evolution(self, *, limit: int = 5) -> list[Experience]:
        del limit
        return []


class ModelPromptOptimizer:
    """调用独立 Prompt Optimizer Agent 生成候选指导层。"""

    def __init__(self, settings: Settings) -> None:
        self.catalog = default_agent_catalog(settings.llm_model or "")
        toolbox = AgentToolbox(RepositoryTools(), EditTools(), GitTools())
        self.executor = AgentExecutor(
            LiteLLMClient(api_key=settings.llm_api_key, base_url=settings.llm_base_url),
            toolbox,
        )

    def optimize(
        self,
        *,
        agent_role: str,
        current_prompt: str,
        experiences: list[Experience],
    ) -> PromptOptimization:
        invocation = self.executor.invoke(
            agent=self.catalog["prompt_optimizer"],
            workspace=Path.cwd(),
            task={
                "target_agent": agent_role,
                "current_prompt": current_prompt,
                "experiences": [item.model_dump(mode="json") for item in experiences],
            },
            output_schema=PromptOptimization,
        )
        if not isinstance(invocation.output, PromptOptimization):
            raise TypeError("Prompt Optimizer 返回类型错误")
        return invocation.output


class RepairPromptBenchmarkEvaluator:
    """在相同真实 Bug 任务上比较当前 Prompt 与候选 Prompt。"""

    def __init__(
        self,
        settings: Settings,
        prompt_store: PostgresPromptEvolutionStore,
    ) -> None:
        self.settings = settings
        self.prompt_store = prompt_store

    def evaluate(
        self,
        *,
        agent_role: str,
        candidate: PromptVersion,
    ) -> PromptEvaluationComparison:
        cases = self._load_cases()
        baseline_repository = PromptRepository(guidance_provider=self.prompt_store)
        candidate_repository = PromptRepository(
            guidance_provider=self.prompt_store,
            guidance_overrides={agent_role: (candidate.guidance, candidate.effective_version)},
        )
        baseline = [self._run_case(case, baseline_repository, "baseline") for case in cases]
        candidate_results = [
            self._run_case(case, candidate_repository, "candidate") for case in cases
        ]
        promoted, reason = compare_prompt_results(baseline, candidate_results)
        return PromptEvaluationComparison(
            baseline=baseline,
            candidate=candidate_results,
            promoted=promoted,
            reason=reason,
        )

    def _load_cases(self) -> list[PromptBenchmarkCase]:
        benchmark_file = self.settings.prompt_benchmarks_file.expanduser().resolve()
        raw = json.loads(benchmark_file.read_text(encoding="utf-8"))
        cases = TypeAdapter(list[PromptBenchmarkCase]).validate_python(raw)
        if len(cases) < 2:
            raise ValueError("Prompt A/B 评测至少需要两个 Bug 任务")
        for case in cases:
            if not case.source_directory.is_absolute():
                case.source_directory = (benchmark_file.parent / case.source_directory).resolve()
        return cases

    def _run_case(
        self,
        case: PromptBenchmarkCase,
        prompt_repository: PromptRepository,
        variant: str,
    ) -> PromptBenchmarkResult:
        run_id = uuid4().hex
        with tempfile.TemporaryDirectory(prefix="evodev-prompt-benchmark.") as temp_dir:
            repository = Path(temp_dir) / "repository"
            shutil.copytree(
                case.source_directory,
                repository,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
            )
            self._initialize_repository(repository)
            task = TaskRead(
                repository_path=repository,
                issue_title=case.issue_title,
                issue_body=case.issue_body,
                test_command=case.test_command,
                constraints=[],
                max_iterations=case.max_iterations,
            )
            try:
                result = build_repair_workflow_service(
                    self.settings,
                    prompt_repository=prompt_repository,
                    experience_store=NullExperienceStore(),
                ).execute(run_id=run_id, task=task)
                return PromptBenchmarkResult(
                    benchmark_name=case.name,
                    succeeded=result["status"] == "succeeded",
                    retry_count=result.get("retry_count", 0),
                    prompt_tokens=result.get("prompt_tokens", 0),
                    completion_tokens=result.get("completion_tokens", 0),
                    duration_ms=result.get("duration_ms", 0),
                    error_code=result.get("error_code"),
                    error_message=result.get("error_message"),
                )
            finally:
                self._cleanup_run(run_id)

    @staticmethod
    def _initialize_repository(repository: Path) -> None:
        subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
        subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=EvoDev Benchmark",
                "-c",
                "user.email=benchmark@evodev.local",
                "commit",
                "--quiet",
                "-m",
                "初始化 Prompt 评测任务",
            ],
            check=True,
        )

    def _cleanup_run(self, run_id: str) -> None:
        WorkspaceManager(self.settings.workspaces_dir).remove(run_id)
        LocalArtifactStore(self.settings.outputs_dir).remove_run(run_id)
        PostgresCheckpointStore(self.settings.database_url).delete_thread(run_id)


def compare_prompt_results(
    baseline: list[PromptBenchmarkResult],
    candidate: list[PromptBenchmarkResult],
) -> tuple[bool, str]:
    """采用保守规则决定候选 Prompt 是否值得升级。"""
    if len(baseline) != len(candidate) or len(baseline) < 2:
        return False, "A/B 评测必须包含相同且不少于两个任务"
    pairs = zip(baseline, candidate, strict=True)
    if any(old.succeeded and not new.succeeded for old, new in pairs):
        return False, "候选 Prompt 导致原本成功的任务失败"
    baseline_success = sum(item.succeeded for item in baseline)
    candidate_success = sum(item.succeeded for item in candidate)
    if candidate_success < baseline_success:
        return False, "候选 Prompt 的成功任务数量下降"
    baseline_tokens = sum(item.prompt_tokens + item.completion_tokens for item in baseline)
    candidate_tokens = sum(item.prompt_tokens + item.completion_tokens for item in candidate)
    if baseline_tokens and candidate_tokens > baseline_tokens * 1.2:
        return False, "候选 Prompt 的 Token 用量增长超过 20%"
    baseline_retries = sum(item.retry_count for item in baseline)
    candidate_retries = sum(item.retry_count for item in candidate)
    if candidate_success > baseline_success:
        return True, "候选 Prompt 提高了任务成功数且没有产生回归"
    if candidate_retries < baseline_retries:
        return True, "成功数不变，候选 Prompt 减少了重试次数"
    if candidate_retries == baseline_retries and candidate_tokens < baseline_tokens:
        return True, "成功数和重试次数不变，候选 Prompt 降低了 Token 用量"
    return False, "候选 Prompt 没有产生可验证的改进"


def validate_prompt_guidance(guidance: str) -> None:
    """拒绝试图改变固定安全边界的候选指导。"""
    for pattern in FORBIDDEN_GUIDANCE_PATTERNS:
        if re.search(pattern, guidance, flags=re.IGNORECASE):
            raise ValueError("候选 Prompt 试图改变固定安全边界")


class PromptEvolutionWorker:
    """领取一个进化任务并完成候选生成、A/B 评测和版本决策。"""

    def __init__(
        self,
        *,
        prompt_store: PostgresPromptEvolutionStore,
        experience_store: PostgresExperienceStore,
        optimizer: PromptOptimizerProtocol,
        evaluator: PromptBenchmarkEvaluatorProtocol,
        model: str,
    ) -> None:
        self.prompt_store = prompt_store
        self.experience_store = experience_store
        self.optimizer = optimizer
        self.evaluator = evaluator
        self.catalog = default_agent_catalog(model)

    def run_once(self) -> tuple[PromptEvolutionJob, PromptVersion | None] | None:
        job = self.prompt_store.claim_next()
        if job is None:
            return None
        try:
            if job.agent_role not in EVOLVABLE_SCHEMAS:
                raise ValueError("首版只允许进化 analyst 或 developer")
            experiences = self.experience_store.list_for_evolution(limit=5)
            if len(experiences) < job.min_experiences:
                raise ValueError(
                    f"可用经验不足：需要 {job.min_experiences} 条，实际 {len(experiences)} 条"
                )
            agent = self.catalog[job.agent_role]
            current_prompt = PromptRepository(guidance_provider=self.prompt_store).render(
                agent, EVOLVABLE_SCHEMAS[job.agent_role]
            )
            optimization = self.optimizer.optimize(
                agent_role=job.agent_role,
                current_prompt=current_prompt,
                experiences=experiences,
            )
            validate_prompt_guidance(optimization.guidance)
            candidate = self.prompt_store.create_candidate(
                job_id=job.id,
                agent_role=job.agent_role,
                base_prompt_version=agent.prompt_version,
                optimization=optimization,
                source_experience_ids=[item.id for item in experiences],
            )
            comparison = self.evaluator.evaluate(
                agent_role=job.agent_role,
                candidate=candidate,
            )
            version = self.prompt_store.finish_evaluation(
                job_id=job.id,
                candidate_id=candidate.id,
                comparison=comparison,
            )
            return job, version
        except Exception as exc:
            self.prompt_store.fail_job(job.id, str(exc))
            raise


def build_prompt_evolution_worker(settings: Settings) -> PromptEvolutionWorker:
    prompt_store = PostgresPromptEvolutionStore(settings.database_url)
    return PromptEvolutionWorker(
        prompt_store=prompt_store,
        experience_store=PostgresExperienceStore(settings.database_url),
        optimizer=ModelPromptOptimizer(settings),
        evaluator=RepairPromptBenchmarkEvaluator(settings, prompt_store),
        model=settings.llm_model or "",
    )
