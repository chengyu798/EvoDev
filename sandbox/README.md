# Docker 沙箱

本目录保存代码执行沙箱的镜像定义。`Dockerfile` 提供 Python 3.13、pytest 和非 root
基础环境。`DockerCommandRunner` 负责挂载任务工作区，并实施网络、CPU、内存、进程数量、
超时和输出大小限制。

```bash
docker build -t evodev-python:3.13 sandbox
```

任何执行权限扩大都应先评估对宿主机和源仓库的风险。
