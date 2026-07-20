---
name: wechat-content-router-macos
description: >
  macOS 版微信内容路由 skill。把微信里转来的内容链接自动识别并导入 Obsidian 或本地普通文件夹。当前优先支持“小红书链接/分享文案”和“微信公众号文章链接”，内置 macOS OCR（Swift + Vision）。不要用于批量扫描整个微信，也不要用于社交互动。
---

# wechat-content-router-macos

这个 skill 是 **macOS 版微信入口路由 skill**。

它不只处理小红书，还处理微信公众号；而且不一定非要进 Obsidian，也可以直接下载到本地文件夹。

当前 OCR 基于：

- `Swift`
- `Vision`
- `AppKit`

所以它适用于 **macOS**。

## 首次调用规则

如果这是安装后的首次调用，或者当前还没有 `scripts/config.json`：

1. 不要先讲大段说明
2. 直接进入“开始配置 wechat-content-router-macos”
3. 按顺序一步步问完：
   - 保存到本地还是 Obsidian
   - 路径是什么
   - 要不要开 OCR
   - 手动贴链接还是自动扫描微信
   - 如果自动扫微信：固定文件传输助手，还是固定某个聊天对象
   - 扫描频率是多少
4. 配置完成后，再进入日常使用

## 什么时候用

- 把最近微信 filehelper 里的小红书/公众号链接导入 Obsidian（macOS）
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

- 平台：**macOS**
- OCR：**可用**


## 首次使用建议

先直接运行：

```bash
python3 scripts/use_router.py
```

macOS 也可以直接双击：

```text
START-HERE.command
```

它会先检查有没有 `config.json`：

- 没有：先进入首次配置向导
- 已有：直接进入使用菜单

说明一下：

- 当前 skill 安装机制本身没有“安装后立刻自动执行脚本”的钩子
- 所以最接近“安装后自动进配置”的做法，就是**首次启动时自动进入配置向导**
- macOS 用户可以直接双击 `START-HERE.command`

首次配置时会依次问：

- 保存到本地还是 Obsidian
- 如果是 Obsidian，vault 路径是什么
- 如果是本地，保存目录是什么
- 要不要开 OCR
- 平时更想手动贴链接，还是自动扫描微信
- 如果开微信扫描，要扫哪个会话、按什么频率跑

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

### 模式 B：直接导入单条内容

#### 小红书

```bash
python3 scripts/import_xhs_note.py "<小红书链接或整段分享文案>"
```

#### 公众号

```bash
python3 scripts/import_wechat_mp_article.py "<公众号文章链接>"
```

### 模式 C：走微信自动路由（macOS 一键解密）

**真实流程**：用户把链接转发到指定微信人（默认「文件传输助手」filehelper）→ 一条命令自动解密微信 DB → 扫描该聊天 → 识别链接类型 → 导入。

先初始化配置：

```bash
python3 scripts/init_local_config.py --vault-root "/Users/yourname/Documents/ObsidianVault"
```

如果只是本地落盘，不接 Obsidian：

```bash
python3 scripts/init_local_config.py --mode local --local-root "/Users/yourname/Documents/ImportedContent"
```

补全 `scripts/config.json` 的 `wechat` 段：

```json
{
  "wechat": {
    "enabled": true,
    "chat_username": "filehelper",
    "message_dir": "/Users/yourname/Documents/wcr-decrypted"
  }
}
```

- `message_dir`：解密库（`session.db` + `message_0.db`）的输出目录，**必填**。
- `session_db` / `decrypt_python` / `decrypt_script` / `decrypt_workdir`：**留空即可**。
  macOS 上 `run_wechat_router_pipeline.py` 会自动接线内置一键解密桥
  （`decrypt_wechat_db.py` → `node decrypt_fetch.mjs` → 复用 WxLens 的
  `xkey_helper` + `libwcdb_api`，不碰任何解密算法），把解密结果写入 `message_dir`，
  再交给扫描器导入。
- 非 macOS（如 Windows）留空则跳过解密步骤，沿用「外部预解密」旧流程。

然后运行（一条命令闭环）：

```bash
python3 scripts/run_wechat_router_pipeline.py
```

**macOS 解密前提**
- 微信已登录且正在运行。
- 已关闭 SIP（恢复模式 → 终端 → `csrutil disable`），否则 `xkey_helper` 无法读取密钥。
- 首次运行会弹管理员授权框取密钥；之后密钥缓存在 `<message_dir>/.wcr_key`（权限 600），
  后续运行免重复授权。若微信重启导致密钥失效，桥接会自动重新提取。
- 需要 Node.js（解密桥的取数端用 Node 跑）。

**桥接组件**
- `scripts/decrypt_fetch.mjs`：Node 取数端。取密钥 → 打开微信账号 → 拉取 `filehelper`
  最近消息 → 输出纯 JSON 到 stdout（日志走 stderr，不污染 JSON）。
- `scripts/decrypt_wechat_db.py`：Python 落库端。调用上面的取数脚本，把消息写成扫描器
  期望的解密库 schema（`session.db` 的 `SessionTable` + `message_0.db` 的
  `Msg_<md5(username)>`），按 `local_id` 幂等合并（INSERT OR REPLACE）。

## 只读查看器（可选 · 进阶）

> 这是**可选附加功能**，不是主流程。主流程是上文「模式 C：走微信自动路由」——把链接转发到文件传输助手，一条命令自动识别并导入。查看器只在你想在网页里浏览整段微信聊天记录时才用。

本 skill 内置一个**微信聊天记录只读查看器**，复用 WxLens 的解密逻辑（WCDB 原生库 + 密钥提取），把微信加密数据库解密后以网页聊天界面展示。

**特性**
- 纯只读：只 SELECT，绝不写入 / 删除 / 发送任何微信数据。
- 自动发现微信账号目录（macOS 微信 4.x / Windows 微信 4.x）。
- 微信运行且已登录时，可一键“自动提取”数据库密钥；否则在页面粘贴 64 位 hex 密钥即可。
- 会话列表（全部 / 私聊 / 群聊）+ 消息气泡（自己靠右、对方靠左）+ 关键词搜索。

**启动（二选一）**
- 自动拉起：运行 `node scripts/launch-viewer.mjs`（服务已在 `127.0.0.1:8731` 则直接开浏览器；否则后台启动 `viewer-server.mjs` 并自动打开浏览器）。
- 手动：双击 `START-VIEWER.command`（macOS）/ `START-VIEWER.bat`（Windows）。

首次运行若缺 `koffi`，启动器会自动 `npm install koffi`（或手动 `cd scripts && npm install koffi`）。

**前提**
- 需安装 Node.js（https://nodejs.org）。
- macOS 解密需要 **macOS 15 (Sequoia) 及以上**；自动取密钥还需 `resources/key/macos/<arch>/xkey_helper` 助手（已从本机 `/Applications/WxLens.app` 补齐，缺失时改用页面粘贴密钥），且需关闭 SIP（恢复模式 → 终端 → `csrutil disable`）。
- Windows 解密需要微信 4.x 运行且已登录（自带 `wx_key.dll`），无需关闭 SIP。

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
- `scripts/decrypt_wechat_db.py`（macOS 一键解密桥 · Python 落库端）
- `scripts/decrypt_fetch.mjs`（macOS 一键解密桥 · Node 取数端）
- `scripts/import_latest_wechat_links.py`
- `scripts/import_xhs_note.py`
- `scripts/import_wechat_mp_article.py`
