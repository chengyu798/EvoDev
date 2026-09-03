# Python 测试

本目录保存 pytest 测试，目录结构应尽量与 `src/evodev/` 对应。涉及仓库的测试必须
使用临时工作区，不得修改真实项目；外部模型和网络调用应使用模拟。

`test_execution_pipeline.py` 是代码执行基础设施的端到端验收测试，覆盖独立仓库副本、
失败基线、补丁应用、Docker pytest、成功验证、Patch 生成和源仓库保护。

`test_agents.py` 验证 Agent 工具调用循环、权限边界和结构化输出；
`test_repair_workflow.py` 验证失败重试、三次终止、审查、产物生成和 SQLite 检查点。

```bash
uv run pytest
```
