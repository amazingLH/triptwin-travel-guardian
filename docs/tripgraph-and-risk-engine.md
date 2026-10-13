# TripGraph 与确定性风险引擎

## 为什么不是只让大模型判断

途证哨 把行程先转换为结构化 TripGraph，再用可重复、可解释的规则检测关键风险。大模型负责理解输入和生成候选方案，确定性引擎负责最终校验，避免模型把时间、预算或缺失价格“猜对”。

## TripGraph 核心结构

- `Trip`：旅行 ID、版本、起止时间、旅客、约束、事件和风险。
- `TripEvent`：交通、住宿、活动、餐饮或接驳节点。
- `depends_on`：事件依赖关系。
- `transfer_from_event_id`：需要计算衔接时间的上游节点。
- `cost_cny`：已知成本；`null` 表示未知，不能视为 0。
- `proposed_extra_cost_cny`：Plan B 可能新增的成本。
- `walking_minutes` / `transfer_count`：老人友好度校验依据。

所有时间都必须携带时区，例如 `2026-10-18T10:00:00+08:00`。

## 阶段 3 的四类规则

1. 时间衔接：可用间隔必须不少于路线时间与安全缓冲之和。
2. 日期一致性：事件不能超出行程，住宿必须覆盖所有过夜日期。
3. 预算：检查已知成本、Plan B 新增成本、总预算和新增成本上限。
4. 体力：有老人或行动限制时，检查每日步行、活动数量和单段换乘。

天气敏感字段已进入模型，但真实天气规则留到阶段 6 接入高德 MCP 后启用。

## 黄金案例

- `examples/hangzhou_golden_trip.json`：故意包含 5 个确定性风险。
- `examples/hangzhou_plan_b_trip.json`：保留高铁和酒店核心节点，局部调整后风险降为 0。

运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m triptwin.cli examples\hangzhou_golden_trip.json
.\.venv\Scripts\python.exe -m pytest -q
```

