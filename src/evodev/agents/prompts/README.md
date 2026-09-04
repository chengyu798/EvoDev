# Agent 系统提示词

本目录单独保存修复 Agent 和 Prompt Optimizer 的系统提示词。每个模板必须保留以下占位符：

- `{{PROMPT_VERSION}}`：运行时替换为 Agent 配置中的提示词版本。
- `{{OUTPUT_SCHEMA}}`：运行时替换为当前结构化输出的 JSON Schema。

修改提示词时应同步增加 `prompt_version`，并运行 Agent 相关测试。提示词只描述模型职责和
行为约束，工具权限仍由 `agents/catalog.py` 和工具网关强制控制。
