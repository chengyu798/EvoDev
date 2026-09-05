// 集中维护运行状态的中文文案和终态判断。
import type { RunStatus } from "./api/client";

export const terminalStatuses = new Set<RunStatus>(["succeeded", "failed", "cancelled"]);

export const statusLabels: Record<RunStatus, string> = {
  created: "等待执行",
  preparing: "准备工作区",
  baseline_testing: "基准测试",
  analyzing: "分析问题",
  implementing: "修改代码",
  testing: "验证修改",
  debugging: "诊断失败",
  reviewing: "审查补丁",
  finalizing: "生成结果",
  succeeded: "运行成功",
  failed: "运行失败",
  cancelled: "已取消",
};
