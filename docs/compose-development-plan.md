# WeChatFlow Agent 一键出稿开发计划

## 1. 项目目标

把当前已经验证的“任务状态、审稿、排版、图片和公众号草稿”能力，收敛为一个可直接使用的
内容生产入口：用户只提供主题、文字/文档素材和可选图片，系统自动生成任务书、事实与素材
清单、初稿、编辑审查、修改后成稿和微信预览。

目标交互：

```powershell
wechatflow compose `
  --topic "普通人应该如何使用 AI Agent" `
  --material .\materials `
  --image .\images\workflow.png `
  --theme professional-clean
```

默认只生成本地成稿与预览，不自动创建公众号草稿，更不自动正式发布或群发。创建草稿继续
沿用现有的人工确认和 `publish` 命令。

实施状态（2026-09-03）：M1 模型层、M2 素材摄取和 M3 一键编排已完成；M4 的 143 项自动
测试与本机交付检查已通过；真实 DeepSeek Smoke Test 已生成成稿并通过自动审稿及微信预览检查。

## 2. 研究结论

### 2.1 现有代码可以复用的部分

- `runs.py` 已有独立、可恢复的文章任务状态。
- `llm-write` 已能调用 OpenAI 兼容的 `/chat/completions`，但只能读取预先整理好的 brief。
- `content_eval.py` 已定义准确性、观点、实用性、声音和可读性五维编辑报告。
- `converter.py` 已能把 Markdown 转换成 18 套主题的微信兼容 HTML。
- 图片模块已支持用户图片、AI 生图、多 provider fallback 和图片预算上限。
- 发布模块已完成 Dry-run、微信 API Mock 和真实公众号草稿 Canary。

因此不重写排版、图片或发布模块。本阶段只补齐模型抽象、素材摄取和自动编排。

### 2.2 模型接口研究

DeepSeek 当前官方接口继续兼容 OpenAI Chat Completions，基础地址为
`https://api.deepseek.com`；官方当前列出的文本模型为 `deepseek-v4-flash` 和
`deepseek-v4-pro`。图片理解使用 `deepseek-v4-flash-vision-exp`，支持 JPEG、PNG、GIF、
WebP，并接受 Base64、URL 或 Files API 输入。DeepSeek 也支持 JSON Output，适合任务书和
审稿报告等结构化阶段。

Google Gemini 官方同样提供 OpenAI 兼容入口并支持 `image_url` 内容块。因此 v1 不绑定某个
SDK，而是实现一个 OpenAI-compatible HTTP 适配器；DeepSeek 作为默认配置，其他服务通过
`base_url + model + api_key` 接入。

参考：

- <https://api-docs.deepseek.com/>
- <https://api-docs.deepseek.com/guides/vision/>
- <https://api-docs.deepseek.com/guides/json_mode/>
- <https://ai.google.dev/gemini-api/docs/openai>
- <https://platform.openai.com/docs/quickstart>

## 3. 用户场景与成功标准

### 场景 A：主题 + 文字材料

用户给一个主题和若干 Markdown、TXT、HTML、JSON、YAML、CSV、PDF 或 DOCX 文件，系统应：

1. 提取并标记每份用户材料；
2. 生成任务书和只基于材料的主张清单；
3. 生成 1200–2500 字公众号初稿；
4. 自动审稿，必要时完成一次修改并复审；
5. 输出成稿和微信预览。

### 场景 B：主题 + 图片素材

系统把图片复制到任务目录，调用视觉模型提取内容、可用事实、图注和建议插入位置；写作模型
只能引用视觉分析中明确出现的信息。采用的图片通过占位符插入文章，原始图片不被修改。

### 场景 C：模型或材料不足

- 未配置 API Key：在任何付费调用前报出明确配置提示。
- 图片存在但没有视觉模型：保留图片清单，标记“未解析”，不编造图片内容。
- 审稿结论为 `needs_input`：保留全部中间产物，不把文章标为完成。
- 第二次审稿仍不通过：输出当前版本和问题清单，任务保持可恢复状态。

### v1 验收标准

- 一个命令完成摄取、规划、写作、审稿、修改和预览。
- 所有中间产物写入独立 run，失败后可检查和恢复。
- 用户图片可被视觉模型理解，并能稳定插入成稿副本。
- 本地测试完全 Mock 模型调用，不消耗 API 额度。
- 默认不触发图片生成、微信公众号写入或正式发布。
- Windows 和 Linux CI 全部通过。

## 4. v1 功能范围

### 纳入

- 新命令 `wechatflow compose`。
- DeepSeek 默认配置和通用 OpenAI-compatible provider。
- 文本、常见结构化文件、HTML、PDF、DOCX 解析。
- JPEG、PNG、GIF、WebP 图片理解。
- 结构化任务书与主张清单。
- 初稿生成、最多两轮审稿、一次自动修改。
- 用户图片复制、占位符替换与相对路径插入。
- Markdown 成稿、审稿 JSON、执行报告和微信 HTML 预览。
- 任务状态、错误记录、调用 usage 记录。

### 暂不纳入

- 自动联网搜索和网页事实核验。
- 音频、视频素材转写。
- Web 操作后台和多人协作。
- 向量数据库或长期 RAG。
- 自动创建公众号草稿、正式发布或群发。
- 自动生成配图。现有 `image-gen` 仍作为成稿后的独立步骤。

## 5. 技术设计

### 5.1 模块划分

```text
compose CLI
  ├─ material_ingest.py       本地文件解析、图片复制、素材包
  ├─ model_client.py          OpenAI-compatible 文本/JSON/视觉调用
  ├─ compose_pipeline.py      规划、写作、审稿、修改、预览编排
  ├─ runs.py                  任务状态与产物路径
  ├─ content_eval.py          确定性编辑报告
  └─ toolkit/converter.py     微信 HTML
```

### 5.2 产物

```text
runs/<run_id>/
  state.yaml
  materials.md
  assets/
  brief.yaml
  claims.yaml
  draft.md
  review-report.json
  article.md
  preview.html
  compose-report.json
```

### 5.3 模型职责

| 阶段 | 默认模型 | 输出 |
|---|---|---|
| 图片理解 | `deepseek-v4-flash-vision-exp` | 图片摘要、事实、图注建议 |
| 规划 | `deepseek-v4-flash` | JSON 任务书与主张 |
| 写作 | `deepseek-v4-flash` | Markdown 初稿 |
| 审稿/修改 | 可单独配置 `deepseek-v4-pro` | JSON 审稿、Markdown 成稿 |

模型名均为配置项，不写死 provider。审稿阶段使用 JSON Output；正文阶段使用普通文本。

### 5.4 配置

```yaml
writer:
  provider: deepseek
  api_key: "在本机填写"
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"
  reviewer_model: "deepseek-v4-pro"
  vision_model: "deepseek-v4-flash-vision-exp"
  timeout_seconds: 180
  max_tokens: 6000
  retries: 2
```

环境变量优先：

```text
WEWRITE_WRITER_API_KEY
WEWRITE_WRITER_PROVIDER
WEWRITE_WRITER_BASE_URL
WEWRITE_WRITER_MODEL
WEWRITE_REVIEWER_MODEL
WEWRITE_VISION_MODEL
```

### 5.5 编辑闭环

```text
初稿
  → 审稿 JSON
  ├─ pass        → 成稿
  ├─ revise      → 修改 → 第二次审稿
  └─ needs_input → 停止并保留问题
```

程序只负责检查 JSON 结构和五维分数，不把语言风格的机械评分伪装成事实准确性验证。用户材料
统一标为 `user_provided`；模型不得把自己的补充记忆写成已验证事实。

## 6. 实施里程碑

### M1：基础设施

- 统一 writer 配置读取；
- 新增通用模型客户端；
- 更新 DeepSeek 默认模型；
- 为文本、JSON 和视觉请求建立 Mock 合约测试。

### M2：素材摄取

- 解析目录和文件；
- 提取 PDF/DOCX/HTML/纯文本；
- 复制图片并生成稳定资产编号；
- 输出 `materials.md` 和用户材料来源记录。

### M3：一键编排

- 新增 `compose` 命令；
- 生成 brief、claims、draft；
- 自动审稿、一次修改、复审；
- 插图占位符替换、成稿和预览生成；
- 状态与调用报告落盘。

### M4：验证与交付

- 单元测试、失败恢复测试和端到端 Mock 测试；
- 更新 README、配置示例和演示命令；
- 本地完整回归；
- 推送并等待 Windows/Linux CI；
- 使用本机 DeepSeek 配置执行真实模型 Smoke Test（已通过，未创建微信草稿或正式发布）。

## 7. 测试矩阵

| 测试 | 是否联网 | 通过标准 |
|---|---:|---|
| provider 配置覆盖 | 否 | YAML 与环境变量优先级正确 |
| 文本/PDF/DOCX 摄取 | 否 | 内容和来源标签正确 |
| 图片请求结构 | 否 | MIME、Base64、视觉模型正确 |
| 正常出稿 | 否 | 全部产物生成、任务 completed |
| revise 分支 | 否 | 修改后复审并生成最终报告 |
| needs_input 分支 | 否 | 不错误标记 completed |
| 预览兼容性 | 否 | 微信 HTML 无 ERROR |
| DeepSeek Smoke Test | 是 | 已真实生成 2,438 字符文章，审稿通过，未发布 |
| 全量回归 | 否 | 当前 143 项测试全部通过 |

## 8. 风险与取舍

- **模型输出不稳定**：结构化阶段使用 JSON Output，并进行本地字段校验。
- **图片理解成本**：逐图调用、记录 usage；不默认生成新图片。
- **材料过长**：v1 按文件截取并明确记录，后续再做分块摘要和长文 RAG。
- **事实幻觉**：只允许引用材料包中的事实；无法确认的内容必须写成判断或删除。
- **兼容服务差异**：v1 保证 DeepSeek；其他兼容服务做请求形状兼容，不承诺所有私有参数。
- **一键不等于无人审核**：输出目标是“可审阅成稿”，公众号写入仍需人工确认。

## 9. 完成定义

当用户能在一台新 Windows 主机上安装项目、配置本地模型 Key，使用一个主题、一个素材目录和
若干图片运行 `wechatflow compose`，得到任务书、主张、初稿、审稿报告、最终 Markdown 和
微信预览，并且所有 CI 通过时，v1 视为完成。
