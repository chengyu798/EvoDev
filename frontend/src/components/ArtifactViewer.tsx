// 通过选项卡组织测试、智能体、代码和经验等运行证据。
import {
  BrainIcon,
  CheckCircleIcon,
  ClipboardIcon,
  CodeIcon,
  FileCodeIcon,
  InfoIcon,
  RobotIcon,
  TestTubeIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import { useMemo, useState, type KeyboardEvent } from "react";

import type { AgentTrace, RunArtifactBundle, TaskRun, TestResult } from "../api/client";

type ArtifactViewerProps = {
  run: TaskRun;
  artifacts: RunArtifactBundle | null;
  loading: boolean;
  suggestedTab?: ArtifactTab;
};

export type ArtifactTab = "summary" | "tests" | "agents" | "diff" | "experience";

const agentLabels: Record<string, string> = {
  analyst: "问题分析智能体",
  developer: "代码实现智能体",
  "failure-analyzer": "失败诊断智能体",
  reviewer: "补丁审查智能体",
};

const evaluationLabels: Record<string, string> = {
  tests_passed: "测试是否通过",
  review_passed: "审查是否通过",
  changed_files: "修改文件",
  iteration: "修复轮次",
  retry_count: "失败重试次数",
};

function formatDuration(milliseconds: number | undefined): string {
  if (!milliseconds) return "未记录";
  return milliseconds < 1000 ? `${milliseconds} 毫秒` : `${(milliseconds / 1000).toFixed(1)} 秒`;
}

function TestEvidence({ title, result }: { title: string; result: TestResult }) {
  const output = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
  const passed = result.exit_code === 0;
  return (
    <article className="test-result">
      <div className="test-result__summary">
        <span className={passed ? "result-icon result-icon--success" : "result-icon result-icon--error"}>
          {passed ? <CheckCircleIcon size={20} weight="fill" /> : <XCircleIcon size={20} weight="fill" />}
        </span>
        <div>
          <strong>{title}</strong>
          <span>{result.command?.join(" ") ?? "未记录测试命令"}</span>
        </div>
        <dl>
          <div><dt>结果</dt><dd>{passed ? "通过" : `退出码 ${result.exit_code ?? "未知"}`}</dd></div>
          <div><dt>耗时</dt><dd>{formatDuration(result.duration_ms)}</dd></div>
        </dl>
      </div>
      <details className="raw-output">
        <summary>查看完整终端输出</summary>
        <pre>{output || "没有终端输出"}</pre>
      </details>
    </article>
  );
}

function traceSummary(trace: AgentTrace): string {
  const summary = trace.output?.summary ?? trace.output?.problem_summary ?? trace.output?.failure_summary;
  return typeof summary === "string" ? summary : "该智能体已经返回结构化结果。";
}

function traceLabel(agentId: string | undefined): string {
  const prefix = agentId?.split("@")[0] ?? "";
  return agentLabels[prefix] ?? "未知智能体";
}

function stringifyValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.length ? value.map(String).join("、") : "无";
  if (value === null || value === undefined || value === "") return "未记录";
  return String(value);
}

function DiffViewer({ patch }: { patch: string | null }) {
  const [copied, setCopied] = useState(false);
  const lines = (patch ?? "").split("\n");
  const files = useMemo(() => {
    const result = new Set<string>();
    lines.forEach((line) => {
      if (line.startsWith("+++ b/")) result.add(line.slice(6));
      if (line.startsWith("diff --git a/")) result.add(line.split(" b/").at(-1) ?? "");
    });
    return [...result].filter(Boolean);
  }, [lines]);
  const additions = lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length;
  const deletions = lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length;

  async function copyPatch() {
    if (!patch) return;
    await navigator.clipboard.writeText(patch);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  if (!patch) {
    return <div className="content-empty"><FileCodeIcon size={28} /><strong>尚未生成代码差异</strong><span>代码修改完成后会在这里显示补丁。</span></div>;
  }

  return (
    <div className="diff-layout">
      <aside className="diff-files">
        <div className="diff-files__title">修改文件</div>
        {files.length ? files.map((file) => <span key={file}><FileCodeIcon size={15} />{file}</span>) : <span><FileCodeIcon size={15} />当前补丁</span>}
      </aside>
      <div className="diff-content">
        <div className="diff-toolbar">
          <div><span className="addition-count">+{additions}</span><span className="deletion-count">-{deletions}</span></div>
          <button className="text-button" type="button" onClick={copyPatch}>
            <ClipboardIcon size={15} />{copied ? "已经复制" : "复制补丁"}
          </button>
        </div>
        <pre className="diff-viewer">
          {lines.map((line, index) => {
            const kind = line.startsWith("+") ? "is-addition" : line.startsWith("-") ? "is-deletion" : line.startsWith("@@") ? "is-position" : "";
            return <code className={kind} key={`${index}-${line}`}><span>{index + 1}</span>{line || " "}</code>;
          })}
        </pre>
      </div>
    </div>
  );
}

export function ArtifactViewer({ run, artifacts, loading, suggestedTab = "summary" }: ArtifactViewerProps) {
  const [activeTab, setActiveTab] = useState<ArtifactTab>(suggestedTab);
  const [manuallySelected, setManuallySelected] = useState(false);
  const currentTab = manuallySelected ? activeTab : suggestedTab;

  const tabs: { id: ArtifactTab; label: string; icon: typeof InfoIcon; count?: number }[] = [
    { id: "summary", label: "执行摘要", icon: InfoIcon },
    { id: "tests", label: "测试报告", icon: TestTubeIcon, count: artifacts ? Number(Boolean(artifacts.baseline_test)) + artifacts.verification_tests.length : undefined },
    { id: "agents", label: "智能体轨迹", icon: RobotIcon, count: artifacts?.agent_traces.length },
    { id: "diff", label: "代码变更", icon: CodeIcon, count: run.changed_files.length },
    { id: "experience", label: "经验记录", icon: BrainIcon, count: run.retrieved_experience_ids.length + Number(Boolean(run.generated_experience_id)) },
  ];

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    let nextIndex: number;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = tabs.length - 1;
    else return;
    event.preventDefault();
    setActiveTab(tabs[nextIndex].id);
    setManuallySelected(true);
    const tabButtons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']");
    tabButtons?.[nextIndex]?.focus();
  }

  if (loading) {
    return <div className="artifact-shell artifact-shell--loading" aria-label="正在读取运行产物"><span /><span /><span /></div>;
  }

  return (
    <section className="artifact-shell" aria-label="运行产物">
      <button className="evidence-follow" type="button" aria-pressed={!manuallySelected} onClick={() => setManuallySelected(false)}>{manuallySelected ? "恢复自动跟随运行阶段" : "正在自动跟随运行阶段"}</button>
      <div className="artifact-tabs" role="tablist" aria-label="运行证据分类">
        {tabs.map(({ id, label, icon: Icon, count }, index) => (
          <button
            aria-controls="artifact-tab-panel"
            aria-selected={currentTab === id}
            className={currentTab === id ? "is-active" : ""}
            id={`artifact-tab-${id}`}
            key={id}
            role="tab"
            tabIndex={currentTab === id ? 0 : -1}
            type="button"
            onClick={() => { setActiveTab(id); setManuallySelected(true); }}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            <Icon size={17} />
            <span>{label}</span>
            {count !== undefined && count > 0 ? <small>{count}</small> : null}
          </button>
        ))}
      </div>

      <div className="artifact-content" id="artifact-tab-panel" role="tabpanel" aria-labelledby={`artifact-tab-${currentTab}`}>
        {currentTab === "summary" ? (
          <div className="summary-view">
            <div className={`outcome-banner outcome-banner--${run.status}`}>
              {run.status === "succeeded" ? <CheckCircleIcon size={30} weight="fill" /> : run.status === "failed" ? <XCircleIcon size={30} weight="fill" /> : <InfoIcon size={30} weight="fill" />}
              <div>
                <strong>{run.status === "succeeded" ? "修复已经通过验证" : run.status === "failed" ? "本次修复未能完成" : "任务正在执行"}</strong>
                <span>{run.status === "succeeded" ? "确定性测试和补丁审查均已完成。" : run.error_message ?? "工作流结束后将在这里显示最终结论。"}</span>
              </div>
            </div>
            <dl className="summary-grid">
              <div><dt>测试验证</dt><dd>{run.tests_passed === null ? "等待结果" : run.tests_passed ? "已经通过" : "未通过"}</dd></div>
              <div><dt>补丁审查</dt><dd>{run.review_passed === null ? "等待结果" : run.review_passed ? "已经通过" : "未通过"}</dd></div>
              <div><dt>模型输入用量</dt><dd>{run.prompt_tokens.toLocaleString("zh-CN")}</dd></div>
              <div><dt>模型输出用量</dt><dd>{run.completion_tokens.toLocaleString("zh-CN")}</dd></div>
              <div><dt>模型费用估算</dt><dd>{run.cost_estimate?.amount == null ? "未配置单价" : `${run.cost_estimate.amount.toLocaleString("zh-CN", { maximumFractionDigits: 6 })} ${run.cost_estimate.currency}`}</dd></div>
              <div><dt>复用历史经验</dt><dd>{run.retrieved_experience_ids.length} 条</dd></div>
              <div><dt>失败重试</dt><dd>{run.retry_count} 次</dd></div>
            </dl>
            {artifacts?.evaluation ? (
              <div className="evaluation-block">
                <h3>最终评测数据</h3>
                <dl>{Object.entries(artifacts.evaluation).map(([key, value]) => <div key={key}><dt>{evaluationLabels[key] ?? "其他评测指标"}</dt><dd>{stringifyValue(value)}</dd></div>)}</dl>
              </div>
            ) : null}
          </div>
        ) : null}

        {currentTab === "tests" ? (
          <div className="test-list">
            {artifacts?.baseline_test ? <TestEvidence title="修改前基准测试" result={artifacts.baseline_test} /> : null}
            {artifacts?.verification_tests.map((result, index) => <TestEvidence key={index} title={`第 ${index + 1} 轮修改后测试`} result={result} />)}
            {!artifacts?.baseline_test && !artifacts?.verification_tests.length ? <div className="content-empty"><TestTubeIcon size={28} /><strong>还没有测试结果</strong><span>测试节点执行后会在这里显示验证证据。</span></div> : null}
          </div>
        ) : null}

        {currentTab === "agents" ? (
          <div className="agent-timeline">
            {artifacts?.agent_traces.map((trace, index) => (
              <article key={`${trace.agent_id}-${index}`}>
                <span className="agent-timeline__marker"><RobotIcon size={18} /></span>
                <div className="agent-timeline__body">
                  <div className="agent-timeline__heading">
                    <div><strong>{traceLabel(trace.agent_id)}</strong><span>{trace.agent_id ?? "未记录标识"}</span></div>
                    <small>{formatDuration(trace.duration_ms)}</small>
                  </div>
                  <p>{traceSummary(trace)}</p>
                  <dl>
                    <div><dt>模型</dt><dd>{trace.model ?? "未记录"}</dd></div>
                    <div><dt>提示词版本</dt><dd>{trace.prompt_version ?? "未记录"}</dd></div>
                    <div><dt>工具调用</dt><dd>{trace.tool_calls?.length ?? 0} 次</dd></div>
                    <div><dt>模型用量</dt><dd>{(trace.prompt_tokens ?? 0) + (trace.completion_tokens ?? 0)}</dd></div>
                  </dl>
                  {trace.tool_calls?.length ? <details className="tool-calls"><summary>查看工具调用记录</summary><pre>{JSON.stringify(trace.tool_calls, null, 2)}</pre></details> : null}
                </div>
              </article>
            ))}
            {!artifacts?.agent_traces.length ? <div className="content-empty"><RobotIcon size={28} /><strong>还没有智能体记录</strong><span>智能体完成推理后会在这里保留轨迹。</span></div> : null}
          </div>
        ) : null}

        {currentTab === "diff" ? <DiffViewer patch={artifacts?.patch ?? null} /> : null}

        {currentTab === "experience" ? (
          <div className="experience-view">
            <div className="experience-stats">
              <div><span>检索到的历史经验</span><strong>{run.retrieved_experience_ids.length}</strong></div>
              <div><span>本次生成的新经验</span><strong>{run.generated_experience_id ? 1 : 0}</strong></div>
            </div>
            {artifacts?.experience ? (
              <div className="experience-detail">
                <div><span>失败模式</span><p>{stringifyValue(artifacts.experience.failure_pattern)}</p></div>
                <div><span>经验结论</span><p>{stringifyValue(artifacts.experience.lesson)}</p></div>
                <div><span>建议动作</span><p>{stringifyValue(artifacts.experience.recommended_actions)}</p></div>
              </div>
            ) : (
              <div className="content-empty"><BrainIcon size={28} /><strong>本次没有生成失败经验</strong><span>成功任务不会强行生成经验，避免将无效信息写入长期记忆。</span></div>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
