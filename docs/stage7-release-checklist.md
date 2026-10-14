# Stage 7 发布检查清单

最新本地回归（2026-10-14，应用基线 `596bcc7`）：164 项测试、2 个离线案例和桌面 / 手机宽度加载回归通过；参见 [加载修复记录](loading-fix-2026-10-14.md)。此前审查报告为历史记录，不代表最新测试数量。这不替代尚未完成的公网验收。

## 已完成

- [x] 全量自动化测试与离线发布验收通过（以最新 CI 数量为准）。
- [x] Deployment 证据已保存，Stage 6 验收完成。
- [x] `.env` 与本地会话标识已写入 `.gitignore`。
- [x] 对 5 项真实配置值执行精确泄露扫描：源码、文档和证据均为 0 命中。
- [x] Gradio 关闭详细错误展示，公网监听地址和端口可由环境变量配置。
- [x] 用户问题作为 `untrusted_user_question` 传给模型，并增加提示注入回归测试。
- [x] `README.md`、`requirements.txt`、`app.py` 与 `ms_deploy.json` 已准备。

## 等待平台操作

- [x] 创建 GitHub Public 仓库，现名为 `tuzhengguard-travel-guardian`。
- [x] 通过暂存区密钥扫描后推送至 `https://github.com/amazingLH/tuzhengguard-travel-guardian`。
- [x] 创建公开 ModelScope 创空间 `L666H666Better/triptwin-travel-guardian`。
- [x] 合并平台生成的卡片元数据并将完整代码推送至 ModelScope `master` 分支。
- [x] 在 Secret/密钥区配置必要变量；不得写入公开变量或仓库。
- [x] 构建成功并记录公网 URL。
- [x] `a3c624e` 部署后，作者重新上传两张重叠车票，确认两段均显示并检出重叠（2026-10-14）。
- [x] 重新部署包含 `596bcc7` 加载修复的版本（作者于 2026-10-14 确认）。
- [ ] 关闭旧页面再打开，复测置信度 / 证据面板不再被无关操作遮盖。
- [ ] 按 [公网验收表](public-acceptance.md) 补查最新示例闭环、历史、导出和会话隔离。
- [ ] 补做最新版本手机交互检查并保存结果。
- [ ] 检查最新公开页面与运行日志无密钥，提交图片已脱敏。
- [ ] 补最新运行截图并记录完整验收日期。

连续运行示例三次可作为稳定性自测建议，并非已核实的官方强制标准。不为勾选验收而重复发起收费调用。

## 材料与正式提交（阶段 8）

- [x] 更新 [正文草稿](submission-draft.md)、[版本记录](release-record.md) 与 [提交步骤](submission-guide.md)。
- [ ] 在正文补最新公网风险与 Plan B 截图（已有历史真实工具截图，不能冒充最新结果）。
- [ ] 作者核对主要提交人、报名意向和赛道登记回执。
- [ ] 作者正式提交官方作品 Issue，保存链接、编号与日期。
- [ ] 检查正式帖中的 Demo、代码和图片均可公开访问。

## 必需 Secrets

```text
DASHSCOPE_API_KEY
FLYAI_API_KEY
BAILIAN_WORKSPACE_ID
BAILIAN_AGENT_ID
BAILIAN_ENVIRONMENT_ID
TRIPTWIN_BROWSER_STATE_SECRET
TRIPTWIN_RATE_LIMIT_SALT
```

真实值只从本地 `.env` 复制到平台 Secret 配置，不进入截图、聊天或代码。

