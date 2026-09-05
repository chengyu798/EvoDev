// 以对话形式串联用户任务、执行状态和 LangGraph 工作流。
import {
  ArrowClockwiseIcon,
  BracketsCurlyIcon,
  CheckCircleIcon,
  CircleIcon,
  ClockIcon,
  GitDiffIcon,
  SpinnerGapIcon,
  StopCircleIcon,
  TestTubeIcon,
  UserIcon,
} from "@phosphor-icons/react";
import { useState } from "react";

import type { RunEvent, Task, TaskRun } from "../api/client";
import { statusLabels, terminalStatuses } from "../runStatus";
import { StatusBadge } from "./StatusBadge";

const graphNodes = [
  ["prepare_workspace", "准备工作区", "创建隔离副本"],
  ["run_baseline_tests", "基准测试", "记录修改前结果"],
  ["analyze_issue", "问题分析", "定位根因"],
  ["implement_patch", "代码修改", "生成候选补丁"],
  ["run_tests", "测试验证", "运行确定性测试"],
  ["diagnose_failure", "失败诊断", "分析未通过原因"],
  ["review_patch", "补丁审查", "检查风险和回归"],
  ["final_evaluation", "汇总结果", "保存证据与经验"],
] as const;

type RunOverviewProps = {
  run: TaskRun;
  task: Task | null;
  events: RunEvent[];
  actionPending: boolean;
  onCancel: () => Promise<void>;
  onRerun: () => Promise<void>;
};

function repositoryName(path: string | undefined): string {
  if (!path) return "未知仓库";
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function formatDuration(milliseconds: number): string {
  if (!milliseconds) return "等待统计";
  if (milliseconds < 1000) return `${milliseconds} 毫秒`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  return `${Math.floor(milliseconds / 60_000)} 分 ${Math.round((milliseconds % 60_000) / 1000)} 秒`;
}

function responseSummary(run: TaskRun): string {
  if (run.status === "succeeded") return "修复已经完成，测试与补丁审查均已通过。你可以继续查看完整证据。";
  if (run.status === "failed") return "这次运行没有完成。我已经保留失败原因和当前可用的执行证据。";
  if (run.status === "cancelled") return "运行已经取消，已产生的执行记录仍然可以查看。";
  return `正在执行${statusLabels[run.status]}，页面会自动同步最新进度。`;
}

export function RunOverview({
  run,
  task,
  events,
  actionPending,
  onCancel,
  onRerun,
}: RunOverviewProps) {
  const [confirmingAction, setConfirmingAction] = useState<"cancel" | "rerun" | null>(null);
  const completedNodes = new Set(events.map((event) => event.node_name).filter(Boolean));
  const isTerminal = terminalStatuses.has(run.status);
  const testsLabel = run.tests_passed === null ? "等待验证" : run.tests_passed ? "全部通过" : "存在失败";

  async function handleConfirmedAction(action: "cancel" | "rerun") {
    if (confirmingAction !== action) {
      setConfirmingAction(action);
      return;
    }
    if (action === "cancel") await onCancel();
    else await onRerun();
    setConfirmingAction(null);
  }

  return (
    <div className="conversation-stack">
      <article className="conversation-message conversation-message--user">
        <span className="conversation-avatar conversation-avatar--user"><UserIcon size={18} weight="fill" /></span>
        <div className="conversation-message__body">
          <div className="conversation-meta">
            <strong>你的任务</strong>
            <span>{repositoryName(task?.repository_path)}</span>
          </div>
          <h1>{task?.issue_title ?? "代码修复任务"}</h1>
          <p>{task?.issue_body ?? "正在读取任务信息。"}</p>
        </div>
      </article>

      <article className="conversation-message conversation-message--assistant">
        <span className="conversation-avatar conversation-avatar--assistant"><BracketsCurlyIcon size={19} weight="bold" /></span>
        <div className="conversation-message__body">
          <header className="assistant-response__header">
            <div>
              <div className="assistant-response__identity">
                <strong>EvoDev</strong>
                <StatusBadge
                  label={statusLabels[run.status]}
                  tone={run.status === "succeeded" ? "ready" : isTerminal ? "offline" : "pending"}
                />
              </div>
              <p>{responseSummary(run)}</p>
            </div>
            <div className="run-header__actions">
              {isTerminal ? (
                <button
                  className={`secondary-action${confirmingAction === "rerun" ? " is-confirming" : ""}`}
                  type="button"
                  disabled={actionPending}
                  onBlur={() => setConfirmingAction(null)}
                  onClick={() => handleConfirmedAction("rerun")}
                >
                  <ArrowClockwiseIcon size={17} />
                  {actionPending ? "正在启动" : confirmingAction === "rerun" ? "确认重新运行" : "重新运行"}
                </button>
              ) : (
                <button
                  className={`secondary-action secondary-action--danger${confirmingAction === "cancel" ? " is-confirming" : ""}`}
                  type="button"
                  disabled={actionPending}
                  onBlur={() => setConfirmingAction(null)}
                  onClick={() => handleConfirmedAction("cancel")}
                >
                  <StopCircleIcon size={17} />
                  {actionPending ? "正在取消" : confirmingAction === "cancel" ? "确认取消运行" : "取消运行"}
                </button>
              )}
            </div>
          </header>

          <dl className="metric-strip" aria-label="运行指标">
            <div>
              <dt><TestTubeIcon size={16} />测试结果</dt>
              <dd className={run.tests_passed === false ? "metric-error" : ""}>{testsLabel}</dd>
            </div>
            <div>
              <dt><GitDiffIcon size={16} />修改文件</dt>
              <dd>{run.changed_files.length} 个</dd>
            </div>
            <div>
              <dt><ArrowClockwiseIcon size={16} />修复轮次</dt>
              <dd>{run.iteration} / {run.max_iterations}</dd>
            </div>
            <div>
              <dt><ClockIcon size={16} />执行耗时</dt>
              <dd>{formatDuration(run.duration_ms)}</dd>
            </div>
          </dl>

          <section className="workflow-panel" aria-labelledby="workflow-heading">
            <div className="section-heading">
              <div>
                <h2 id="workflow-heading">修复工作流</h2>
                <p>{isTerminal ? "工作流已经结束，可以查看下方完整证据。" : `当前正在执行：${statusLabels[run.status]}`}</p>
              </div>
              <span>{events.length} 条状态记录</span>
            </div>

            <ol className="workflow-track">
              {graphNodes.map(([node, label, description]) => {
                const isCurrent = run.current_node === node;
                const isDone = completedNodes.has(node);
                const isSkipped = isTerminal && !isDone;
                return (
                  <li className={isCurrent ? "is-current" : isDone ? "is-done" : isSkipped ? "is-skipped" : ""} key={node}>
                    <span className="workflow-track__icon" aria-hidden="true">
                      {isCurrent ? <SpinnerGapIcon size={18} /> : isDone ? <CheckCircleIcon size={18} weight="fill" /> : <CircleIcon size={18} />}
                    </span>
                    <strong>{label}</strong>
                    <small>{isCurrent ? "正在执行" : isDone ? "已经完成" : isSkipped ? "本次未触发" : description}</small>
                  </li>
                );
              })}
            </ol>

            {run.error_message ? (
              <div className="run-error" role="alert">
                <strong>运行未能完成</strong>
                <span>{run.error_message}</span>
              </div>
            ) : null}
          </section>
        </div>
      </article>
    </div>
  );
}
