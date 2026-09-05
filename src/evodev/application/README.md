# 应用服务

本目录保存面向用例的应用服务，负责协调领域模型、工作流和基础设施。正式 HTTP 服务使用
PostgreSQL 保存任务、运行摘要和节点事件；内存仓库只用于自动化测试。

`DeterministicRepairService` 提供不依赖智能体的修复用例：创建独立仓库副本、运行基线
测试、应用受控补丁、运行修复后测试，并返回变更文件和完整 Patch。工作区会被保留，
便于失败诊断和人工复查。

`RepairWorkflowService` 组装四类 Agent、LangGraph 节点和 PostgreSQL Checkpointer，执行
完整的“分析—修改—测试—失败诊断—审查—生成补丁”闭环。模型或基础设施异常会转换为
包含错误编码和原因的失败状态。`RunService` 在后台线程调用该工作流，并将 LangGraph 每个
节点的状态更新转换为前端可轮询的运行事件。

`ReadOnlyAgentService` 组装对话与规划 Agent。对话 Agent 只能读取仓库和已有证据；规划
Agent 在临时隔离副本中读取代码并运行安全诊断，生成计划后立即清理临时工作区。计划未
经用户确认时，`RunService` 会拒绝启动修复。

`DemoCleanupService` 按运行编号删除手动测试产生的隔离工作区、运行输出和检查点，并可
安全删除临时示例仓库与 Docker 沙箱镜像。临时仓库路径必须通过范围和命名校验。

`PromptEvolutionWorker` 在独立进程中生成候选 Prompt、执行真实 Bug A/B 评测并决定升级
或拒绝，不会占用主修复请求的执行线程。
