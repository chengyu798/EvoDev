# LangGraph 工作流

本目录保存 EvoDev 的状态、节点、路由、工作流规格和 LangGraph 编译入口。循环和
终止条件必须显式表达，且必须受最大迭代次数限制。大型日志和 Diff 不应写入 Graph State。

`compiler.py` 支持注入真实节点或测试节点；生产运行使用 PostgreSQL Checkpointer，并以
`run_id` 作为 `thread_id`。测试失败进入 Failure Analyzer，审查失败返回 Developer，
所有自动修改路径最多执行三轮。

分析节点会先按标签检索历史经验；失败终止节点会从问题分析和失败诊断中生成结构化经验。
工作流结束后另存 `run-metrics.json`，记录版本、Token、耗时和重试次数。
