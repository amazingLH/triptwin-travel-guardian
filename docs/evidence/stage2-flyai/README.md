# Stage 2 — Bailian Managed Agent + FlyAI Evidence

验证日期：2026-10-10（Asia/Shanghai）

## 验证结论

- 阿里云百炼 Managed Agent 已挂载市场中的官方“飞猪旅行 V1.0” Skill。
- Agent 先通过 `read_skill_file` 读取 `search-hotel` 与 `search-poi` 参数说明。
- Agent 随后通过 `bash` 实际执行 FlyAI CLI，而不是根据模型记忆生成候选。
- 酒店查询返回 `status: 0`、`message: success`、10 条候选。
- 杭州博物馆查询返回 `status: 0`、`message: success`、10 条候选。

## 截图

- `01-hotel-tool-call-success.png`：Skill 文档读取、两次 bash 工具调用以及酒店成功结果。
- `02-poi-tool-call-success.png`：相同工具调用链以及博物馆成功结果。

截图已避开 API Key、账号名、Workspace ID、Agent ID、Environment ID 和 Session ID。FlyAI 属于飞猪官方能力，并非本项目原创；本项目负责场景编排、TripGraph、风险检测和重规划逻辑。
