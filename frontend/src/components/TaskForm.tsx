// 通过对话式输入收集修复目标，并在设置区补充执行参数。
import {
  ArrowUpIcon,
  FolderOpenIcon,
  SlidersHorizontalIcon,
  SparkleIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";

import type { TaskCreate } from "../api/client";

type TaskFormProps = {
  submitting: boolean;
  error: string | null;
  recentRepositories?: string[];
  onSubmit: (payload: TaskCreate) => Promise<void>;
};

const promptExamples = [
  {
    label: "修复测试失败",
    title: "修复订单金额计算错误",
    body: "订单金额计算存在错误。请结合现有测试定位根因，修复实现，并确保所有测试通过。",
  },
  {
    label: "排查边界条件",
    title: "修复边界条件处理错误",
    body: "请检查当前实现中的边界条件，定位与预期行为不一致的位置，并通过现有测试验证修复结果。",
  },
  {
    label: "优化异常处理",
    title: "修复异常处理逻辑",
    body: "当前模块在异常输入下返回了错误结果。请定位异常处理问题，保持公开接口不变，并确保现有测试全部通过。",
  },
];

function deriveTitle(description: string): string {
  const firstSentence = description.split(/[。！？\n]/).find(Boolean)?.trim() ?? "";
  return firstSentence.slice(0, 60) || "代码修复任务";
}

export function TaskForm({ submitting, error, recentRepositories = [], onSubmit }: TaskFormProps) {
  const [repositoryPath, setRepositoryPath] = useState("");
  const [issueTitle, setIssueTitle] = useState("");
  const [issueBody, setIssueBody] = useState("");
  const [testCommand, setTestCommand] = useState("pytest -q");
  const [constraints, setConstraints] = useState("保持公开函数签名不变");
  const [maxIterations, setMaxIterations] = useState(3);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const description = issueBody.trim();
    await onSubmit({
      repository_path: repositoryPath.trim(),
      issue_title: issueTitle.trim() || deriveTitle(description),
      issue_body: description,
      test_command: testCommand.trim(),
      constraints: constraints
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      max_iterations: maxIterations,
      title_locked: Boolean(issueTitle.trim()),
    });
  }

  function applyExample(example: (typeof promptExamples)[number]) {
    setIssueTitle(example.title);
    setIssueBody(example.body);
  }

  return (
    <div className="prompt-entry">
      <div className="prompt-suggestions" aria-label="问题描述示例">
        <span><SparkleIcon size={15} />试试这样描述</span>
        <div>
          {promptExamples.map((example) => (
            <button key={example.label} type="button" onClick={() => applyExample(example)}>
              {example.label}
            </button>
          ))}
        </div>
      </div>

      <form className="prompt-composer" onSubmit={handleSubmit}>
        <div className="repository-field">
          <label htmlFor="repository-path"><FolderOpenIcon size={17} />工作仓库</label>
          <input
            id="repository-path"
            name="repository_path"
            list="recent-repositories"
            placeholder="粘贴本地代码仓库的绝对路径"
            value={repositoryPath}
            onChange={(event) => setRepositoryPath(event.target.value)}
            required
          />
          <datalist id="recent-repositories">
            {recentRepositories.map((path) => <option value={path} key={path} />)}
          </datalist>
        </div>

        <div className="prompt-field">
          <label className="sr-only" htmlFor="issue-body">问题描述</label>
          <textarea
            id="issue-body"
            name="issue_body"
            placeholder="告诉 EvoDev 发生了什么、预期结果是什么，以及如何判断修复成功……"
            value={issueBody}
            onChange={(event) => setIssueBody(event.target.value)}
            rows={6}
            required
          />
        </div>

        {error ? <div className="inline-error" role="alert">{error}</div> : null}

        <details className="composer-settings">
          <summary>
            <SlidersHorizontalIcon size={17} />
            运行设置
            <span>测试、约束和修复次数</span>
          </summary>
          <div className="composer-settings__content">
            <div className="form-field form-field--wide">
              <label htmlFor="issue-title">任务名称（可选）</label>
              <input
                id="issue-title"
                name="issue_title"
                placeholder="留空时根据问题描述自动生成"
                value={issueTitle}
                onChange={(event) => setIssueTitle(event.target.value)}
              />
            </div>
            <div className="form-field">
              <label htmlFor="test-command">测试命令</label>
              <input
                id="test-command"
                name="test_command"
                value={testCommand}
                onChange={(event) => setTestCommand(event.target.value)}
                required
              />
            </div>
            <div className="form-field">
              <label htmlFor="max-iterations">最大修复次数</label>
              <select
                id="max-iterations"
                name="max_iterations"
                value={maxIterations}
                onChange={(event) => setMaxIterations(Number(event.target.value))}
              >
                <option value={1}>1 次</option>
                <option value={2}>2 次</option>
                <option value={3}>3 次</option>
              </select>
            </div>
            <div className="form-field form-field--wide">
              <label htmlFor="constraints">修改约束</label>
              <textarea
                id="constraints"
                name="constraints"
                value={constraints}
                onChange={(event) => setConstraints(event.target.value)}
                rows={3}
              />
              <span>每行填写一条约束，可以留空。</span>
            </div>
          </div>
        </details>

        <footer className="composer-footer">
          <div className="composer-safety">
            <ShieldCheckIcon size={17} />
            <span>代码只在隔离工作区中修改</span>
          </div>
          <button className="send-action" type="submit" disabled={submitting}>
            <span>{submitting ? "正在分析" : "开始对话"}</span>
            <ArrowUpIcon size={18} weight="bold" />
          </button>
        </footer>
      </form>
    </div>
  );
}
