# Stage 7 发布检查清单

## 已完成

- [x] 全量自动化测试：37 项通过。
- [x] Deployment 证据已保存，Stage 6 验收完成。
- [x] `.env` 与本地会话标识已写入 `.gitignore`。
- [x] 对 5 项真实配置值执行精确泄露扫描：源码、文档和证据均为 0 命中。
- [x] Gradio 关闭详细错误展示，公网监听地址和端口可由环境变量配置。
- [x] 用户问题作为 `untrusted_user_question` 传给模型，并增加提示注入回归测试。
- [x] `README.md`、`requirements.txt`、`app.py` 与 `ms_deploy.json` 已准备。

## 等待平台操作

- [x] 创建 GitHub Public 仓库 `triptwin-travel-guardian`。
- [x] 通过暂存区密钥扫描后推送至 `https://github.com/amazingLH/triptwin-travel-guardian`。
- [x] 创建公开 ModelScope 创空间 `L666H666Better/triptwin-travel-guardian`。
- [x] 合并平台生成的卡片元数据并将完整代码推送至 ModelScope `master` 分支。
- [ ] 在 Secret/密钥区配置 5 项变量；不得写入公开变量或仓库。
- [ ] 等待构建成功并记录公网 URL。
- [ ] 无痕窗口完整闭环连续运行 3 次。
- [ ] 手机网络运行 1 次。
- [ ] 检查公开仓库、页面与运行日志均无密钥。
- [ ] 记录最终验证时间。

## 必需 Secrets

```text
DASHSCOPE_API_KEY
FLYAI_API_KEY
BAILIAN_WORKSPACE_ID
BAILIAN_AGENT_ID
BAILIAN_ENVIRONMENT_ID
```

真实值只从本地 `.env` 复制到平台 Secret 配置，不进入截图、聊天或代码。

