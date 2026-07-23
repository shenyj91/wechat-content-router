---
name: wechat-content-router-windows
description: >
  Windows 版微信内容路由。把微信会话里转来的小红书/公众号/飞书链接自动识别并导入 Obsidian 或本地文件夹。主路径用 Frida 内存提取（无需数据库密钥），Windows OCR 用 PaddleOCR。不要用于批量扫描整�微信或社交互动。
---

# wechat-content-router-windows

Windows 微信内容路由——把微信指定会话里的小红书分享、公众号文章、飞书文档链接自动识别、分类，然后落到 Obsidian vault 或本地文件夹。

## 安装

将此 skill 放到 Codex 的 skills 目录：

```bash
# 方式一：直接复制
cp -r skills/wechat-content-router-windows ~/.codex/skills/

# 方式二：符号链接
ln -s "$(pwd)/skills/wechat-content-router-windows" ~/.codex/skills/
```

安装 Python 依赖：

```bash
cd ~/.codex/skills/wechat-content-router-windows/scripts
pip install -r requirements.txt
```

Windows 上也可以直接双击 `START-HERE.bat` 或 `CONFIG-WIZARD.bat` 自动装依赖并启动配置向导。

## 首次配置

如果还没有 `scripts/config.json`，先引导用户完成配置。**不要运行交互式向导**（依赖子进程 `input()`，Codex 终端回答不了）——用 `init_local_config.py` 命令行参数一次性写入。

配置需要用户确认三件事：

### 1. 存到哪里

先探测 Obsidian vault：
```bash
python -c "import init_local_config as c; print(c.detect_obsidian_vaults())"
```

如果没找到 vault 或用户想存本地，默认候选 `~/Documents/ImportedContent`。让用户选一个，确认后写入 `storage.mode`（`obsidian` / `local`）和对应路径。

### 2. 用哪个微信账号

列出本机微信账号：
```bash
python -c "import wechat_win_decrypt as w; print(w.list_all_accounts())"
```

**Frida 内存提取会自动注入 Weixin.exe 进程，不需要 `account_dir`**——只需记下用户选中的 wxid。单账号也要展示出来让用户确认，多账号必须挑一个。记录选中的 wxid（写 `wechat.selected_account_wxid`）。

若 `list_all_accounts()` 返回空（当前环境禁了注册表扫描），直接问用户当前登录的微信昵称或 wxid。

### 3. 文件传输助手还是指定聊天

默认从**文件传输助手**（会话 ID = `filehelper`）读链接。问用户是否改到其他具体聊天。若改，必须拿到明确的会话名或 ID（如群聊 wxid）。

### 收尾：非交互写配置

三问确认后用一行命令写配置：

```bash
# Obsidian 场景
python scripts/init_local_config.py --mode obsidian --vault-root "<仓库路径>" \
  --wechat-enabled --chat-username "<filehelper 或 会话名>" \
  --default-action wechat_monitor --monitor-mode manual

# 本地文件夹场景
# python scripts/init_local_config.py --mode local --local-root "<本地目录>" \
#   --wechat-enabled --chat-username "<filehelper 或 会话名>" \
#   --default-action wechat_monitor --monitor-mode manual
```

写完后读取 `scripts/config.json` 回显配置摘要给用户确认。OCR 默认开启。

> **权限说明**：主路径用 **Frida 内存提取**（扫微信进程内存明文页），需要 `frida` 和管理员权限以注入 `Weixin.exe`，但**不需要数据库密钥**。Frida 会自动注入当前运行的微信进程，不需要 `account_dir`。若 Frida attach 失败，在 Windows 终端以管理员身份跑 `python scripts/use_router.py`。

## 工作流

### 模式 A：菜单式使用（推荐）

```bash
python scripts/use_router.py
```

菜单选项：
1. 手动粘贴一条链接/分享文案导入
2. 跑一次微信自动扫描（Frida 内存提取）
3. 按当前配置持续扫描微信
4. 重新配置

### 模式 B：直接导入单条

```bash
# 小红书
python scripts/import_xhs_note.py "<小红书链接或整段分享文案>"

# 公众号
python scripts/import_wechat_mp_article.py "<公众号文章链接>"
```

### 模式 C：命令行扫描+导入

先确保已配置，然后一步完成 Frida 扫描 + 分类导入：

```bash
python scripts/frida_route/run_frida_scan.py --seconds 120
python scripts/frida_route/import_frida_links.py
```

也可用 `use_router.py` 菜单 2，菜单内部自动走 Frida 链路。

## 当前内置路由

| 路由 | 处理对象 |
|------|---------|
| `xhs` | 小红书链接 / 分享文案 |
| `mp` | 微信公众号文章链接 |
| `feishu` | 飞书文档 / wiki 链接 |

`xhs` / `mp` / `feishu` 路由支持可选 PDF 输出。`storage.mode=local` 时默认以 PDF 为主产物。

## 消息内容提取（Frida 内存路径）

> 这是**消息内容专用的提取路径**。微信 4.x 在磁盘上对消息库做了非标准加密，磁盘解密大量页失败。Frida 读取内存中微信保留的解密后明文 SQLite 页，不依赖数据库密钥。

### 前提
- Windows，**WeChat（`Weixin.exe`）正在运行并登录**
- 已装 `frida`：`cd scripts && pip install -r requirements.txt`
- 管理员权限（注入目标进程）

### 用法
```bash
# 扫描内存中的数据库 + 链接 + 关键词（默认 120s）
python scripts/frida_route/run_frida_scan.py --seconds 120

# 只列内存里的数据库头
python scripts/frida_route/wcr_mem_scan.py

# dump 内存库为可打开的 .db
python scripts/frida_route/wcr_mem_extract4.py  # base64 分块
python scripts/frida_route/wcr_mem_extract5.py  # 二进制直传

# 全扫（库 + 链接 + 关键词）
python scripts/frida_route/wcr_mem_full_scan.py

# 第二步：分类导入
python scripts/frida_route/import_frida_links.py
```

### 按会话过滤

默认只保留 config 中 `wechat.chat_username`（默认 `filehelper`）的会话链接。在内存里找到消息库、逐页解析记录、比对 `talker` 列，再用全局 URL 做交集——只有该会话的链接才导入。

```bash
# 手动指定会话
python scripts/frida_route/run_frida_scan.py --chat-username filehelper
```

过滤结果在 `output/filter_info.json`（`applied` / `kept` / `total`）。

**已知版本适配**：微信 4.x 的 `talker` 存储方式随版本变化——有的是字符串 `filehelper`，有的是整数 `TalkerId`。

- `filter_info.applied=false` → talker 是整数形式、机制无法识别，降级为全部链接
- `filter_info.applied=true` 且 `kept=0` → 机制可用但指定会话此刻未驻留内存，**不回退其他会话**，提示先打开会话再扫

**多账号同进程**：`talker == "filehelper"` 在三账号同进程时同名，会抓全账号 filehelper 链接（通常无害）。想限定单账号需用 `wxid_xxx` 作为 `chat_username`。

输出在 `scripts/frida_route/output/`：
- `databases.json`：内存库信息
- `urls.txt`：提取到的 URL
- `categorized_urls.json`：按 xiaohongshu / mp.weixin / feishu / kdocs / other 分类
- `keyword_hits.json`：关键词命中
- `memdb/*.db`：dump 的数据库

`import_frida_links.py` 读 `categorized_urls.json` 分类导入，用 `output/imported_frida_links.json` 去重。

### 平台导入依赖
- **飞书**：需 Playwright Chromium → `npx playwright install chromium`
- **小红书长链**：需本机 Chrome 登录过小红书（`browser_cookie3` 读 cookie）；短链 `xhslink.com` 无需登录态
- **金山文档**：暂无对应 importer，自动跳过

Frida 内存提取**不依赖数据库密钥**，也无需 `scripts/wechat_key.txt`。

## 只读查看器（可选）

内置微信聊天记录网页查看器。纯 Python 解密（`wcdb_decrypt.py` + `viewer_query.py`），零原生依赖。纯只读，只 SELECT。

**启动**：
- `node scripts/launch-viewer.mjs`（自动开浏览器）
- 或双击 `START-VIEWER.bat`

**前提**：Python 依赖（`cryptography`、`zstandard`）+ Node 依赖（`koffi`，用于 `wx_key.dll` 密钥提取）。

## 输出要求

回复时优先输出：
- 路由类型
- 标题
- 生成文件路径
- 图片数量（xhs）
- OCR 长度（xhs）
- 公众号名称（mp）

## 不要用于

- 发帖、点赞、评论、私信
- 平台级批量爬取
- 未经许可的大范围微信聊天扫描

## 资源

- [references/config-template.json](references/config-template.json)
- [references/routes.md](references/routes.md)
- `scripts/init_local_config.py`
- `scripts/use_router.py`
- `scripts/frida_route/run_frida_scan.py`
- `scripts/frida_route/import_frida_links.py`
- `scripts/import_xhs_note.py`
- `scripts/import_wechat_mp_article.py`
