# Agent 定义

本目录保存 Agent 角色清单、结构化输出、模型调用适配、工具调用循环和多角色协调器。
Agent 只处理需要推理的步骤，并且只能使用其 `allowed_tools` 明确授权的工具。

- `catalog.py`：定义四类 Agent 的模型、Prompt 文件、版本和工具权限。
- `prompting.py`：安全加载提示词模板并注入 Prompt 版本和 JSON Schema。
- `prompts/`：分别保存 Analyst、Developer、Failure Analyzer 和 Reviewer 的系统提示词。
- `schemas.py`：定义分析、开发、失败诊断和审查结果。
- `client.py`：通过 LiteLLM 屏蔽不同模型服务商的调用差异。
- `tools.py`：限制 Agent 只能操作当前任务工作区。
- `executor.py`：处理工具调用次数、结构化输出和 Token 统计。
- `coordinator.py`：向工作流提供四类 Agent 的统一入口。
