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
5. 如果用户选择微信自动扫描，先让他选数据源：
   - 内置 WCDB 解密并导入（默认、推荐）：会自动完成解密与读取
   - 直接扫描微信进程（实验模式）：仅保留给能接受不稳定结果的场景
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
- 默认不要让用户自己配置 `session.db` / `message_dir` / `db_dir`
- 内置 WCDB 解密模式会自动完成解密和导入，不要求用户手填这些路径
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

## 只读查看器（可选 · 进阶）

> 这是**可选附加功能**，不是主流程。主流程是上文「模式 C：走微信自动路由」——把链接转发到文件传输助手，一条命令自动识别并导入。查看器只在你想在网页里浏览整段微信聊天记录时才用。

本 skill 内置一个**微信聊天记录只读查看器**。解密与查询已改为**纯 Python**（`wcdb_decrypt.py` + `viewer_query.py`，零原生依赖），**不再依赖会崩溃的 `wcdb_api.dll` / `WCDB.dll`**；仅密钥提取仍用独立的 `wx_key.dll`（hook 微信进程）。把微信加密数据库解密后以网页聊天界面展示。

**特性**
- 纯只读：只 SELECT，绝不写入 / 删除 / 发送任何微信数据。
- 自动发现 Windows 微信 4.x 账号目录（`xwechat_files/<账号>/db_storage`）。
- 微信运行且已登录时，查看器**打开即自动提取**数据库密钥（走 `wx_key.dll`），**普通用户无需手动输入任何密钥**。仅在开发者调试时，才可在页面折叠的「高级」区手动粘贴密钥，或在 config 里配置 `key_file` 指定密钥文件（`key_file` 也是由提取工具生成的，不是让人手敲的 64 位 hex）。
- 会话列表（全部 / 私聊 / 群聊）+ 消息气泡（自己靠右、对方靠左）+ 关键词搜索。
- 多账号机器：默认进“最近登录（mtime 最新）”的账号；也可用环境变量 `VIEWER_WXID=<微信号>` 或 `config.json` 里的 `wechat.selected_account_wxid` 精确绑定某个号，避免进错号。

**启动（二选一）**
- 自动拉起：运行 `node scripts/launch-viewer.mjs`（服务已在 `127.0.0.1:8731` 则直接开浏览器；否则后台启动 `viewer-server.mjs` 并自动打开浏览器）。
- 手动：双击 `START-VIEWER.bat`（Windows）/ `START-VIEWER.command`（macOS）。

首次运行请先装依赖（**两条都要**）：
- Python 依赖：`cd scripts && pip install -r requirements.txt`（需要 `cryptography` 与 `zstandard`）。
- Node 依赖（**必装**，自动提取密钥用）：`cd scripts && npm install`（安装 `koffi`，`key-extractor.js` 通过它加载 `wx_key.dll`）。若没装 koffi，自动提取会直接报错“缺少依赖”，此时应回退去装依赖，而**不是**让客户手动粘贴密钥（普通用户根本没有那段 64 位 hex）。

**前提**
- 需安装 Node.js（https://nodejs.org）与 Python 3（含 `cryptography`、`zstandard`）。
- 解密与查询已完全脱离 WxLens 原生库，不再因 DLL（`wcdb_api.dll`/`WCDB.dll`）崩溃而失败；Windows 端自动提取密钥**无需关闭 SIP**（通过独立的 `wx_key.dll` 注入，它不触发那个反盗用崩溃）。若自动提取失败，请按页面提示排查（微信是否在运行并登录 / 是否执行过 `npm install` / macOS 是否关 SIP），**不要**让客户去手动粘贴 64 位 hex 密钥——普通用户没有那段密钥，那只是开发者调试入口。

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
