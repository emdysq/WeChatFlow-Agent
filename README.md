<div align="center">

# WeChatFlow Agent

**从选题、写作、审稿到公众号草稿箱的可审阅 Agent 内容工作流**

Windows 交付 · 任务级状态 · 修改提案 · 18 套主题 · 微信草稿 · 131 项测试

[![License: MIT](https://img.shields.io/badge/License-MIT-2563eb)](LICENSE)
[![CI](https://github.com/emdysq/WeChatFlow-Agent/actions/workflows/checks.yml/badge.svg)](https://github.com/emdysq/WeChatFlow-Agent/actions/workflows/checks.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-0f766e)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-131%20passed-16a34a)](tests)
[![Canary](https://img.shields.io/badge/WeChat%20draft-canary%20passed-07c160)](WECHAT_CANARY_CHECKLIST.md)

</div>

---

WeChatFlow Agent 是我围绕真实公众号运营流程构建的本地 Agent 内容工作流。它把文章任务书、
事实来源、初稿、审稿、修改提案、微信兼容排版和草稿创建放进同一个可恢复任务中。

工程基于 MIT 开源项目 WeWrite 的内容管道构建；本项目重点完成 Windows 原生交付、可接受/
拒绝的改稿提案、发布 Dry-run、任务级远程写入控制、微信 API 合约测试和真实公众号 Canary。
开源来源与保留范围见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 为什么做这个项目

公众号运营中，选题、资料核对、反复改稿、排版、素材上传和草稿同步分散在多个工具里。
常见问题不是“不会生成一篇文章”，而是：

- AI 修改缺少可审阅过程，容易直接覆盖原文；
- 排版完成前才发现图片、摘要或微信兼容性问题；
- Windows 环境安装、中文输出和复现成本高；
- 本地成稿、预览产物和远程草稿缺少统一任务记录。

## 核心工作流

```text
用户主题 / 资料
  → Article Brief
  → Claims + Sources
  → Draft
  → Editorial Review
  → Proposal Diff（可接受 / 拒绝）
  → WeChat HTML Preview
  → Publish Dry-run
  → 人工确认
  → 微信草稿箱
```

每篇文章保存在独立 run 中：

```text
brief.yaml
claims.yaml
sources.yaml
draft.md
proposal.md + proposal.json
review-report.json
article.md
preview.html
草稿 media_id（仅本地状态）
```

## 我完成的关键能力

### 1. 可审阅 Agent 改稿

任务可以使用 `proposal` 模式启动。AI 候选稿先生成 unified diff，用户决定后再落成稿：

```powershell
wechatflow run start --topic "AI Agent 与内容工作流" --review-mode proposal
wechatflow proposal create --summary "修正标题并补充结论边界"
wechatflow proposal show
wechatflow proposal accept
# 或
wechatflow proposal reject --reason "保留原结构"
```

### 2. 发布 Dry-run 与真实草稿链路

正式写入前可生成不联网的发布计划，检查标题、摘要、正文、主题、封面、图片动作、HTML
兼容性和阻断项：

```powershell
wechatflow publish article.md --cover cover.png --dry-run --dry-run-output publish-plan.json
```

微信链路已覆盖：

```text
GET  /cgi-bin/token
POST /cgi-bin/media/uploadimg
POST /cgi-bin/material/add_material
POST /cgi-bin/draft/add
```

真实 Canary 已成功创建公众号测试草稿，并由后台人工确认标题、正文排版和封面正常。项目
没有调用正式发表或群发接口。

### 3. Windows 原生交付

```powershell
git clone https://github.com/emdysq/WeChatFlow-Agent.git
Set-Location .\WeChatFlow-Agent
.\install.ps1
```

安装器使用独立虚拟环境，安装 CLI 和 Agent Skills，保存精确安装清单；重复运行不会覆盖
同名无关目录。卸载默认保留文章、配置和凭据：

```powershell
.\uninstall.ps1 -Confirm:$false
```

中文 Windows 主机上的 `cp932` 输出崩溃已在统一 CLI 边界修复。

### 4. 一键离线 Demo

```powershell
.\scripts\demo.ps1
```

Demo 不读取公众号密钥、不联网，依次执行 Markdown 转换、微信 HTML 兼容性校验和文章质量
评分，并输出可审计的 `demo-report.json`。

## 验证结果

| 项目 | 结果 |
|---|---|
| 上游测试基线 | 112 passed |
| 当前完整回归 | 131 passed |
| Windows 生命周期 | install → CLI → uninstall passed |
| 微信 API Mock | token → 图片 → 封面 → draft/add passed |
| 真实公众号 Canary | 草稿创建成功，后台人工验收通过 |
| 正式发表 / 群发 | 未执行 |

运行测试：

```powershell
python -m pytest -q
```

## 效果预览

内置 18 套微信主题。以下截图由仓库中的真实示例文章渲染：

<table>
<tr>
<td width="33%" align="center"><img src="docs/screenshots/professional-clean.png" width="250"><br><sub><b>professional-clean</b></sub></td>
<td width="33%" align="center"><img src="docs/screenshots/sspai.png" width="250"><br><sub><b>sspai</b></sub></td>
<td width="33%" align="center"><img src="docs/screenshots/warm-editorial.png" width="250"><br><sub><b>warm-editorial</b></sub></td>
</tr>
</table>

```powershell
wechatflow gallery
wechatflow preview docs/demo-article.md --theme professional-clean
```

## 架构

```text
Prompt / Agent Skills
  ├─ topic / write / review
  ├─ visual / publish
  └─ learn / stats / rewrite
          ↓
Python Runtime
  ├─ run state + source ledger
  ├─ proposal diff
  ├─ Markdown renderer
  ├─ publish preflight
  └─ WeChat API
          ↓
$WEWRITE_HOME / ~/.wewrite
  └─ config + runs + history + output
```

设计原则：Agent 负责开放式判断，Python 负责确定性转换、状态和外部调用。

## 使用边界

```text
写一篇公众号文章                → 审过的本地成稿（默认不生图、不发布）
```

配图、排版、发布都能在文章完成后单独执行，排版和发布不会偷偷触发生图。

已完成文章可以继续
配图、排版或发布，原始正文不被覆盖。

全部 18 个主题：`bauhaus`、`bold-green`、`bold-navy`、`bytedance`、
`elegant-rose`、`focus-red`、`github`、`impeccable`、`ink`、
`lobster-notes`、`midnight`、`minimal-gold`、`minimal`、`newspaper`、
`professional-clean`、`sspai`、`tech-modern`、`warm-editorial`。

## 常用命令

```powershell
wechatflow diagnose
wechatflow run start --topic "主题"
wechatflow score article.md --json
wechatflow content-eval --draft draft.md --final article.md --assessment assessment.yaml --json
wechatflow hotspots --limit 20
wechatflow search-articles "AI 编程" -n 10
wechatflow seo --json "AI Agent"
wechatflow learn-edits --help
wechatflow learn-theme <公众号文章 URL> --name my-theme
wechatflow exemplar article.md
wechatflow fetch-article <公众号文章 URL> -o article.md
wechatflow llm-write --help
wechatflow similarity article.md rewrite.md
wechatflow build-playbook
wechatflow image-gen --help
wechatflow image-post p1.jpg p2.jpg -t "图文标题" --confirm-publish
wechatflow preview article.md --theme sspai
wechatflow validate preview.html --json
wechatflow publish article.md --cover cover.png --dry-run
wechatflow proposal show
wechatflow themes
wechatflow gallery
```

为兼容现有 Agent Skills 与状态目录，`wewrite` 命令仍然可用。

## 配置

写作、审稿、排版和离线 Demo 不需要微信公众号凭据。只有创建草稿时需要在本机状态目录
配置 AppID 与 AppSecret：

```powershell
Copy-Item config.example.yaml "$HOME\.wewrite\config.yaml"
```

不要把密钥写入 Git、README、Issue 或聊天记录。

## 项目材料

- [项目案例与面试说明](PROJECT_CASE_STUDY.md)
- [工程审计与真实性边界](WECHATFLOW_CUSTOMIZATION_AUDIT.md)
- [真实草稿 Canary 清单](WECHAT_CANARY_CHECKLIST.md)
- [内容质量规则](docs/content-quality-rubric.md)

## 当前边界

- 已验证本地内容管道、Windows 交付、改稿提案、Mock 微信链路和真实草稿创建。
- 没有统一 Web 工作台。
- 没有真实用户增长指标。
- 没有验证正式发表、群发或草稿更新。

## 开源与许可

本仓库保留 MIT License。工程基础来自 WeWrite，新增实现、测试和项目材料由本仓库维护者
完成。详细归属见 [THIRD_PARTY.md](THIRD_PARTY.md)。
