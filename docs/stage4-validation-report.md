# 阶段 4 验收报告：Managed Agents API 接入

验收日期：2026-10-12（Asia/Shanghai）

当前结论：**阶段 4 已完整通过验收。**

## 已完成

- 从本地 `.env` 读取百炼、Agent、Environment 与 FlyAI 配置；API Key 使用 `SecretStr`，日志和证据均脱敏。
- 通过北京地域 Managed Agents REST API 创建 Session、发送 Event、轮询 Event 历史并解析终态。
- 将本地 TripGraph 的 5 个确定性风险作为结构化上下文发送给 Agent。
- Agent 激活官方 `flyai` Skill、读取命令文档，并在云端沙箱真实执行 FlyAI CLI 查询。
- 使用免费模型 `qwen3.8-flash` 增量补查 2026-10-19 至 2026-10-20 的杭州西湖酒店，不重复查询已完成的景点。
- 将结构化候选和脱敏调用轨迹保存到 `docs/evidence/stage4-api/`。
- 本地候选验证器检查 FlyAI 执行证据、飞猪来源链接、预算、受保护节点和风险覆盖率。

## 云端真实结果

```text
Managed Agent session: end_turn
增量酒店会话事件数: 109
工具调用/输出: 25 / 25
错误数: 0
累计有效 FlyAI 查询证据: 7
新增酒店查询: 4（均 exit_code=0、status=0）
酒店候选: 6
密钥泄露: 0
```

景点候选来自杭州博物馆、西湖相关 POI 和“杭州室内景点 低步行 雨天”查询；酒店候选来自杭州西湖、入住 2026-10-19、退房 2026-10-20 的真实查询。所有入选候选均带飞猪 `router.feizhu.com` 来源链接。

## 本地最终验证

```text
valid: true
flyai_evidence_valid: true
protected_event_ids_untouched: true
入选候选: 4
未覆盖风险: 0
拒绝原因: 0
pytest: 21 passed
```

最终选择保留 3 个原有景点替代候选，并新增“如家精选-杭州西湖景区苏堤店”作为第二晚住宿候选，增量价格为 135 元，低于 500 元 Plan B 增量上限。`hotel-west-lake` 与 `train-sh-hz` 等受保护节点保持不变，未执行预订或支付。

## 验收证据

- `docs/evidence/stage4-api/smoke-trace.json`：脱敏后的云端会话及工具调用轨迹。
- `docs/evidence/stage4-api/candidates.json`：合并后的真实 FlyAI 候选。
- `docs/evidence/stage4-api/candidate-validation.json`：本地确定性验证结果，`valid=true`。

阶段 4 已结束，下一步进入阶段 5：完成 Gradio P0 页面与黄金案例演示。
