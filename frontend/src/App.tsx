// 组装会话历史、Agent 对话区和运行证据抽屉。
import { ListIcon, XIcon } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import {
  approveTaskPlan,
  archiveTask,
  cancelRun,
  createRun,
  createTask,
  respondTask,
  fetchTask,
  fetchHealth,
  fetchRun,
  fetchRunArtifacts,
  fetchRunEvents,
  listRuns,
  listTasks,
  restoreTask,
  sendTaskMessage,
  updateTaskTitle,
  type HealthStatus,
  type RunArtifactBundle,
  type RunEvent,
  type Task,
  type TaskCreate,
  type TaskPlan,
  type TaskRun,
} from "./api/client";
import { AppSidebar } from "./components/AppSidebar";
import { ArtifactViewer } from "./components/ArtifactViewer";
import type { ArtifactTab } from "./components/ArtifactViewer";
import { SessionWorkspace } from "./components/SessionWorkspace";
import { TaskForm } from "./components/TaskForm";
import { terminalStatuses } from "./runStatus";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误，请检查后端日志。";
}

function storedNumber(key: string, fallback: number): number {
  if (typeof window === "undefined") return fallback;
  const value = Number(window.localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [archivedTasks, setArchivedTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<TaskRun[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [selectedRun, setSelectedRun] = useState<TaskRun | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [artifacts, setArtifacts] = useState<RunArtifactBundle | null>(null);
  const [view, setView] = useState<"create" | "session">("create");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => typeof window !== "undefined" && window.innerWidth < 900);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [showingArchived, setShowingArchived] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => storedNumber("evodev-sidebar-width", 292));
  const [evidenceWidth, setEvidenceWidth] = useState(() => storedNumber("evodev-evidence-width", 480));
  const [loading, setLoading] = useState(true);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const sessionRuns = useMemo(
    () => runs.filter((run) => run.task_id === selectedTask?.id),
    [runs, selectedTask?.id],
  );
  const recentRepositories = useMemo(
    () => [...new Set([...tasks, ...archivedTasks].map((task) => task.repository_path))],
    [archivedTasks, tasks],
  );
  const suggestedEvidenceTab: ArtifactTab = selectedRun?.status === "testing" || selectedRun?.status === "baseline_testing"
    ? "tests"
    : selectedRun?.status === "implementing"
      ? "diff"
      : selectedRun?.status === "analyzing" || selectedRun?.status === "debugging" || selectedRun?.status === "reviewing"
        ? "agents"
        : "summary";

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then((result) => {
      setHealth(result);
      setHealthError(false);
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setHealthError(true);
    });
    Promise.all([
      listTasks(controller.signal),
      listTasks(controller.signal, true),
      listRuns(controller.signal),
    ]).then(([taskItems, archivedItems, runItems]) => {
      setTasks(taskItems);
      setArchivedTasks(archivedItems);
      setRuns(runItems);
      const linkedTaskId = new URLSearchParams(window.location.search).get("task");
      const linkedTask = [...taskItems, ...archivedItems].find(
        (item) => item.id === linkedTaskId,
      );
      if (linkedTask) {
        const linkedRun = runItems.find((item) => item.task_id === linkedTask.id) ?? null;
        setSelectedTask(linkedTask);
        setSelectedRun(linkedRun);
        setEvidenceOpen(Boolean(linkedRun) && new URLSearchParams(window.location.search).get("evidence") === "1");
        setView("session");
      }
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setPageError(errorMessage(error));
    }).finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const selectedRunId = selectedRun?.id;
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      listTasks(controller.signal).then((items) => {
        setTasks(items);
        setSelectedTask((current) => current ? items.find((item) => item.id === current.id) ?? current : null);
      }).catch(() => { /* 后台刷新失败不打断当前对话。 */ });
    }, 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    if (!selectedRunId || view !== "session") return;
    const runId = selectedRunId;
    const controller = new AbortController();
    let timer: number | undefined;
    async function refresh() {
      try {
        const [run, runEvents, runArtifacts] = await Promise.all([
          fetchRun(runId, controller.signal),
          fetchRunEvents(runId, controller.signal),
          fetchRunArtifacts(runId, controller.signal),
        ]);
        setSelectedRun(run);
        setEvents(runEvents);
        setArtifacts(runArtifacts);
        setRuns((items) => items.map((item) => item.id === run.id ? run : item));
        setArtifactLoading(false);
        if (!terminalStatuses.has(run.status)) timer = window.setTimeout(refresh, 1200);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setPageError(errorMessage(error));
        setArtifactLoading(false);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [selectedRunId, view]);

  async function handleTaskSubmit(payload: TaskCreate) {
    setPending(true);
    setFormError(null);
    let createdId: string | null = null;
    try {
      const created = await createTask(payload);
      createdId = created.id;
      setTasks((items) => [created, ...items]);
      setSelectedTask(created);
      setView("session");
      const planned = await respondTask(created.id);
      setSelectedTask((current) => current?.id === planned.id ? planned : current);
      setTasks((items) => items.map((item) => item.id === planned.id ? planned : item));
    } catch (error: unknown) {
      const message = errorMessage(error);
      if (createdId) { setPageError(message); await refreshTask(createdId); }
      else setFormError(message);
    } finally {
      setPending(false);
    }
  }

  async function refreshTask(id: string) {
    try {
      const task = await fetchTask(id);
      setTasks((items) => items.map((item) => item.id === id ? task : item));
      setSelectedTask((current) => current?.id === id ? task : current);
    } catch { /* 保留原始操作错误，避免刷新错误覆盖原因。 */ }
  }

  function selectTask(task: Task) {
    setSelectedTask(task);
    const taskRuns = runs.filter((run) => run.task_id === task.id);
    setSelectedRun(taskRuns[0] ?? null);
    setEvents([]);
    setArtifacts(null);
    setArtifactLoading(Boolean(taskRuns[0]));
    setView("session");
    window.history.replaceState(null, "", `?task=${task.id}`);
    setPageError(null);
    if (window.innerWidth < 900) setSidebarCollapsed(true);
  }

  function selectRun(run: TaskRun) {
    setSelectedRun(run);
    setEvents([]);
    setArtifacts(null);
    setArtifactLoading(true);
  }

  async function sendMessage(content: string) {
    if (!selectedTask) return false;
    setPending(true);
    setPageError(null);
    try {
      const updated = await sendTaskMessage(selectedTask.id, content);
      setSelectedTask((current) => current?.id === updated.id ? updated : current);
      setTasks((items) => items.map((item) => item.id === updated.id ? updated : item));
      return true;
    } catch (error: unknown) {
      setPageError(errorMessage(error));
      await refreshTask(selectedTask.id);
      return false;
    } finally {
      setPending(false);
    }
  }

  async function startPlan(plan: TaskPlan) {
    if (!selectedTask) return;
    const activeRun = sessionRuns.find((run) => !terminalStatuses.has(run.status));
    if (activeRun) {
      const shouldStop = window.confirm(
        "当前修复仍在运行。选择“确定”会先停止当前运行并启动新计划；选择“取消”会保留计划，等待当前运行完成。",
      );
      if (!shouldStop) return;
    }
    setPending(true);
    try {
      if (activeRun) {
        const cancelled = await cancelRun(activeRun.id);
        setRuns((items) => items.map((item) => item.id === cancelled.id ? cancelled : item));
      }
      const approved = await approveTaskPlan(selectedTask.id, plan.id);
      const run = await createRun(selectedTask.id);
      setSelectedTask(approved);
      setTasks((items) => items.map((item) => item.id === approved.id ? approved : item));
      setRuns((items) => [run, ...items]);
      setSelectedRun(run);
      setEvents([]);
      setArtifacts(null);
      setArtifactLoading(true);
      setEvidenceOpen(true);
    } catch (error: unknown) {
      setPageError(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  async function retryResponse() {
    if (!selectedTask) return;
    setPending(true);
    setPageError(null);
    try {
      const updated = await respondTask(selectedTask.id);
      setTasks((items) => items.map((item) => item.id === updated.id ? updated : item));
      setSelectedTask((current) => current?.id === updated.id ? updated : current);
    } catch (error: unknown) {
      setPageError(errorMessage(error));
      await refreshTask(selectedTask.id);
    } finally { setPending(false); }
  }

  async function handleCancel() {
    if (!selectedRun) return;
    setPending(true);
    try {
      const run = await cancelRun(selectedRun.id);
      setSelectedRun(run);
      setRuns((items) => items.map((item) => item.id === run.id ? run : item));
    } catch (error: unknown) {
      setPageError(errorMessage(error));
    } finally {
      setPending(false);
    }
  }

  async function handleArchive(task: Task) {
    try {
    const updated = await archiveTask(task.id);
    setTasks((items) => items.filter((item) => item.id !== task.id));
    setArchivedTasks((items) => [updated, ...items]);
    if (selectedTask?.id === task.id) {
      setSelectedTask(null);
      setSelectedRun(null);
      setView("create");
    }
    } catch (error: unknown) { setPageError(errorMessage(error)); }
  }

  async function handleRestore(task: Task) {
    try {
    const updated = await restoreTask(task.id);
    setArchivedTasks((items) => items.filter((item) => item.id !== task.id));
    setTasks((items) => [updated, ...items]);
    } catch (error: unknown) { setPageError(errorMessage(error)); }
  }

  async function handleRename(task: Task, title: string) {
    try {
    const updated = await updateTaskTitle(task.id, title);
    setTasks((items) => items.map((item) => item.id === updated.id ? updated : item));
    if (selectedTask?.id === updated.id) setSelectedTask(updated);
    } catch (error: unknown) { setPageError(errorMessage(error)); }
  }

  function resizeSidebar(event: React.PointerEvent<HTMLDivElement>) {
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    const move = (moveEvent: PointerEvent) => {
      const next = Math.min(420, Math.max(220, startWidth + moveEvent.clientX - startX));
      setSidebarWidth(next);
      window.localStorage.setItem("evodev-sidebar-width", String(next));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  function resizeEvidence(event: React.PointerEvent<HTMLDivElement>) {
    const startX = event.clientX;
    const startWidth = evidenceWidth;
    const move = (moveEvent: PointerEvent) => {
      const next = Math.min(720, Math.max(360, startWidth + startX - moveEvent.clientX));
      setEvidenceWidth(next);
      window.localStorage.setItem("evodev-evidence-width", String(next));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  return (
    <div className="app-frame">
      <AppSidebar
        collapsed={sidebarCollapsed}
        width={sidebarWidth}
        tasks={tasks}
        archivedTasks={archivedTasks}
        runs={runs}
        selectedTaskId={selectedTask?.id ?? null}
        loading={loading}
        showingArchived={showingArchived}
        onToggle={() => setSidebarCollapsed((value) => !value)}
        onCreate={() => { setView("create"); setSelectedTask(null); setSelectedRun(null); setEvidenceOpen(false); window.history.replaceState(null, "", window.location.pathname); }}
        onSelect={selectTask}
        onArchive={handleArchive}
        onRestore={handleRestore}
        onRename={handleRename}
        onShowArchived={setShowingArchived}
      />
      {!sidebarCollapsed ? <div className="column-resizer column-resizer--left" role="separator" aria-label="调整历史栏宽度" onPointerDown={resizeSidebar} onDoubleClick={() => { setSidebarWidth(292); window.localStorage.setItem("evodev-sidebar-width", "292"); }} /> : null}
      <button className="mobile-sidebar-button" type="button" aria-label="打开历史会话" onClick={() => setSidebarCollapsed(false)}><ListIcon size={20} /></button>

      <main className="main-workspace">
        <div className="service-strip"><span className={health && !healthError ? "is-online" : ""} />{health && !healthError ? "服务与隔离沙箱已连接" : healthError ? "后端服务未连接" : "正在检查运行环境"}</div>
        {pageError ? <div className="page-error" role="alert">{pageError}</div> : null}
        {view === "create" ? (
          <section className="create-view">
            <div className="welcome-copy"><span>新会话</span><h1>把代码问题交给一组会协作的智能体</h1><p>先分析并展示计划，你确认后才会修改代码。</p></div>
            <div className="start-guides"><span>选择一个代码仓库</span><span>描述问题和预期结果</span><span>确认计划后启动修复</span></div>
            <TaskForm submitting={pending} error={formError} recentRepositories={recentRepositories} onSubmit={handleTaskSubmit} />
          </section>
        ) : selectedTask ? (
          <SessionWorkspace key={selectedTask.id}
            task={selectedTask}
            runs={sessionRuns}
            selectedRun={selectedRun}
            events={events}
            artifacts={artifacts}
            pending={pending}
            onSelectRun={selectRun}
            onSend={sendMessage}
            onRetry={retryResponse}
            onStartPlan={startPlan}
            onCancel={handleCancel}
            onOpenEvidence={() => setEvidenceOpen(true)}
          />
        ) : null}
      </main>

      {evidenceOpen && selectedRun ? (
        <>
          <div className="column-resizer column-resizer--right" role="separator" aria-label="调整证据栏宽度" onPointerDown={resizeEvidence} onDoubleClick={() => { setEvidenceWidth(480); window.localStorage.setItem("evodev-evidence-width", "480"); }} />
          <aside className="evidence-drawer" style={{ width: evidenceWidth }}>
            <header><div><span>运行证据</span><strong>可复查的完整执行记录</strong></div><button className="icon-button" type="button" aria-label="关闭证据栏" onClick={() => setEvidenceOpen(false)}><XIcon size={18} /></button></header>
            <ArtifactViewer key={selectedRun.id} run={selectedRun} artifacts={artifacts} loading={artifactLoading} suggestedTab={suggestedEvidenceTab} />
          </aside>
        </>
      ) : null}
      {!sidebarCollapsed ? <button className="mobile-sidebar-backdrop" type="button" aria-label="关闭历史会话" onClick={() => setSidebarCollapsed(true)} /> : null}
      {evidenceOpen ? <button className="mobile-evidence-backdrop" type="button" aria-label="关闭证据栏" onClick={() => setEvidenceOpen(false)} /> : null}
    </div>
  );
}

export default App;
