import { useEffect, useState } from "react";

import { fetchHealth, type HealthStatus } from "./api/client";
import { StatusBadge } from "./components/StatusBadge";

const workflow = [
  { name: "Analyze", detail: "Understand issue and repository" },
  { name: "Implement", detail: "Create the smallest valid patch" },
  { name: "Test", detail: "Run deterministic pytest checks" },
  { name: "Review", detail: "Assess coverage and regression risk" },
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
        <a className="brand" href="/" aria-label="EvoDev home">
          <span className="brand__mark">E</span>
          <span>EvoDev</span>
        </a>
        <div className="topbar__status">
          {health ? (
            <>
              <StatusBadge label={`API v${health.version}`} tone="ready" />
              <StatusBadge
                label={health.docker_available ? "Docker ready" : "Docker offline"}
                tone={health.docker_available ? "ready" : "offline"}
              />
            </>
          ) : (
            <StatusBadge
              label={healthError ? "API offline" : "Checking API"}
              tone={healthError ? "offline" : "pending"}
            />
          )}
        </div>
      </header>

      <section className="hero">
        <div className="eyebrow">MULTI-AGENT SOFTWARE REPAIR</div>
        <h1>Turn an issue into<br />verified code.</h1>
        <p>
          EvoDev coordinates analysis, implementation, deterministic tests, and review
          inside an isolated workspace. Every decision leaves evidence.
        </p>
        <button className="primary-action" type="button" disabled>
          Create task
          <span aria-hidden="true">&rarr;</span>
        </button>
        <span className="hero__note">Task creation is the next implementation step.</span>
      </section>

      <section className="workspace-grid" aria-label="EvoDev workflow overview">
        <article className="panel workflow-panel">
          <div className="panel__header">
            <div>
              <span className="panel__kicker">BUG FIX V1</span>
              <h2>Execution graph</h2>
            </div>
            <StatusBadge label="Architecture ready" tone="ready" />
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
              <span className="panel__kicker">RUN EVIDENCE</span>
              <h2>What a run produces</h2>
            </div>
          </div>
          <dl className="evidence-list">
            <div>
              <dt>Patch</dt>
              <dd>Reviewable Git diff</dd>
            </div>
            <div>
              <dt>Tests</dt>
              <dd>Baseline and final results</dd>
            </div>
            <div>
              <dt>Trace</dt>
              <dd>Agents, tools, and transitions</dd>
            </div>
            <div>
              <dt>Experience</dt>
              <dd>Reusable lessons from failure</dd>
            </div>
          </dl>
        </article>
      </section>
    </main>
  );
}

export default App;
