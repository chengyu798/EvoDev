// 验证会话创建、计划确认、运行结果和接口错误提示。
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const taskId = "22222222-2222-4222-8222-222222222222";
const runId = "11111111-1111-4111-8111-111111111111";
const planId = "33333333-3333-4333-8333-333333333333";

const draftPlan = {
  id: planId, version: 1, status: "draft",
  problem_summary: "add 函数错误地执行了减法。", likely_root_cause: "函数实现使用了错误的运算符。",
  relevant_files: ["calculator.py"], implementation_steps: ["将减法运算改为加法运算。"],
  validation_steps: ["运行 pytest -q。"], risks: [], created_at: "2026-09-05T00:00:01Z", approved_at: null,
} as const;

const completedRun = {
  id: runId, task_id: taskId, status: "succeeded", workflow_version: "bug_fix@1", current_node: null,
  iteration: 1, max_iterations: 3, error_code: null, error_message: null, tests_passed: true, review_passed: true,
  changed_files: ["calculator.py"], retrieved_experience_ids: [], generated_experience_id: null, retry_count: 0,
  prompt_tokens: 100, completion_tokens: 20, duration_ms: 1200, created_at: "2026-09-05T00:00:00Z",
  started_at: "2026-09-05T00:00:01Z", finished_at: "2026-09-05T00:00:02Z",
} as const;

function makeTask(overrides: Record<string, unknown> = {}) {
  return {
    id: taskId, repository_path: "/tmp/example", issue_title: "修复加法", issue_body: "返回两数之和",
    test_command: "pytest -q", constraints: ["保持公开函数签名不变"], max_iterations: 3,
    created_at: "2026-09-05T00:00:00Z", updated_at: "2026-09-05T00:00:00Z", archived_at: null,
    title_locked: false, messages: [], plans: [], ...overrides,
  };
}

const completedTask = makeTask({ plans: [{ ...draftPlan, status: "approved", approved_at: "2026-09-05T00:00:02Z" }] });
const completedArtifacts = {
  run_id: runId, baseline_test: { command: ["pytest", "-q"], exit_code: 1, stdout: "1 failed" },
  verification_tests: [{ command: ["pytest", "-q"], exit_code: 0, stdout: "2 passed" }], agent_traces: [],
  evaluation: { tests_passed: true }, patch: "- return left - right\n+ return left + right", experience: null, metrics: {},
};

function response(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }));
}

function initialResponse(url: string, init?: RequestInit) {
  if (url.endsWith("/api/health")) return response({ status: "ok", version: "0.1.0", docker_available: true });
  if ((url.endsWith("/api/tasks") || url.endsWith("/api/tasks?archived=false")) && !init?.method) return response([]);
  if (url.endsWith("/api/tasks?archived=true") && !init?.method) return response([]);
  if (url.endsWith("/api/runs") && !init?.method) return response([]);
  return null;
}

describe("首页", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("显示会话工作台和服务状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => initialResponse(String(input), init) ?? response({ message: "未匹配接口" }, 404));
    render(<App />);
    expect(screen.getByRole("heading", { name: "把代码问题交给一组会协作的智能体" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始对话" })).toBeInTheDocument();
    expect(await screen.findByText("服务与隔离沙箱已连接")).toBeInTheDocument();
  });

  it("创建会话并生成计划，确认后才启动运行且可以查看证据", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input); const initial = initialResponse(url, init); if (initial) return initial;
      if (url.endsWith(`/api/tasks/${taskId}/respond`) && init?.method === "POST") return response(makeTask({ plans: [draftPlan] }));
      if (url.endsWith(`/api/tasks/${taskId}/plans/${planId}/approve`)) return response(makeTask({ plans: [{ ...draftPlan, status: "approved", approved_at: "2026-09-05T00:00:02Z" }] }));
      if (url.endsWith(`/api/tasks/${taskId}/runs`)) return response(completedRun, 202);
      if (url.endsWith(`/api/runs/${runId}/events`)) return response([]);
      if (url.endsWith(`/api/runs/${runId}/artifacts`)) return response(completedArtifacts);
      if (url.endsWith(`/api/runs/${runId}`)) return response(completedRun);
      if (url.endsWith("/api/tasks") && init?.method === "POST") return response(makeTask(), 201);
      return response({ message: "未匹配接口" }, 404);
    });
    render(<App />);
    fireEvent.change(screen.getByLabelText("工作仓库"), { target: { value: "/tmp/example" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "返回两数之和" } });
    fireEvent.click(screen.getByRole("button", { name: "开始对话" }));
    expect(await screen.findByText("等待你的确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "启动修复" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).includes("/runs") && init?.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "启动修复" }));
    await waitFor(() => expect(screen.getAllByText("运行成功").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "查看证据" }));
    fireEvent.click(await screen.findByRole("tab", { name: /测试报告/ }));
    expect(await screen.findByText("修改前基准测试")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /代码变更/ }));
    expect(screen.getByText(/return left \+ right/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "恢复自动跟随运行阶段" }));
    expect(screen.getByRole("tab", { name: /执行摘要/ })).toHaveAttribute("aria-selected", "true");
  });

  it("按会话关联历史任务并支持打开运行证据", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/health")) return response({ status: "ok", version: "0.1.0", docker_available: true });
      if (url.endsWith("/api/tasks") || url.endsWith("/api/tasks?archived=false")) return response([completedTask]);
      if (url.endsWith("/api/tasks?archived=true")) return response([]);
      if (url.endsWith("/api/runs")) return response([completedRun]);
      if (url.endsWith(`/api/runs/${runId}/events`)) return response([]);
      if (url.endsWith(`/api/runs/${runId}/artifacts`)) return response(completedArtifacts);
      if (url.endsWith(`/api/runs/${runId}`)) return response(completedRun);
      return response({ message: "未匹配接口" }, 404);
    });
    render(<App />);
    const historyItem = await screen.findByRole("button", { name: /修复加法.*example.*运行成功/ });
    fireEvent.click(historyItem);
    expect(await screen.findByRole("heading", { name: "修复加法" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "查看证据" })).toBeInTheDocument();
  });

  it("把接口字段校验错误转换为可读中文", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input); const initial = initialResponse(url, init); if (initial) return initial;
      if (url.endsWith("/api/tasks") && init?.method === "POST") return response({ detail: [{ loc: ["body", "repository_path"], msg: "Value error, 仓库路径必须指向已存在的目录" }] }, 422);
      return response({ message: "未匹配接口" }, 404);
    });
    render(<App />);
    fireEvent.change(screen.getByLabelText("工作仓库"), { target: { value: "/tmp/not-exists" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "请修复问题" } });
    fireEvent.click(screen.getByRole("button", { name: "开始对话" }));
    expect(await screen.findByText("本地代码仓库路径：仓库路径必须指向已存在的目录")).toBeInTheDocument();
  });

  it("首条解释请求只走对话路由，不主动生成计划或运行", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input); const initial = initialResponse(url, init); if (initial) return initial;
      if (url.endsWith("/api/tasks") && init?.method === "POST") return response(makeTask());
      if (url.endsWith(`/api/tasks/${taskId}/respond`)) return response(makeTask({ messages: [{ id: "answer", role: "assistant", content: "这是一个计算模块。", intent: "explain" }] }));
      return response({}, 404);
    });
    render(<App />);
    fireEvent.change(screen.getByLabelText("工作仓库"), { target: { value: "/tmp/example" } });
    fireEvent.change(screen.getByLabelText("问题描述"), { target: { value: "这个模块做什么？" } });
    fireEvent.click(screen.getByRole("button", { name: "开始对话" }));
    expect(await screen.findByText("这是一个计算模块。")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => /\/(plans|runs)$/.test(String(input)) && init?.method === "POST")).toBe(false);
    expect(screen.queryByRole("button", { name: "启动修复" })).not.toBeInTheDocument();
  });

  it("显示真实失败状态、支持历史搜索且发送失败保留输入", async () => {
    const failed = makeTask({ planning_status: "failed", planning_error: "工具调用达到上限，请缩小范围。" });
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/tasks?archived=false")) return response([failed]);
      if (url.endsWith(`/api/tasks/${taskId}/messages`)) return response({ message: "分析服务暂时不可用" }, 502);
      if (url.endsWith(`/api/tasks/${taskId}`)) return response(failed);
      return initialResponse(url, init) ?? response({}, 404);
    });
    render(<App />);
    expect(await screen.findByText("规划失败")).toBeInTheDocument();
    expect(screen.queryByText("正在规划")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索会话"), { target: { value: "找不到的仓库" } });
    expect(screen.getByText("没有匹配的会话")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索会话"), { target: { value: "example" } });
    fireEvent.click(screen.getByRole("button", { name: /修复加法.*规划失败/ }));
    expect(screen.getByText("工具调用达到上限，请缩小范围。")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("继续对话"), { target: { value: "只检查 calculator.py" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText("分析服务暂时不可用")).toBeInTheDocument();
    expect(screen.getByLabelText("继续对话")).toHaveValue("只检查 calculator.py");
  });
});
