// 展示单个会话中的消息、计划版本和多次修复运行。
import {
  ArrowUpIcon,
  BracketsCurlyIcon,
  CheckCircleIcon,
  CodeIcon,
  EyeIcon,
  PlayIcon,
  RobotIcon,
  SpinnerGapIcon,
  StopCircleIcon,
  UserIcon,
} from "@phosphor-icons/react";
import { useMemo, useState, type FormEvent } from "react";

import type { AgentTrace, RunArtifactBundle, RunEvent, Task, TaskPlan, TaskRun } from "../api/client";
import { statusLabels, terminalStatuses } from "../runStatus";

type SessionWorkspaceProps = {
  task: Task;
  runs: TaskRun[];
  selectedRun: TaskRun | null;
  events: RunEvent[];
  artifacts: RunArtifactBundle | null;
  pending: boolean;
  onSelectRun: (run: TaskRun) => void;
  onSend: (content: string) => Promise<boolean>;
  onRetry: () => Promise<void>;
  onStartPlan: (plan: TaskPlan) => Promise<void>;
  onCancel: () => Promise<void>;
  onOpenEvidence: () => void;
};

const agentNames: Record<string, string> = {
  analyst: "问题分析智能体",
  developer: "代码实现智能体",
  "failure-analyzer": "失败诊断智能体",
  reviewer: "补丁审查智能体",
};

const nodeNames: Record<string, string> = {
  prepare_workspace: "准备隔离工作区",
  run_baseline_tests: "运行基线测试",
  analyze_issue: "分析问题原因",
  implement_patch: "修改代码",
  run_tests: "验证测试结果",
  diagnose_failure: "诊断失败原因",
  review_patch: "审查代码补丁",
  final_evaluation: "汇总运行结果",
};

const toolNames: Record<string, string> = {
  list_files: "检查仓库文件",
  read_file: "读取相关代码",
  search_text: "搜索代码内容",
  git_diff: "检查代码差异",
  apply_patch: "应用代码修改",
  run_command: "运行诊断命令",
};

function traceTitle(trace: AgentTrace): string {
  const role = trace.agent_id?.split("@")[0] ?? "";
  return agentNames[role] ?? "执行智能体";
}

function traceSummary(trace: AgentTrace): string {
  const output = trace.output ?? {};
  const value = output.summary ?? output.problem_summary ?? output.failure_summary ?? output.root_cause;
  return typeof value === "string" ? value : "已完成当前步骤，详细结果可以在右侧证据栏查看。";
}

function eventText(event: RunEvent): string {
  const agentName = typeof event.payload.agent_name === "string" ? event.payload.agent_name : "智能体";
  const tool = typeof event.payload.tool === "string" ? event.payload.tool : "";
  if (event.event_type === "agent.started") return `${agentName}开始工作`;
  if (event.event_type === "agent.completed") return `${agentName}已完成`;
  if (event.event_type === "tool.started") return toolNames[tool] ?? `调用工具 ${tool}`;
  if (event.event_type === "tool.completed") return `${toolNames[tool] ?? tool}已完成`;
  if (event.event_type === "run.created") return "已创建隔离运行";
  if (event.event_type === "run.started") return "修复流程已启动";
  if (event.event_type === "run.completed") return "修复流程已完成";
  if (event.event_type === "run.failed") return "修复流程未完成";
  if (event.event_type === "run.cancelled") return "修复流程已停止";
  if (event.event_type === "node.completed") {
    return `${nodeNames[event.node_name ?? ""] ?? "工作流步骤"}已完成`;
  }
  return nodeNames[event.node_name ?? ""] ?? "同步运行状态";
}

function TraceDetails({ trace }: { trace: AgentTrace }) {
  const output = trace.output ?? {};
  const details = [
    ["判断依据", output.likely_root_cause ?? output.root_cause],
    ["执行内容", output.implementation_steps ?? output.suggested_changes ?? output.requirement_coverage],
    ["修改文件", output.changed_files],
    ["下一步", output.required_changes],
  ].filter(([, value]) => typeof value === "string" || (Array.isArray(value) && value.length));
  return details.length ? (
    <dl className="trace-details">
      {details.map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{Array.isArray(value) ? value.join("；") : String(value)}</dd></div>)}
    </dl>
  ) : null;
}

function PlanCard({ plan, previous, pending, onStart }: { plan: TaskPlan; previous?: TaskPlan; pending: boolean; onStart: () => Promise<void> }) {
  const isDraft = plan.status === "draft";
  const canRun = plan.status !== "superseded";
  return (
    <article className={`plan-card${isDraft ? " is-current" : ""}`}>
      <header>
        <div><span>计划 {plan.version}</span><strong>{isDraft ? "等待你的确认" : plan.status === "approved" ? "已确认" : "历史版本"}</strong></div>
        {canRun ? <button className="plan-start" type="button" disabled={pending} onClick={() => void onStart()}><PlayIcon size={16} weight="fill" />{pending ? "正在启动" : isDraft ? "启动修复" : "再次运行"}</button> : null}
      </header>
      <p>{plan.problem_summary}</p>
      {previous ? <details className="plan-changes"><summary>相对计划 {previous.version} 的调整</summary><ul>{([
        ["问题判断", plan.problem_summary !== previous.problem_summary || plan.likely_root_cause !== previous.likely_root_cause],
        ["涉及文件", JSON.stringify(plan.relevant_files) !== JSON.stringify(previous.relevant_files)],
        ["实施步骤", JSON.stringify(plan.implementation_steps) !== JSON.stringify(previous.implementation_steps)],
        ["验证方式", JSON.stringify(plan.validation_steps) !== JSON.stringify(previous.validation_steps)],
        ["风险说明", JSON.stringify(plan.risks) !== JSON.stringify(previous.risks)],
      ] as const).filter(([, changed]) => changed).map(([label]) => <li key={label}>{label}已更新，请重新确认。</li>)}</ul></details> : null}
      <div className="plan-section"><strong>判断依据</strong><p>{plan.likely_root_cause}</p></div>
      {plan.relevant_files.length ? <div className="plan-files">{plan.relevant_files.map((file) => <code key={file}>{file}</code>)}</div> : null}
      <ol>{plan.implementation_steps.map((step) => <li key={step}>{step}</li>)}</ol>
      {plan.validation_steps.length ? <div className="plan-section"><strong>验证方式</strong><p>{plan.validation_steps.join("；")}</p></div> : null}
      {plan.risks.length ? <details><summary>查看风险说明</summary><ul>{plan.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul></details> : null}
      {isDraft ? <small>需要调整时，直接在下方输入补充要求；计划更新后再启动。</small> : null}
    </article>
  );
}

export function SessionWorkspace(props: SessionWorkspaceProps) {
  const { task, runs, selectedRun, events, artifacts, pending, onSelectRun, onSend, onRetry, onStartPlan, onCancel, onOpenEvidence } = props;
  const [message, setMessage] = useState("");
  const active = selectedRun && !terminalStatuses.has(selectedRun.status);
  const orderedPlans = useMemo(() => [...task.plans].sort((a, b) => a.version - b.version), [task.plans]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const content = message.trim();
    if (!content) return;
    if (await onSend(content)) setMessage("");
  }

  return (
    <section className="session-workspace">
      <header className="session-header">
        <div><span>{task.repository_path.split("/").filter(Boolean).at(-1)}</span><h1>{task.issue_title}</h1></div>
        <div className="session-header__actions">
          {runs.length > 1 ? (
            <select aria-label="选择运行记录" value={selectedRun?.id ?? ""} onChange={(event) => {
              const run = runs.find((item) => item.id === event.target.value);
              if (run) onSelectRun(run);
            }}>
              {runs.map((run, index) => <option value={run.id} key={run.id}>运行 {runs.length - index}：{statusLabels[run.status]}</option>)}
            </select>
          ) : null}
          {selectedRun ? <button className="evidence-trigger" type="button" onClick={onOpenEvidence}><EyeIcon size={17} />查看证据</button> : null}
        </div>
      </header>

      <div className="message-scroll">
        <div className="message-stream">
          {task.messages.length === 0 ? (
            <article className="chat-message chat-message--user">
              <span className="chat-avatar"><UserIcon size={17} weight="fill" /></span>
              <div><header><strong>你</strong><span>历史任务</span></header><p>{task.issue_body}</p></div>
            </article>
          ) : null}
          {task.messages.map((item) => (
            <article className={`chat-message chat-message--${item.role}`} key={item.id}>
              <span className="chat-avatar">{item.role === "user" ? <UserIcon size={17} weight="fill" /> : item.role === "system" ? <CheckCircleIcon size={18} /> : <BracketsCurlyIcon size={18} weight="bold" />}</span>
              <div>
                <header><strong>{item.role === "user" ? "你" : item.agent_name ?? "EvoDev"}</strong>{item.intent ? <span>{item.intent === "explain" ? "问题解答" : item.intent === "modify" ? "准备处理" : item.intent === "clarify" ? "等待确认" : "系统状态"}</span> : null}</header>
                <p>{item.content}</p>
              </div>
            </article>
          ))}

          {task.planning_status === "failed" ? <div className="readable-error" role="alert"><strong>本次分析未完成</strong><p>{task.planning_error || "请缩小问题范围后重试。"}</p><small>尚未启动新的修复，你可以补充具体文件和错误信息，或重试上一条请求（不会重复添加消息）。</small><button className="evidence-follow" type="button" disabled={pending} onClick={() => void onRetry()}>重试分析</button></div> : null}
          {pending || task.planning_status === "planning" ? <p role="status">正在分析请求，请稍候；此时不会自动启动修复。</p> : null}
          {orderedPlans.map((plan, index) => plan.status === "superseded" ? <details className="historical-plan" key={plan.id}><summary>查看历史计划 {plan.version}</summary><PlanCard plan={plan} previous={orderedPlans[index - 1]} pending={pending} onStart={() => onStartPlan(plan)} /></details> : <PlanCard key={plan.id} plan={plan} previous={orderedPlans[index - 1]} pending={pending} onStart={() => onStartPlan(plan)} />)}

          {selectedRun ? (
            <article className="run-message">
              <header>
                <span className={`run-state run-state--${selectedRun.status}`}>{active ? <SpinnerGapIcon size={17} /> : <CheckCircleIcon size={17} />}{statusLabels[selectedRun.status]}</span>
                {active ? <button type="button" disabled={pending} onClick={() => void onCancel()}><StopCircleIcon size={16} />停止运行</button> : null}
              </header>
              <div className="live-steps">
                {events.length ? events.slice(-12).map((event) => <span key={event.id}><CheckCircleIcon size={14} />{eventText(event)}</span>) : <span><SpinnerGapIcon size={14} />正在准备执行环境</span>}
              </div>
              {selectedRun.error_message ? <div className="readable-error"><strong>本次运行未完成</strong><p>{selectedRun.error_message}</p></div> : null}
            </article>
          ) : null}

          {artifacts?.agent_traces.map((trace, index) => (
            <article className="chat-message chat-message--agent" key={`${trace.agent_id}-${index}`}>
              <span className="chat-avatar"><RobotIcon size={18} /></span>
              <div>
                <header><strong>{traceTitle(trace)}</strong><span>执行结果</span></header>
                <p>{traceSummary(trace)}</p>
                <TraceDetails trace={trace} />
                <button className="inline-evidence" type="button" onClick={onOpenEvidence}><CodeIcon size={15} />查看工具调用与原始证据</button>
              </div>
            </article>
          ))}
        </div>
      </div>

      <div className="conversation-composer-wrap">
        {active ? <p className="composer-context">当前修复仍在运行。你可以继续提问或补充要求，新计划不会覆盖本次运行。</p> : null}
        <form className="conversation-composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="conversation-message">继续对话</label>
          <textarea id="conversation-message" rows={2} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="询问原因，或明确说明需要继续修改的内容" disabled={pending} />
          <button type="submit" aria-label="发送消息" disabled={pending || !message.trim()}><ArrowUpIcon size={18} weight="bold" /></button>
        </form>
        <span className="composer-hint">对话智能体默认只读；明确要求处理后会先生成计划。</span>
      </div>
    </section>
  );
}
