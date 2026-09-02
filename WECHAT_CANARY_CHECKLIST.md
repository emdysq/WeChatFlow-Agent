# 微信公众号草稿 Canary 清单

目标：只向测试/次要公众号创建一篇草稿，绝不调用群发或正式发布接口。

## 验收结果（2026-09-02）

- [x] token 获取成功，无 IP 白名单错误。
- [x] 封面上传成功并返回永久素材 `media_id`。
- [x] `draft/add` 成功返回草稿 `media_id`。
- [x] 用户已在公众号后台确认中文标题、正文排版和封面正常。
- [x] 全程未调用正式发布或群发接口。
- [x] 一次性发布授权已消费；草稿结果仅记录于 Git 忽略的本地运行状态。

测试 run：`20260902-124132-df360e`。本文档不记录 AppID、AppSecret、access token 或
完整 `media_id`。

## 1. 用户需要准备

- 一个允许调用公众号草稿与素材接口的测试或次要公众号。第一轮不要使用主运营账号。
- 公众号 AppID 与 AppSecret。
- 将执行机器的公网出口 IP 加入公众号后台的 IP 白名单。
- 一个可在公众号后台人工检查草稿的管理员账号。

不要把 AppSecret 发到聊天、提交到 Git、写进 README 或截图。项目已经忽略 `.artifacts/`，
请只在本机创建：

```text
.artifacts/state/config.yaml
```

内容格式：

```yaml
wechat:
  appid: "在本机填写"
  secret: "在本机填写"
  author: "可选署名"
theme: "professional-clean"
```

Canary 完成后可以删除该文件，或撤销/重置 AppSecret。

## 2. 当前已经具备的安全条件

- 本地 HTML 已通过兼容性校验。
- Dry-run 不读取密钥、不发网络请求。
- 正式发布必须绑定已完成且审稿通过的任务产物。
- 发布权限为一次性，任何失败重试都需要重新授权。
- 封面或正文图片缺失时，在获取 token 前失败。
- 系统只调用草稿接口，不调用 `freepublish/submit` 或群发接口。

## 3. 执行顺序

1. 再次运行 Dry-run，并保存 JSON 计划。
2. 人工核对标题、摘要、主题、封面、图片动作、HTML 指纹和阻断项。
3. 确认 `content_ready=true` 且 `blockers=[]`。
4. 创建或恢复专用 Canary run，并保存文章、审稿报告与来源记录。
5. 用户明确说“允许创建测试草稿”。
6. 执行 `wewrite run permission publish allow`。
7. 调用 `wewrite publish`；CLI 在网络请求前消费一次性授权。
8. 记录返回的 `media_id`，由用户进入公众号后台人工检查。
9. 不调用正式发布；检查完成后可在后台删除测试草稿。

## 4. 实际网络调用

```text
GET  /cgi-bin/token
POST /cgi-bin/media/uploadimg              # 仅正文本地图片
POST /cgi-bin/material/add_material        # 封面永久图片素材
POST /cgi-bin/draft/add                     # 创建草稿
```

## 5. 通过标准

- token 获取成功且无 IP 白名单错误。
- 封面上传得到永久 `media_id`。
- 正文本地图片替换为微信图片 URL。
- `draft/add` 返回草稿 `media_id`。
- 公众号后台能看到草稿，中文标题、摘要、正文、排版和封面正常。
- 命令执行后任务中的 `permissions.publish` 自动恢复为 `false`。

## 6. 失败处理

- 保留 Dry-run JSON、错误码和不含密钥的安全错误信息。
- 不自动重试，不自动重新授权。
- 不在聊天或 Issue 中粘贴完整请求、token、AppID、AppSecret。
- 优先修复本地预检或账号权限问题，再由用户重新授权。

## 7. 接口参考

- 微信公众号获取 access_token：
  <https://developers.weixin.qq.com/doc/offiaccount/Basic_Information/Get_access_token.html>
- 微信公众号素材管理：
  <https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Adding_Permanent_Assets.html>
- 微信公众号新建草稿：
  <https://developers.weixin.qq.com/doc/offiaccount/Draft_Box/Add_draft.html>
