# WeWrite → WeChatFlow 开源构建审计基线

更新时间：2026-09-03
上游：`imraywang/wewrite`
上游基线：`bbf6d1a`
本地分支：`feat/wechatflow-customization`

## 1. 当前结论

WeWrite 不是传统 Web SaaS，而是面向 Codex、Claude Code 等 Agent 的公众号内容生产系统：

```text
用户意图
→ Skill 路由与内容判断
→ Python CLI 确定性操作
→ run 级状态与产物
→ 本地文章 / 配图 / HTML 预览 / 微信草稿
```

它适合作为 WeChatFlow 的工程基座，因为代码体量可控、工作流完整，并且内容判断与外部
副作用已经有清楚的分层。不过 README 中的完整能力不等于全部经过本机或真实公众号验证，
后续必须继续区分自动测试、本地验收、Mock 微信和真实公众号 Canary。

## 2. 已完成的基线验收

- 使用 Python 3.12 创建独立 `.venv` 并以 editable 模式安装。
- 上游原始测试：`112 passed`。
- 修改后完整测试：`143 passed`。
- 上下文预算门：通过，首次运行静态文档约 6,389 tokens。
- 18 套主题：能够正常发现和加载。
- `docs/demo-article.md`：成功转换为本地 HTML。
- HTML 兼容性校验：通过。
- 真实微信公众号 Canary：已于 2026-09-02 在用户授权后成功获取 token、上传永久封面并创建
  测试草稿；用户随后在公众号后台确认标题、正文排版和封面显示正常。未调用正式发布或群发接口。

本地验收产物保存在 `.artifacts/`，该目录被 Git 忽略。

## 3. 架构地图

### Prompt 层

`skills/` 包含一个主入口和九个模块，负责选题、写作、审稿、视觉、排版发布、学习、数据复盘
和多平台改写。模型负责开放式判断，但不应直接实现确定性副作用。

### Runtime 层

`src/wewrite/cli.py` 是统一命令入口；`commands/` 管理诊断、任务、来源、质量、检索与学习；
`model_client.py`、`material_ingest.py` 和 `compose_pipeline.py` 负责兼容模型、素材摄取与一键出稿；
`toolkit/` 管理 Markdown 转换、主题、图片 Provider 和微信 API。

### State 层

每篇文章位于 `$WEWRITE_HOME/runs/<run_id>/`，关键产物依次为：

```text
brief.yaml
→ claims.yaml + sources.yaml
→ draft.md
→ review-report.json
→ article.md
→ article-illustrated.md（可选）
→ preview.html
→ 微信草稿 media_id（可选）
```

完成后的正文不可继续覆盖，只允许追加视觉和发布结果。

## 4. 已发现并处理的问题

### Windows 非 UTF-8 控制台崩溃

在当前中文 Windows 主机上，Python 输出流被识别为 `cp932`。诊断、主题、预览和校验命令在
打印中文或 `✓` 时抛出 `UnicodeEncodeError`，尽管 HTML 已经生成。

处理：在统一 CLI 边界把 stdout/stderr 配置为 UTF-8，并通过强制 ASCII 父输出环境的子进程
测试锁定回归。

### 发布授权只存在于 Prompt 约定

上游 Skill 要求用户明确授权，但原始 `wewrite publish` 可以绕过任务状态直接发起远程写入。
Prompt 规则不能构成可靠的安全边界。

处理：新增确定性发布门禁。

- Agent 任务必须完成并审稿通过。
- 输入必须是当前任务的 `article` 或 `illustrated_article`。
- 必须存在明确发布权限。
- 权限在远程请求前一次性消费，失败重试需要重新授权。
- 独立 CLI 用户必须显式传入 `--confirm-publish`。
- 图片帖也必须显式确认远程写入。
- 封面缺失或路径无效时在获取 token 前失败。

## 5. 暂未验证或仍需改进

按优先级排序：

1. 可视化工作台：当前主要通过 Agent 对话和文件产物操作，已有文件级 diff 提案，但没有统一
   的 run、来源、提案和预览界面。

已经完成：

- 发布 Dry-run：生成标题、摘要字节数、正文长度、图片动作、HTML SHA-256、兼容性结果、
  阻断项和授权状态；不读密钥、不联网、不消费授权。
- 微信 API Mock：覆盖 token → 正文图片 → 封面 → `draft/add`，同时验证 HTTP URL/参数/
  multipart/超时、正文 URL 替换与一次性授权消费。
- 真实公众号 Canary：覆盖 token → 永久封面 → `draft/add`，草稿后台人工验收通过；一次性授权已
  消费，返回的草稿 `media_id` 仅保存在 Git 忽略的本地运行状态中。
- Windows 原生交付：新增幂等 `install.ps1`、默认保留用户状态的 `uninstall.ps1` 和不读取
  密钥、不联网的 `scripts/demo.ps1`；已在隔离目录真实跑通安装 → CLI → 卸载。
- 可审阅修改提案：任务可用 `--review-mode proposal` 启动，候选稿生成 unified diff；用户可
  `accept` 后复制为成稿，或 `reject` 后保留原文。按产品取舍保持简单，不做哈希或冲突校验。
- 一键 AI 出稿：新增 `compose`，支持常见文档与图片素材、DeepSeek/兼容模型、结构化任务书、
  两轮审稿、一次自动修改、用户图片插入和微信 HTML 预览；端到端 Mock 已通过。真实 DeepSeek
  Smoke Test 使用 2 份文档和 1 张图片生成 2,438 字符成稿，审稿通过，预览检查为 0 错误、
  0 警告；未创建公众号草稿或正式发布。

## 6. 建议的功能扩展边界

求职版本聚焦四条主线：

1. **Windows/FDE 交付**：可重复安装、诊断和一键本地 Demo。
2. **安全发布闭环**：一次性授权、Dry-run、Mock 集成测试、真实 Canary 证据。
3. **可审阅 Agent 协作**：把 draft → final 的变化呈现为可接受/拒绝的修改建议。
4. **多模态一键出稿**：主题与用户素材 → 规划 → 写作 → 审稿 → 成稿 → 微信预览。

暂不开发账号系统、云端多租户、复杂桌面客户端、多 Agent 平台或完整 CMS。

## 7. 简历真实性边界

当前可以陈述：基于 MIT 开源项目完成本地验收与功能扩展；复现并修复 Windows 编码问题；
将公众号发布授权从 Prompt 约定下沉为确定性运行时门禁；新增一次性权限、产物绑定和回归测试；
完成真实公众号 Canary，并由后台人工确认草稿标题、正文排版和封面正常；补齐 Windows
安装/卸载/离线 Demo，并实现可接受或拒绝的改稿提案。

当前不能陈述：已有正式发布/群发验证、已有真实用户指标、完整 AI 写作质量得到业务验证，
或项目由本人从零开发。
