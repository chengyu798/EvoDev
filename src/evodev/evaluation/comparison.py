"""固定样例、提示词和经验快照，执行可审计的小样本对照。"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from evodev.agents.catalog import default_agent_catalog
from evodev.agents.prompting import PackagePromptSource, PromptRepository
from evodev.application.evolution import (
    NullExperienceStore,
    PromptBenchmarkCase,
    RepairPromptBenchmarkEvaluator,
)
from evodev.application.repair import build_repair_workflow_service
from evodev.config import Settings
from evodev.domain.experiences import Experience
from evodev.domain.tasks import TaskRead
from evodev.evaluation.costs import estimate_token_cost


class FrozenExperienceStore(NullExperienceStore):
    """沿用正式检索排序，但丢弃写入与反馈，防止组间污染。"""

    def __init__(self, experiences: list[Experience]) -> None:
        self.experiences = [item.model_copy(deep=True) for item in experiences]

    def search(self, *, task_type: str, tags: list[str], limit: int = 3) -> list[Experience]:
        selected = [
            item
            for item in self.experiences
            if item.task_type == task_type
            and item.status == "active"
            and set(item.tags).intersection(tags)
        ]
        selected.sort(
            key=lambda item: (
                len(set(item.tags).intersection(tags)),
                item.quality_score,
                item.usage_count,
                item.created_at,
            ),
            reverse=True,
        )
        return [item.model_copy(deep=True) for item in selected[: max(0, limit)]]

    def get_many(self, experience_ids: list[UUID]) -> list[Experience]:
        by_id = {item.id: item for item in self.experiences}
        return [by_id[item].model_copy(deep=True) for item in experience_ids if item in by_id]


class FrozenPromptSource:
    """整次对照复用内存中的模板，不读取运行中修改的文件。"""

    def __init__(self, templates: dict[str, str]) -> None:
        self.templates = templates

    def read(self, prompt_file: str) -> str:
        return self.templates[prompt_file]


def summarize(rows: list[dict]) -> dict:
    """失败计入分母；缺失计量不伪装为零。"""
    result = {}
    for variant in ("baseline", "experience"):
        group = [row for row in rows if row["variant"] == variant]
        count = len(group)
        summary = {
            "attempts": count,
            "task_success_rate": sum(row["status"] == "succeeded" for row in group) / count
            if count
            else None,
            "test_pass_rate": sum(row.get("tests_passed") is True for row in group) / count
            if count
            else None,
        }
        for key in ("prompt_tokens", "completion_tokens", "retry_count", "duration_ms"):
            values = [row.get(key) for row in group]
            total = sum(values) if values and all(value is not None for value in values) else None
            summary[f"total_{key}"] = total
            summary[f"average_{key}"] = total / count if total is not None else None
        result[variant] = summary
    return result


def load_inputs(
    benchmark_file: Path, experience_file: Path
) -> tuple[list[PromptBenchmarkCase], list[Experience]]:
    cases = TypeAdapter(list[PromptBenchmarkCase]).validate_json(benchmark_file.read_text())
    if len(cases) < 2:
        raise ValueError("对照至少需要两个不同样例")
    for case in cases:
        case.source_directory = (benchmark_file.parent / case.source_directory).resolve()
        if not case.source_directory.is_dir():
            raise ValueError(f"样例目录不存在：{case.source_directory}")
    if len({case.source_directory for case in cases}) != len(cases):
        raise ValueError("样例目录不能重复")
    raw = json.loads(experience_file.read_text())
    experiences = TypeAdapter(list[Experience]).validate_python(
        raw if isinstance(raw, list) else [raw]
    )
    if not any(item.status == "active" for item in experiences):
        raise ValueError("经验快照至少包含一条启用经验")
    return cases, experiences


def run_comparison(
    settings: Settings,
    cases: list[PromptBenchmarkCase],
    experiences: list[Experience],
    output: Path,
) -> dict:
    """仅由显式执行入口调用；保留每轮产物和中间报告。"""
    if output.exists():
        raise ValueError("报告路径已存在，请指定新文件，避免覆盖证据")
    settings = settings.model_copy(update={"prompt_evolution_auto_enqueue": False})
    catalog = default_agent_catalog(settings.llm_model or "")
    source = PackagePromptSource()
    templates = {agent.prompt_file: source.read(agent.prompt_file) for agent in catalog.values()}
    prompts = PromptRepository(source=FrozenPromptSource(templates))
    report = {
        "kind": "experience_comparison",
        "status": "running",
        "sample_size": len(cases),
        "model": settings.llm_model,
        "scope": "小样本验证，不能推断普遍效果；固定基础 Prompt，不加载进化指导层",
        "prompts": templates,
        "prompt_sha256": hashlib.sha256(json.dumps(templates, sort_keys=True).encode()).hexdigest(),
        "experience_snapshot": [item.model_dump(mode="json") for item in experiences],
        "runs": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save() -> None:
        report["summary"] = summarize(report["runs"])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    for index, case in enumerate(cases):
        with tempfile.TemporaryDirectory(prefix="evodev-comparison.") as temporary:
            repository = Path(temporary) / "repository"
            shutil.copytree(
                case.source_directory,
                repository,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
            )
            RepairPromptBenchmarkEvaluator._initialize_repository(repository)
            commit = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
            ).strip()
            # 交替执行组别，减轻固定先后顺序造成的偏差。
            variants = ("baseline", "experience") if index % 2 == 0 else ("experience", "baseline")
            for variant in variants:
                run_id = uuid4().hex
                task = TaskRead(
                    repository_path=repository,
                    issue_title=case.issue_title,
                    issue_body=case.issue_body,
                    test_command=case.test_command,
                    constraints=["保持公开函数签名和测试文件不变"],
                    max_iterations=case.max_iterations,
                )
                row = {
                    "run_id": run_id,
                    "variant": variant,
                    "benchmark_name": case.name,
                    "base_commit": commit,
                    "task": task.model_dump(mode="json"),
                }
                store = (
                    FrozenExperienceStore(experiences)
                    if variant == "experience"
                    else NullExperienceStore()
                )
                try:
                    state = build_repair_workflow_service(
                        settings, prompt_repository=prompts, experience_store=store
                    ).execute(run_id=run_id, task=task)
                    row.update(
                        {
                            key: state.get(key)
                            for key in (
                                "status",
                                "retry_count",
                                "prompt_tokens",
                                "completion_tokens",
                                "duration_ms",
                                "error_code",
                                "error_message",
                                "retrieved_experience_ids",
                            )
                        }
                    )
                    evaluation = Path(settings.outputs_dir) / run_id / "evaluation.json"
                    row["tests_passed"] = (
                        json.loads(evaluation.read_text()).get("tests_passed")
                        if evaluation.exists()
                        else False
                    )
                except Exception as exc:
                    # 不输出异常正文，避免供应商错误中包含凭据或请求内容。
                    row.update(status="failed", error_code=type(exc).__name__, tests_passed=False)
                if (
                    row.get("prompt_tokens") is not None
                    and row.get("completion_tokens") is not None
                ):
                    row["cost"] = estimate_token_cost(
                        row["prompt_tokens"],
                        row["completion_tokens"],
                        input_price_per_million=settings.llm_input_price_per_million,
                        output_price_per_million=settings.llm_output_price_per_million,
                        currency=settings.llm_cost_currency,
                    ).model_dump()
                else:
                    row["cost"] = {
                        "status": "unknown_usage",
                        "amount": None,
                        "currency": settings.llm_cost_currency,
                    }
                report["runs"].append(row)
                save()
    report["status"] = "completed"
    save()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="经验对照评测：默认仅检查本地输入，不调用模型")
    parser.add_argument(
        "--benchmarks", type=Path, default=Path("examples/prompt-evolution-benchmarks.json")
    )
    parser.add_argument("--experience-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/experience-comparison.json"))
    parser.add_argument("--execute", action="store_true", help="明确允许发送样例和经验并调用模型")
    args = parser.parse_args()
    cases, experiences = load_inputs(args.benchmarks.resolve(), args.experience_file)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "preflight",
                    "cases": [case.name for case in cases],
                    "experience_count": len(experiences),
                    "planned_runs": len(cases) * 2,
                    "message": "未调用模型。执行前确认模型、Docker、数据库、数据发送授权和费用。",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    run_comparison(Settings(), cases, experiences, args.output)
    print(f"评测证据已保存：{args.output}")


if __name__ == "__main__":
    main()
