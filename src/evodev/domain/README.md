# 领域模型

本目录定义 Task、TaskRun、Agent、Workflow、Experience 及状态枚举等核心业务对象。
领域模型应尽量保持框架无关，不直接依赖 FastAPI、LangGraph 或具体数据库实现。

`evolution.py` 定义 Prompt 版本、异步进化任务和真实 A/B 评测结果。
