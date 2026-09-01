# EvoDev

EvoDev 是一个基于 LangGraph 的多智能体软件修复系统。V0.1 的目标是接收本地
Python 仓库、Issue 描述和 pytest 命令，在受控工作流中生成可审查的 Patch、测试证据和
执行轨迹。

项目当前处于 V0.1 架构与骨架实现阶段，详见：

- `docs/01-一周开发任务清单.md`
- `docs/02-系统架构设计.md`

## 本地开发

```bash
uv sync --dev
cp .env.example .env
uv run evodev doctor
uv run evodev serve
```

默认 API 地址为 `http://127.0.0.1:8000`，健康检查地址为
`http://127.0.0.1:8000/api/health`。

在另一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

## 质量检查

```bash
uv run pytest
uv run ruff check .
```

## 沙箱镜像

```bash
docker build -t evodev-python:3.13 sandbox
```
