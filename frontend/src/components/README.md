# 前端组件

本目录保存可复用的 React 组件。组件应保持职责单一、Props 类型明确，不直接执行后端
请求；必要的交互行为应有对应测试。

- `AppSidebar.tsx`：按时间显示历史会话，并提供重命名、归档和恢复操作。
- `TaskForm.tsx`：以自然语言输入为主，渐进补充仓库和运行配置。
- `SessionWorkspace.tsx`：展示会话消息、计划版本、多次运行和底部对话输入框。
- `RunOverview.tsx`：保留旧版运行概览组件，供迁移期间参考。
- `ArtifactViewer.tsx`：通过选项卡展示测试、智能体、代码差异和失败经验。
- `StatusBadge.tsx`：显示服务与运行状态。
