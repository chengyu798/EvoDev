# 持久化适配

本目录保存领域记录、LangGraph Checkpoint 和本地 Artifact Store 的持久化适配。
业务代码应依赖抽象接口，路径组装、SQLite 和文件系统细节应留在此层。
