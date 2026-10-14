---
# ModelScope Studio card metadata
domain: multi-modal
tags:
- Agent
- AI旅行
- 百炼
- 飞猪旅行
- 高德地图MCP
- Gradio
- TripGraph
datasets:
  evaluation:
  test:
  train:
models:
license: MIT License
---

# 途证哨 TuzhengGuard · 旅行数字孪生守护者

“途”是旅行，“证”是可追溯证据，“哨”是风险守护。项目现使用 `TuzhengGuard` 作为对外英文标识；改名范围与兼容说明见 [名称迁移记录](docs/name-migration.md)。

途证哨 将零散行程解析为结构化 `TripGraph`，使用确定性规则发现时间、日期、预算、体力和天气风险，再基于飞猪旅行真实候选生成可验证的 Plan B。它只做风险提示与候选推荐，**不会自动预订或支付**。

> 当前状态：最终发布候选版；[GitHub 公共仓库](https://github.com/amazingLH/tuzhengguard-travel-guardian)与 [ModelScope 公网 Demo](https://modelscope.cn/studios/L666H666Better/triptwin-travel-guardian)均已发布。

## 作品亮点

- **旅行数字孪生**：把车次、酒店、景点、同行人和约束统一为可计算的 TripGraph。
- **确定性风险引擎**：风险结论来自显式规则和证据，不让模型自由编造。
- **真实工具闭环**：百炼 Managed Agent 调用飞猪旅行 Skill/CLI 与高德地图 MCP。
- **受约束的 Plan B**：候选必须属于当前行程、总增量不超限、受保护订单不变，并通过 TripGraph 回放复检。
- **真实巡检**：用户行程使用独立 Managed Agent 会话实时调用高德 MCP 与 FlyAI；失败时停止，不借用示例结果。
- **隐私与可追溯**：密钥不入库；原始上传图片不进入浏览器历史；页面明确数据时效和未核验范围。
- **可落地交互**：支持 1–5 张截图合并、结构化校对、独立历史会话删除/清空，以及 JSON/ICS 导出。
- **解析后人工确认**：用户截图先生成草稿，缺少的日期、地点、价格等必要参数需补全，预算、人数与规则需确认；确认成功后才构建 TripGraph 并进入后续操作。已退票/取消订单显示原因并阻止构建有效出行计划。导入截图按纵向列表展示，支持框内滚动、悬停显示文件名及一键清空。
- **多图覆盖校验**：多张截图仍在一次请求中处理，但模型必须逐图返回独立结果；程序校验图片编号和对应事件，再合并行程。同一出发时间而目的地不同的车票不会去重。漏图或无法识别时停止构建，指出图片编号，不以残缺结果报告“0 风险”。旧多图历史须重新解析后再分析。编号覆盖校验不是字段正确率保证，仍需人工核对。
- **三组功能示例**：杭州完整行程、两段正常铁路衔接、三段冲突铁路行程。铁路示例来自所提供的脱敏车票截图，字段由人工核对，预算/人数为演示设置；示例解析与冲突分析不调用模型，不冒充实时高德或 FlyAI 结果。
- **可应用的局部 Plan B**：对可通过移除非受保护冲突项解决的时间冲突，枚举多个方案、重新校验依赖与预算、回放风险并展示比较表；用户选择后更新页面行程、时间线和风险，不执行实际订单退改。无法在本地解决或需要新供给的情况继续走真实工具链路。

## 架构

```mermaid
flowchart LR
    U[用户 / 行程图片] --> V[Qwen 视觉解析]
    V --> G[TripGraph]
    G --> R[确定性风险引擎]
    R --> A[百炼 Managed Agent]
    A --> F[飞猪旅行 Skill / CLI]
    A --> M[高德地图 MCP]
    F --> C[候选与来源链接]
    M --> X[路线 / 距离 / 天气证据]
    C --> P[Plan B 校验器]
    X --> R
    P --> W[Gradio 公网演示]
```

LLM 负责理解、编排和解释；TripGraph、风险规则、候选校验与证据文件负责约束结果。

## 已验证结果

2026-10-14 最新应用基线 `5a23154`：171 项测试、2 个离线案例、静态与编译检查通过；桌面及 390px 手机宽度回归覆盖巡检前未应用的 Plan B 保留、当前选择恢复、独立加载条秒数递增、连接失败重试及历史刷新。详见 [巡检方案与计时修复](docs/plan-inspection-progress-fix-2026-10-14.md)。此补丁需重新部署并复测。

前一应用基线 `596bcc7` 的加载修复已由作者确认重新部署；该部署记录不等于本次 `5a23154` 已部署或已验收。

前一基线 `a3c624e` 的多图请求逐图校验后程序合并；作者已确认该部署后重新上传两张重叠车票，均显示且检出重叠。不能将此记录当作最新加载修复也已在公网验收；见 [验收表](docs/public-acceptance.md)。

2026-10-13 品牌迁移与历史兼容回归：145 项测试、2 个离线案例、静态检查及编译检查通过；本地浏览器已确认新标题和既有会话恢复。历史键、密钥配置和限流参数未改变。本次未新增付费云端调用；创空间重新部署后再验收公网标题。

2026-10-13 最终审查：125 项测试、2 个离线案例与本地桌面/390px 手机宽度流程通过。完整问题、修复和未验证的线上边界见 [最终检查报告](docs/final-audit-2026-10-13.md)。本次未新增付费云端验收，公网需重新部署后复测。

- 历史单一黄金图片解析：47 个字段，准确率 97.9%，低置信字段 0；不是任意车票的总体准确率。
- 黄金案例：检出 5 个风险 / 335 分；验证后的 Plan B 未覆盖风险为 0。
- FlyAI：累计 7 条有效真实查询证据，命令均为 `exit_code=0`、业务 `status=0`。
- 高德 MCP：路线、距离、天气及 POI 搜索均已真实调用；未覆盖行程日期的天气不会被猜测。
- Deployment：首次手动巡检以 `end_turn` 正常结束，结构化记录见 `docs/evidence/stage6-deployment/run.json`。
- 自动化测试与离线验收：由 GitHub Actions 在 Python 3.11/3.12 自动执行。

## 本地运行

要求 Python 3.11+。

请使用项目虚拟环境，并安装 `requirements.txt` 中的固定版本；不要直接混用电脑上其他项目的 Gradio 环境。若未激活虚拟环境，也可直接执行 `.\.venv\Scripts\python.exe app.py` 或 `.\.venv\Scripts\python.exe -m pytest -q`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中配置自己的凭据：

```text
DASHSCOPE_API_KEY=
FLYAI_API_KEY=
BAILIAN_WORKSPACE_ID=
BAILIAN_AGENT_ID=
BAILIAN_ENVIRONMENT_ID=
DASHSCOPE_TEXT_MODEL=qwen3.7-flash
DASHSCOPE_VISION_MODEL=qwen3.7-flash
```

公开演示默认启用每日额度保护：每个浏览器最多 30 次提问和 15 次自行上传
图片解析，全站最多 500 次大模型问答和 300 次图片解析；每位访客最多 15 次实时
高德/FlyAI 核验，全站最多 350 次。重复问题使用浏览器缓存，
不重复调用模型；模型调用事件不暴露具名公开 API。额度可通过以下普通环境变量调整：

```text
TRIPTWIN_BROWSER_QUESTION_LIMIT=30
TRIPTWIN_BROWSER_IMAGE_LIMIT=15
TRIPTWIN_GLOBAL_QUESTION_LIMIT=500
TRIPTWIN_GLOBAL_IMAGE_LIMIT=300
TRIPTWIN_BROWSER_AGENT_LIMIT=15
TRIPTWIN_GLOBAL_AGENT_LIMIT=350
TRIPTWIN_BROWSER_STATE_SECRET=请生成至少32字节随机值
TRIPTWIN_RATE_LIMIT_SALT=请生成另一段至少32字节随机值
TRIPTWIN_USAGE_COUNTER_PATH=/tmp/triptwin-usage.sqlite3
```

然后启动：

```powershell
python app.py
```

默认监听 `0.0.0.0:7860`，本机访问 `http://127.0.0.1:7860/`。

## 测试

```powershell
python -m pytest -q
```

测试覆盖 TripGraph 引用与依赖环、时间重叠、风险规则、跨行程候选阻断、总预算与回放校验、百炼事件解析、密钥脱敏、动态问答、多会话隔离、高德证据与 Deployment 展示。另可运行 `python scripts/evaluate_offline.py` 执行凭据无关的发布验收。

## ModelScope Studio 部署

本项目使用 Gradio，根目录包含 `app.py`、`requirements.txt` 和 `ms_deploy.json`。在创空间的 **Secret/密钥** 配置中添加以下名称，不要把真实值写入代码或普通公开变量：

```text
DASHSCOPE_API_KEY
FLYAI_API_KEY
BAILIAN_WORKSPACE_ID
BAILIAN_AGENT_ID
BAILIAN_ENVIRONMENT_ID
TRIPTWIN_BROWSER_STATE_SECRET
TRIPTWIN_RATE_LIMIT_SALT
```

模型名称不是密钥，可按需在普通环境变量中覆盖；未配置时默认使用
`qwen3.7-flash`：

```text
DASHSCOPE_TEXT_MODEL=qwen3.7-flash
DASHSCOPE_VISION_MODEL=qwen3.7-flash
```

部署完成后必须使用无痕窗口和手机网络分别测试，并确认运行日志不包含凭据。

## 数据与能力边界

- 候选价格、库存、天气和交通结果都有时效性，页面展示的是对应获取时间的证据。
- 高德地理编码可能返回行政区级结果；精度不足时会明确告警，不冒充精确 POI。
- 浏览器历史仅保存在当前浏览器，最多 20 个会话；下拉选择后自动恢复行程、解析草稿、未提交补全、风险、Plan B、对话和小尺寸截图预览。预览也可能含隐私信息，请勿在共享浏览器留存个人订单；支持逐个删除和一键清空，不提供跨设备账户历史。原图不写入历史；旧版本未保存的截图需重新上传。
- 未配置密钥时，本地启动会在用户应用数据目录保留历史加密密钥，重启不再随机换钥。创空间仍须配置并保持 `TRIPTWIN_BROWSER_STATE_SECRET` 和 `TRIPTWIN_RATE_LIMIT_SALT` 不变，否则容器重建或换钥后无法读取旧历史。
- 上传原图会发送至百炼解析，应用不会自动给画面打码；临时上传和导出文件约 1–2 小时后清理。历史会话恢复文件名称列表与预览：原图仍有效时可重新解析，正常计入额度；原图过期时，点击解析复用该会话已有解析，不将低清预览当成原图发送给模型，保留风险、Plan B 和聊天。尚未解析或需要重新识别时需重传原图。临时文件引用经服务端签名及内容哈希校验，不接受任意本地路径。JSON/ICS 导出相互隔离，日历使用明确 UTC 时间。
- 公开站点中的自由问答、用户自传图片解析，以及用户行程的实时高德/FlyAI 核验会使用部署者额度；合成示例与本地确定性风险检查不调用模型。
- 限流计数使用 SQLite 原子事务，匿名访客标识只保存加盐哈希，不保存 IP、问题或图片；容器重建会清空本地计数，因此仍应在百炼侧开启余额/额度硬保护。
- 本地文件错误不扣解析次数；已发出的云端请求即使失败也可能计费，保留服务端次数，避免反复重试绕过保护。任务超时会尝试请求中断，但不能保证平台立即停止。
- 实时证据在 1 小时内复用；过期再次执行仍受每日额度限制。网页不为每位用户自动定时巡检；公开 Scheduled Task 记录属于历史演示。
- 真实候选必须对应本次成功 CLI 输出的名称、来源链接与单一价格。没有价格、只有区间价或证据不足时拒绝确认方案；不编造余票、费用或退改政策。
- 用户上传行程若没有当前会话的实时候选证据，系统不会展示公开杭州案例的 Plan B 或工具轨迹。
- 作品不执行预订、支付、退改或订单操作。
- `examples/` 与杭州图片为合成数据；三张铁路功能示例是获用户授权的脱敏订单素材，非纯合成图，预算/人数是明确的演示设置。

## 目录

```text
app.py                      Gradio 入口
src/triptwin/               TripGraph、风险、Agent 与展示服务
tests/                      自动化测试
evals/                      离线发布验收清单
examples/                   合成黄金行程
assets/                     合成杭州图片与脱敏铁路示例
docs/evidence/              脱敏的真实调用证据
docs/stage6-validation-report.md
```

## 参赛交付

当前应用代码基线为 `5a23154`，巡检方案与计时补丁待重新部署、复测。此前版本的部署及双图通过记录保留，不能自动继承为本补丁已通过。部署、验收与正式提交分别记录。

- [作品提交正文](docs/submission-draft.md)：用户场景、创新、百炼使用、真实证据与体验步骤。
- [部署后的提交步骤](docs/submission-guide.md)：截图、报名核对、官方作品 Issue 和回执。
- [公网验收表](docs/public-acceptance.md) / [参赛版本记录](docs/release-record.md)。

## AI 协作说明

本项目在代码实现、测试、文档与排错过程中使用了 AI 编程助手；产品定义、平台账号操作、真实工具授权、运行确认和最终提交由参赛者完成。所有外部工具结果均通过控制台事件或脱敏证据复核。

## License

项目原创代码采用 [MIT License](LICENSE)。`skills/triptwin-flyai/` 保留其原始 MIT 许可证与版权声明。

