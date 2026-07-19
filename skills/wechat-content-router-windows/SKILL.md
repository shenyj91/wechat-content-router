---
name: wechat-content-router-windows
description: >
  Windows 版微信内容路由 skill。把微信里转来的内容链接自动识别并导入 Obsidian 或本地普通文件夹。当前优先支持“小红书链接/分享文案”和“微信公众号文章链接”。Windows OCR 使用 PaddleOCR。不要用于批量扫描整个微信，也不要用于社交互动。
---

# wechat-content-router-windows

这个 skill 是 **Windows 版微信入口路由 skill**。

它不只处理小红书，还处理微信公众号；而且不一定非要进 Obsidian，也可以直接下载到本地文件夹。

这个版本是为了把 Windows 发布入口单独拆出来，避免用户误装 macOS OCR 版。

## 首次调用规则

如果这是安装后的首次调用，或者当前还没有 `scripts/config.json`：

1. 不要先讲大段说明
2. 不要在聊天里替用户填写路径，也不要把“其他补充...”当成真实文件夹选择
3. 应自动切到本地辅助配置脚本，不再在聊天里代填路径
4. 说明真实配置向导会先让用户选“本地 / Obsidian”，默认 OCR 开启，Obsidian 路径会先自动探测，不行再用目录选择器兜底
5. 如果用户选择微信自动扫描，只在本机向导里继续确认微信入口、监控方式和会话名；不要让用户手填 `session.db` / `message_dir` / `db_dir`
6. 只有用户已经完成本地配置后，再进入日常使用

当前 Windows OCR 后端：

- `PaddleOCR`
- `PaddlePaddle CPU`

## 什么时候用

- 把最近微信 filehelper 里的小红书/公众号链接导入 Obsidian
- 把这条微信公众号文章落库
- 把这条小红书分享文案落库
- 我不想手工判断链接类型，你自动识别

## 当前内置路由

- `xhs`：小红书链接 / 分享文案
- `mp`：微信公众号文章链接
- `feishu`：飞书文档 / wiki 链接

`xhs` / 公众号 / 飞书路由支持可选：

- 同时保存 `.pdf`
- 默认优先看 PDF 版式（当 `prefer_pdf_preview=true`）

当 `storage.mode=local` 时，`xhs`、公众号、飞书路由默认按 **PDF 主产物** 处理。

## 平台说明

- 平台：**Windows**
- OCR：**已接入（PaddleOCR，建议先本机验证）**

## 首次使用建议

先直接运行：

```bash
python3 scripts/use_router.py
```

Windows 也可以直接打开启动器：

```text
START-HERE.bat
```

它会先检查有没有 `config.json`：

- 没有：先进入首次配置向导
- 已有：直接进入使用菜单

说明一下：

- 当前 skill 安装机制本身没有“安装后立刻自动执行脚本”的钩子
- 所以最接近“安装后自动进配置”的做法，就是**首次启动时自动进入配置向导**
- Windows 用户可以直接打开 `START-HERE.bat`

首次配置时会依次确定：

- 保存到本地还是 Obsidian
- 如果是 Obsidian，优先自动识别 vault，再由目录选择器兜底
- 如果是本地，保存目录是什么
- 平时更想手动贴链接，还是自动扫描微信
- 如果开微信扫描，要扫哪个会话、按什么频率跑
- 微信账号优先自动识别；识别不到时，再让用户在本机选择可用账号

补充规则：

- OCR 默认开启，不再询问
- 不要让用户自己配置 `session.db` / `message_dir` / `db_dir`
- 微信自动扫描优先面向 Windows 微信 4.x：`xwechat_files/<账号>/db_storage`、`Weixin.exe`

## 工作流

### 模式 A：菜单式使用（推荐）

```bash
python3 scripts/use_router.py
```

进入后可选：

1. 手动粘贴一条链接/分享文案导入
2. 跑一次微信自动扫描
3. 按当前配置持续扫描微信
4. 重新配置

补充：

- 如果你在首次配置里选了“微信自动扫描”，启动后会先自动跑一次，再回到菜单
- 如果你只想自己点菜单，就选“手动粘贴链接/分享文案”

### 模式 B：直接导入单条内容

#### 小红书

```bash
python3 scripts/import_xhs_note.py "<小红书链接或整段分享文案>"
```

#### 公众号

```bash
python3 scripts/import_wechat_mp_article.py "<公众号文章链接>"
```

### 模式 C：走微信自动路由

先初始化配置：

```bash
python3 scripts/init_local_config.py --vault-root "/Users/yourname/Documents/ObsidianVault"
```

如果只是本地落盘，不接 Obsidian：

```bash
python3 scripts/init_local_config.py --mode local --local-root "/Users/yourname/Documents/ImportedContent"
```

然后直接运行：

```bash
python3 scripts/run_wechat_router_pipeline.py
```

## 输出要求

回复用户时优先给：

- 路由类型
- 标题
- 生成文件路径
- 图片数量（如果是 xhs）
- OCR 长度（如果是 xhs）
- 公众号名称（如果是 mp）

## 不要用于

- 发帖、点赞、评论、私信
- 平台级批量爬取
- 未经许可的大范围微信聊天扫描

## 资源

- [references/config-template.json](references/config-template.json)
- [references/routes.md](references/routes.md)
- `scripts/init_local_config.py`
- `scripts/run_wechat_router_pipeline.py`
- `scripts/import_latest_wechat_links.py`
- `scripts/import_xhs_note.py`
- `scripts/import_wechat_mp_article.py`
