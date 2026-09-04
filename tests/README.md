# Python 测试

本目录保存 pytest 测试，目录结构应尽量与 `src/evodev/` 对应。涉及仓库的测试必须
使用临时工作区，不得修改真实项目；外部模型和网络调用应使用模拟。

`test_execution_pipeline.py` 是代码执行基础设施的端到端验收测试，覆盖独立仓库副本、
失败基线、补丁应用、Docker pytest、成功验证、Patch 生成和源仓库保护。

`test_agents.py` 验证 Agent 提示词加载、工具调用循环、权限边界和结构化输出；
`test_repair_workflow.py` 验证失败重试、三次终止、审查和产物生成；
`test_experiences.py` 验证经验标签和失败轨迹提取；`test_postgres_integration.py` 使用可选
测试数据库验证 PostgreSQL 检查点及 Experience 的读写、检索和幂等计数。
`test_evolution.py` 验证 Prompt A/B 升级门槛和独立 Worker 编排。

```bash
uv run pytest
```

启动项目 PostgreSQL 后，可以额外执行真实数据库集成测试：

```bash
EVODEV_TEST_DATABASE_URL=postgresql://evodev:evodev@localhost:55432/evodev \
  uv run pytest -q tests/test_postgres_integration.py
```
