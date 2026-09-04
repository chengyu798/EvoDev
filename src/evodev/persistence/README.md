# 持久化适配

本目录保存领域记录、LangGraph Checkpoint 和本地 Artifact Store 的持久化适配。
业务代码应依赖抽象接口，PostgreSQL 连接和文件系统细节应留在此层。

- `artifacts.py`：按运行保存测试结果、Agent 轨迹、评测结果和 Git Patch。
- `checkpoints.py`：管理 LangGraph 官方 PostgreSQL Checkpointer，并校验数据库连接地址。
- `experiences.py`：保存结构化 Experience，按标签检索并幂等记录使用次数。
- `evolution.py`：管理 Prompt 进化任务队列、候选版本、激活状态和回滚。
