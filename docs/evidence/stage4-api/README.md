# 阶段 4 脱敏证据

- `smoke-trace.json`：会话终态、工具名称、FlyAI 命令及简化执行状态；不含 API Key 和完整 Session ID。
- `candidates.json`：Agent 根据真实 FlyAI 查询生成的结构化候选，含飞猪来源链接。
- `candidate-validation.json`：本地确定性复核；第二晚住宿已由真实 FlyAI 酒店候选覆盖，当前为 `valid=true`。

完整说明见 `docs/stage4-validation-report.md`。

