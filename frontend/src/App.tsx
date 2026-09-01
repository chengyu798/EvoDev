// 首页展示系统状态、执行流程和运行产物。
import { useEffect, useState } from "react";

import { fetchHealth, type HealthStatus } from "./api/client";
import { StatusBadge } from "./components/StatusBadge";

const workflow = [
  { name: "分析", detail: "理解问题描述和代码仓库" },
  { name: "实现", detail: "生成范围最小的正确补丁" },
  { name: "测试", detail: "运行确定性的测试检查" },
  { name: "审查", detail: "检查需求覆盖和回归风险" },
];

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((result) => {
        setHealth(result);
        setHealthError(false);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setHealthError(true);
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="EvoDev 首页">
          <span className="brand__mark">E</span>
          <span>EvoDev</span>
        </a>
        <div className="topbar__status">
          {health ? (
            <>
              <StatusBadge label="后端服务已连接" tone="ready" />
              <StatusBadge
                label={health.docker_available ? "沙箱已就绪" : "沙箱未启动"}
                tone={health.docker_available ? "ready" : "offline"}
              />
            </>
          ) : (
            <StatusBadge
              label={healthError ? "后端服务离线" : "正在检查服务"}
              tone={healthError ? "offline" : "pending"}
            />
          )}
        </div>
      </header>

      <section className="hero">
        <div className="eyebrow">多智能体软件修复</div>
        <h1>将问题转化为<br />可验证的代码。</h1>
        <p>
          EvoDev 在隔离工作区中协调问题分析、代码实现、确定性测试和补丁审查，
          并为每一步决策保留可复查的证据。
        </p>
        <button className="primary-action" type="button" disabled>
          创建任务
          <span aria-hidden="true">&rarr;</span>
        </button>
        <span className="hero__note">任务创建功能将在下一阶段接通。</span>
      </section>

      <section className="workspace-grid" aria-label="EvoDev 工作流概览">
        <article className="panel workflow-panel">
          <div className="panel__header">
            <div>
              <span className="panel__kicker">缺陷修复流程</span>
              <h2>执行流程</h2>
            </div>
            <StatusBadge label="架构已就绪" tone="ready" />
          </div>
          <ol className="workflow-list">
            {workflow.map((step, index) => (
              <li key={step.name}>
                <span className="workflow-list__index">0{index + 1}</span>
                <div>
                  <strong>{step.name}</strong>
                  <span>{step.detail}</span>
                </div>
              </li>
            ))}
          </ol>
        </article>

        <article className="panel evidence-panel">
          <div className="panel__header">
            <div>
              <span className="panel__kicker">运行证据</span>
              <h2>每次运行都会产出</h2>
            </div>
          </div>
          <dl className="evidence-list">
            <div>
              <dt>代码补丁</dt>
              <dd>可复查的代码差异</dd>
            </div>
            <div>
              <dt>测试结果</dt>
              <dd>修改前后的测试证据</dd>
            </div>
            <div>
              <dt>运行轨迹</dt>
              <dd>智能体、工具和状态变化</dd>
            </div>
            <div>
              <dt>经验记录</dt>
              <dd>从失败中提炼的可复用经验</dd>
            </div>
          </dl>
        </article>
      </section>
    </main>
  );
}

export default App;
