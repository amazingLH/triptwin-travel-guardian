# 阶段 5 多模态解析证据

- `vision-result.json`：`qwen3.8-flash` 对合成行程图的真实解析结果、脱敏请求 ID、Token 用量、字段置信度及准确率。
- 输入图：`assets/hangzhou-golden-itinerary.png`，仅包含“演示旅客”和虚构订单信息。
- 47 个可见字段中 46 个与标准答案一致，准确率 97.9%；唯一差异是图片未标注酒店步行分钟，模型保守输出默认值 0。
- 文件不含 API Key、Authorization 头或真实个人信息。
