# Agent 定义

本目录保存 Agent 角色清单、结构化输出、模型调用适配、工具调用循环和多角色协调器。
Agent 只处理需要推理的步骤，并且只能使用其 `allowed_tools` 明确授权的工具。

- `catalog.py`：定义对话、修复 Agent 与 Prompt Optimizer 的模型、Prompt 和工具权限。
- `prompting.py`：安全加载提示词模板并注入 Prompt 版本和 JSON Schema。
- `prompts/`：保存只读对话、四类修复 Agent 和 Prompt Optimizer 的系统提示词。
- `schemas.py`：定义对话、分析、开发、失败诊断和审查结果。
- `client.py`：通过 LiteLLM 屏蔽不同模型服务商的调用差异。
- `tools.py`：限制 Agent 只能操作当前任务工作区。
- `executor.py`：处理工具调用次数、结构化输出、实时事件和 Token 统计。
- `coordinator.py`：向工作流提供四类 Agent 的统一入口。

Analyst 和 Developer 会收到 `historical_experiences`。历史经验只作为排查参考，Agent 必须
依据当前仓库内容和真实测试进行核对，不能直接把历史结论当作当前事实。

模型最终输出未通过 JSON Schema 校验时，执行器会要求模型只修正格式一次；第二次仍不合法
才终止运行，避免瞬时格式偏差直接破坏完整任务。

正式修复 Agent 会在固定系统提示词后加载 PostgreSQL 中已通过 A/B 评测的指导层；未激活
的候选内容不会进入正式任务。
