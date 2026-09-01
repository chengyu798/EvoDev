# Docker 沙箱

本目录保存代码执行沙箱的镜像定义。当前 `Dockerfile` 提供 Python 3.13 非 root 基础环境，
依赖安装、工作区挂载、资源限制和网络策略将由后续的 Sandbox Runtime 管理。

```bash
docker build -t evodev-python:3.13 sandbox
```

任何执行权限扩大都应先评估对宿主机和源仓库的风险。
