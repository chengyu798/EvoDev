// 统一封装任务、运行状态和运行产物接口。
export type HealthStatus = {
  status: "ok";
  version: string;
  docker_available: boolean;
};

export type TaskCreate = {
  repository_path: string;
  issue_title: string;
  issue_body: string;
  test_command: string;
  constraints: string[];
  max_iterations: number;
  title_locked: boolean;
};

export type Task = TaskCreate & {
  id: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  title_locked: boolean;
  messages: TaskMessage[];
  plans: TaskPlan[];
  planning_status?: "idle" | "planning" | "failed" | "ready";
  planning_error?: string | null;
};

export type MessageIntent = "explain" | "modify" | "clarify" | "system";

export type TaskMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  intent: MessageIntent | null;
  agent_name: string | null;
  run_id: string | null;
  created_at: string;
};

export type TaskPlan = {
  id: string;
  version: number;
  status: "draft" | "approved" | "superseded";
  problem_summary: string;
  likely_root_cause: string;
  relevant_files: string[];
  implementation_steps: string[];
  validation_steps: string[];
  risks: string[];
  created_at: string;
  approved_at: string | null;
  base_commit?: string | null;
};

export type RunStatus =
  | "created"
  | "preparing"
  | "baseline_testing"
  | "analyzing"
  | "implementing"
  | "testing"
  | "debugging"
  | "reviewing"
  | "finalizing"
  | "succeeded"
  | "failed"
  | "cancelled";

export type TaskRun = {
  id: string;
  task_id: string;
  status: RunStatus;
  workflow_version: string;
  current_node: string | null;
  iteration: number;
  max_iterations: number;
  error_code: string | null;
  error_message: string | null;
  tests_passed: boolean | null;
  review_passed: boolean | null;
  changed_files: string[];
  retrieved_experience_ids: string[];
  generated_experience_id: string | null;
  retry_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms: number;
  cost_estimate?: {
    status: "estimated" | "unconfigured";
    amount: number | null;
    currency: string;
    scope: string;
  } | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunEvent = {
  id: string;
  run_id: string;
  event_type: string;
  node_name: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type TestResult = {
  command?: string[];
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  duration_ms?: number;
  timed_out?: boolean;
};

export type AgentTrace = {
  agent_id?: string;
  model?: string;
  prompt_version?: string;
  output?: Record<string, unknown>;
  tool_calls?: unknown[];
  prompt_tokens?: number;
  completion_tokens?: number;
  duration_ms?: number;
};

export type RunArtifactBundle = {
  run_id: string;
  baseline_test: TestResult | null;
  verification_tests: TestResult[];
  agent_traces: AgentTrace[];
  evaluation: Record<string, unknown> | null;
  patch: string | null;
  experience: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
};

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type ValidationErrorDetail = {
  loc?: unknown[];
  msg?: string;
};

const fieldLabels: Record<string, string> = {
  repository_path: "本地代码仓库路径",
  issue_title: "任务名称",
  issue_body: "问题描述",
  test_command: "测试命令",
  constraints: "修改约束",
  max_iterations: "最大修复次数",
  title_locked: "是否锁定会话名称",
};

function parseErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const body = payload as { message?: unknown; detail?: unknown };
  if (typeof body.message === "string") return body.message;
  if (typeof body.detail === "string") return body.detail;
  if (!Array.isArray(body.detail)) return fallback;

  const messages = body.detail.flatMap((item) => {
    if (typeof item === "string") return [item];
    if (!item || typeof item !== "object") return [];
    const detail = item as ValidationErrorDetail;
    if (typeof detail.msg !== "string") return [];
    const field = detail.loc?.at(-1);
    const label = typeof field === "string" ? fieldLabels[field] : undefined;
    const message = detail.msg.replace(/^Value error,\s*/i, "");
    return [label ? `${label}：${message}` : message];
  });
  return messages.length ? messages.join("；") : fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = `接口请求失败，状态码：${response.status}`;
    try {
      message = parseErrorMessage(await response.json(), message);
    } catch {
      // 非 JSON 错误响应保留通用提示。
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return request<HealthStatus>("/api/health", { signal });
}

export function createTask(payload: TaskCreate): Promise<Task> {
  return request<Task>("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listTasks(signal?: AbortSignal, archived = false): Promise<Task[]> {
  return request<Task[]>(`/api/tasks?archived=${archived}`, { signal });
}

export function fetchTask(taskId: string, signal?: AbortSignal): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}`, { signal });
}

export function respondTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/respond`, { method: "POST" });
}

export function updateTaskTitle(taskId: string, title: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/title`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function archiveTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/archive`, { method: "POST" });
}

export function restoreTask(taskId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/restore`, { method: "POST" });
}

export function createTaskPlan(taskId: string, feedback?: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback: feedback || null }),
  });
}

export function approveTaskPlan(taskId: string, planId: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/plans/${planId}/approve`, {
    method: "POST",
  });
}

export function sendTaskMessage(taskId: string, content: string): Promise<Task> {
  return request<Task>(`/api/tasks/${taskId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export function createRun(taskId: string): Promise<TaskRun> {
  return request<TaskRun>(`/api/tasks/${taskId}/runs`, { method: "POST" });
}

export function listRuns(signal?: AbortSignal): Promise<TaskRun[]> {
  return request<TaskRun[]>("/api/runs", { signal });
}

export function fetchRun(runId: string, signal?: AbortSignal): Promise<TaskRun> {
  return request<TaskRun>(`/api/runs/${runId}`, { signal });
}

export function fetchRunEvents(runId: string, signal?: AbortSignal): Promise<RunEvent[]> {
  return request<RunEvent[]>(`/api/runs/${runId}/events`, { signal });
}

export function fetchRunArtifacts(
  runId: string,
  signal?: AbortSignal,
): Promise<RunArtifactBundle> {
  return request<RunArtifactBundle>(`/api/runs/${runId}/artifacts`, { signal });
}

export function cancelRun(runId: string): Promise<TaskRun> {
  return request<TaskRun>(`/api/runs/${runId}/cancel`, { method: "POST" });
}
