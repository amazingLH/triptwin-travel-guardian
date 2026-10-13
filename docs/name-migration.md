# 途证哨 TuzhengGuard 名称迁移

日期：2026-10-13。旧对外名称为 TripTwin，现名称为“途证哨 TuzhengGuard · 旅行数字孪生守护者”。

## 名称含义和检索边界

途：真实旅行行程。证：订单截图、确定性规则、高德/FlyAI 来源证据。哨：识别风险并给出可校验的 Plan B。

2026-10-13 的公开网络检索未发现明确同名项目，GitHub 仓库搜索 `TuzhengGuard` 在更名前返回 0 条。此记录不是全球唯一性保证，也不是商标权利检索结论。

## 对外统一

- 网站标题、页头、问答区域、错误说明和模型提示词使用“途证哨”。
- GitHub 仓库改为 https://github.com/amazingLH/tuzhengguard-travel-guardian，origin 远端和当前文档链接同步修改。
- Python 发行名及新命令为 `tuzhengguard`；旧 `triptwin` 命令保留兼容。
- 合成行程确认单、ICS 生成者及新 Agent 会话标题使用新品牌。
- 创空间网页内标题随代码重新部署生效。创空间外层展示名称需在平台设置中单独修改；本次不迁移已有创空间 URL，不新建空间。
- 百炼 Managed Agent 的展示名称可改为 `tuzhengguard-sentinel`；已有 Agent ID、Skill ID 与环境 ID 不需要重建。

## 刻意保留的兼容标识

`src/triptwin` 内部包名、`skills/triptwin-flyai` 已配置 Skill 名称、`TRIPTWIN_*` 环境变量、`triptwin_sessions_v1` 浏览器历史键、签名域、临时文件前缀和本地数据目录仍保留。这些不是公开品牌，直接改动会破坏既有部署、历史解密或工具关联。

密钥、限流计数和已保存会话不因品牌改名而主动清空。创空间地址仍为 https://modelscope.cn/studios/L666H666Better/triptwin-travel-guardian；不要把这个旧路径误当成没更新网页标题。

`docs/evidence` 下的真实调用记录与历史截图不修改，避免篡改验真证据；旧截图里的品牌表示采集时版本。展示新品牌请重新截取当前页面，不修改历史证据图。

## 部署操作

1. 在原创空间重新部署最新 `master` 代码，密钥名和值保持不变。
2. 在创空间设置的基本信息中，将作品展示名称改为“途证哨 TuzhengGuard · 旅行数字孪生守护者”（若平台长度受限，可用“途证哨 旅行数字孪生守护者”）。
3. 百炼智能体如需统一展示名称，只修改名称，不重建智能体、不变更 ID。
4. 检查网站标题、提问标签、历史会话及导出功能，然后将报名材料中的作品名称和 GitHub 链接更新为新版。
