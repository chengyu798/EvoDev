# Python 测试

本目录保存 pytest 测试，目录结构应尽量与 `src/evodev/` 对应。涉及仓库的测试必须
使用临时工作区，不得修改真实项目；外部模型和网络调用应使用模拟。

```bash
uv run pytest
```
