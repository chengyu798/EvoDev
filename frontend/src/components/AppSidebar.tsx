// 按会话组织历史任务，并提供重命名、归档和恢复入口。
import {
  ArchiveBoxIcon,
  ArrowCounterClockwiseIcon,
  ClockCounterClockwiseIcon,
  DotsThreeIcon,
  FolderSimpleIcon,
  PencilSimpleIcon,
  PlusIcon,
  SidebarSimpleIcon,
} from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import type { Task, TaskRun } from "../api/client";
import { statusLabels } from "../runStatus";

type AppSidebarProps = {
  collapsed: boolean;
  width: number;
  tasks: Task[];
  archivedTasks: Task[];
  runs: TaskRun[];
  selectedTaskId: string | null;
  loading: boolean;
  showingArchived: boolean;
  onToggle: () => void;
  onCreate: () => void;
  onSelect: (task: Task) => void;
  onArchive: (task: Task) => Promise<void>;
  onRestore: (task: Task) => Promise<void>;
  onRename: (task: Task, title: string) => Promise<void>;
  onShowArchived: (value: boolean) => void;
};

function repositoryName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function dateGroup(value: string): string {
  const date = new Date(value);
  const today = new Date();
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((startToday.getTime() - startDate.getTime()) / 86_400_000);
  if (days === 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 7) return "最近 7 天";
  return "更早";
}

export function AppSidebar(props: AppSidebarProps) {
  const {
    collapsed,
    width,
    tasks,
    archivedTasks,
    runs,
    selectedTaskId,
    loading,
    showingArchived,
    onToggle,
    onCreate,
    onSelect,
    onArchive,
    onRestore,
    onRename,
    onShowArchived,
  } = props;
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const visibleTasks = (showingArchived ? archivedTasks : tasks)
    .filter((task) => `${task.issue_title} ${task.repository_path} ${task.issue_body}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
    .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  const latestRunByTask = useMemo(() => {
    const map = new Map<string, TaskRun>();
    runs.forEach((run) => {
      if (!map.has(run.task_id)) map.set(run.task_id, run);
    });
    return map;
  }, [runs]);
  const groups = useMemo(() => {
    const result = new Map<string, Task[]>();
    visibleTasks.forEach((task) => {
      const key = dateGroup(task.updated_at);
      result.set(key, [...(result.get(key) ?? []), task]);
    });
    return result;
  }, [visibleTasks]);

  async function rename(task: Task) {
    const title = window.prompt("输入新的会话名称", task.issue_title)?.trim();
    setOpenMenuId(null);
    if (title && title !== task.issue_title) await onRename(task, title);
  }

  async function archive(task: Task) {
    setOpenMenuId(null);
    if (window.confirm(`确认归档“${task.issue_title}”吗？之后可以在归档会话中恢复。`)) {
      await onArchive(task);
    }
  }

  return (
    <aside className={`app-sidebar${collapsed ? " is-collapsed" : ""}`} style={{ width: collapsed ? 68 : width }}>
      <div className="sidebar__header">
        <div className="sidebar__identity"><span className="brand__mark">E</span><strong>EvoDev</strong></div>
        <button className="icon-button" type="button" aria-label={collapsed ? "展开历史会话" : "收起历史会话"} onClick={onToggle}>
          <SidebarSimpleIcon size={18} />
        </button>
      </div>

      <button className="new-task-button" type="button" onClick={onCreate}>
        <PlusIcon size={18} weight="bold" /><span>新建会话</span>
      </button>

      <div className="sidebar__section-title">
        {showingArchived ? <ArchiveBoxIcon size={15} /> : <ClockCounterClockwiseIcon size={15} />}
        <span>{showingArchived ? "归档会话" : "历史会话"}</span>
      </div>

      <div className="session-list" aria-label={showingArchived ? "归档会话" : "历史会话"}>
        <input className="history-search" aria-label="搜索会话" placeholder="搜索会话或仓库" value={query} onChange={(event) => setQuery(event.target.value)} />
        {loading ? <div className="sidebar-skeleton"><span /><span /><span /></div> : null}
        {!loading && visibleTasks.length === 0 ? (
          <div className="sidebar-empty"><FolderSimpleIcon size={22} /><span>{query ? "没有匹配的会话" : showingArchived ? "没有归档会话" : "还没有会话"}</span></div>
        ) : null}
        {!loading ? [...groups.entries()].map(([group, items]) => (
          <section className="session-group" key={group}>
            <h2>{group}</h2>
            {items.map((task) => {
              const run = latestRunByTask.get(task.id);
              return (
                <div className={`session-item${selectedTaskId === task.id ? " is-selected" : ""}`} key={task.id}>
                  <button className="session-item__main" type="button" onClick={() => onSelect(task)}>
                    <strong>{task.issue_title}</strong>
                    <span>{repositoryName(task.repository_path)}</span>
                    <small title={task.planning_error ?? undefined}>{task.planning_status === "planning" ? "正在规划" : task.planning_status === "failed" ? "规划失败" : task.plans.at(-1)?.status === "draft" ? "等待确认计划" : run ? statusLabels[run.status] : task.plans.length ? "等待启动" : "等待对话"}</small>
                  </button>
                  {showingArchived ? (
                    <button className="session-item__menu" type="button" aria-label="恢复会话" onClick={() => void onRestore(task)}>
                      <ArrowCounterClockwiseIcon size={16} />
                    </button>
                  ) : (
                    <div className="session-item__actions">
                      <button className="session-item__menu" type="button" aria-label="会话操作" onClick={() => setOpenMenuId(openMenuId === task.id ? null : task.id)}>
                        <DotsThreeIcon size={18} weight="bold" />
                      </button>
                      {openMenuId === task.id ? (
                        <div className="session-menu">
                          <button type="button" onClick={() => void rename(task)}><PencilSimpleIcon size={15} />重命名</button>
                          <button type="button" onClick={() => void archive(task)}><ArchiveBoxIcon size={15} />归档</button>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        )) : null}
      </div>

      <button className="archive-switch" type="button" onClick={() => onShowArchived(!showingArchived)}>
        {showingArchived ? <ClockCounterClockwiseIcon size={17} /> : <ArchiveBoxIcon size={17} />}
        <span>{showingArchived ? "返回历史会话" : "查看归档会话"}</span>
      </button>
    </aside>
  );
}
