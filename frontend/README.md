# 前端应用

本目录是 EvoDev 的 React + TypeScript + Vite 前端工程。界面采用明亮的对话式 Agent
工作台布局，左侧集中管理历史任务，主区域通过自然语言输入创建任务，并以连续对话展示用户
目标和智能体响应。测试结果、智能体轨迹、代码差异和失败经验仍通过结构化证据区复查。

```bash
npm install
npm run dev
npm run lint
npm run test
npm run build
```

接口请求放在 `src/api/`，可复用视图组件放在 `src/components/`，测试公共配置放在
`src/test/`。
