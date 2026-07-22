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
3. 应在聊天里逐项问客户（见「开工前必须向客户确认的三件事」），拿到明确答复后用 `init_local_config.py` 的命令行参数**非交互**写配置。**不要运行会卡在 `input()` 的 `bootstrap_config.py` / 交互式向导**——在聊天里客户无法回答子进程的 `input()`，助手一旦去跑它就会卡住、或偷用探测值静默写配置（这正是「没给我选择的权利」的根因）。OCR 默认开启不再询问
4. 说明真实配置向导会先让用户选“本地 / Obsidian”，默认 OCR 开启；Obsidian 路径会先**探测出候选**，但**必须让客户确认**后才写入（见下文「开工前必须向客户确认的三件事」）
5. 如果用户选择微信自动扫描，先让他选数据源：
   - 内置 WCDB 解密并导入（默认、推荐）：自动解密 `session.db`（会话列表）、`contact.db`（联系人），零原生依赖、稳定可用
   - Frida 内存提取（消息内容专用）：当 `message_0.db` 等消息库在磁盘上大量页解密失败（新微信版本常见）时，**唯一能拿到聊天里链接/内容的路径**——直接扫描 WeChat 进程内存中的明文 SQLite 页。需 WeChat 在运行、已装 `frida`。
6. 只有用户已经完成本地配置后，再进入日常使用

## 开工前必须向客户确认的三件事（强制）

> **任何**一次「从微信取内容 → 落到某处」的操作（首次配置、日常扫描、手动导入都一样），都必须先和客户对齐下面三点。**禁止**靠"自动探测"直接替客户定下来——探测只用来给出候选默认值，最终要客户明确说"可以 / 就是这个 / 换一个"。探测到的值不写进 `config.json` 之前，必须先问。
>
> **两条配置入口，别混用：**
> - **聊天 / 专家入口（WorkBuddy 里召唤本专家）**：助手在**聊天里逐项问**客户（用下面的探测命令给出候选），拿到明确答复后，用 `init_local_config.py` 的**命令行参数非交互写配置**（命令见第 3 点末尾）。**绝不要在聊天里运行 `bootstrap_config.py` / `interactive_config`**——它们依赖子进程的 `input()`，客户在聊天里答不了，助手跑去跑就会卡住或偷用探测值静默写配置（"没给我选择的权利"的根因）。
> - **终端入口（Windows 直接双击 `CONFIG-WIZARD.bat` / `START-HERE.bat`）**：走 CLI 交互向导 `interactive_config`，已**强制显式选择**（Obsidian 必须输入序号、多账号必须挑、本地目录不再有静默默认值）。这是给安装人员/客户在 Windows 终端里用的，不需要聊天。

> **权限澄清（避免误解）**：本技能自动扫描（纯 Python 解密 session.db / contact.db、读链接）**不需要 frida、不需要管理员权限**。只有「从微信进程内存抽密钥」需管理员，已有 `scripts/wechat_key.txt` 文件降级可避开。微信账号目录的自动定位（`list_all_accounts()` → `wechat_bridge.mjs` 的 `findAllAccountDirs()`）在**真实 Windows 上会自动找到、普通用户权限即可**；但若跑在 WorkBuddy 执行沙箱内，沙箱会禁掉注册表读取与全盘扫描，导致返回空——这是「沙箱在拦」，不是「本技能需要权限」。此时引导客户把 `xwechat_files\<账号>` 路径贴出来即可，并如实说明「在您自己电脑上直接跑会自动定位、不用管理员」。

1. **存到哪里（落盘位置）**
   - 先探测候选：`python -c "import init_local_config as c; print(c.detect_obsidian_vaults())"` 找 Obsidian vault；本地默认候选 `~/Documents/ImportedContent`。
   - 把候选读出来展示给客户，问：**"存到这里 OK 吗？还是要换路径？"**
   - 客户确认/给出的路径写入 `storage.mode`（`obsidian` / `local`）+ `vault_root` / `local_root`，并回显确认。

2. **确认用哪个微信（账号）**
   - 列出本机所有微信账号：`python -c "import wechat_win_decrypt as w; print(w.list_all_accounts())"`（返回每个 `xwechat_files/<账号>` 的 `account_dir` / `wxid` / `mtime`）。若返回空列表，说明当前运行环境（沙箱）禁了注册表读取与全盘扫描，按上方「权限澄清」引导客户把 `xwechat_files\<账号>` 路径贴出来，不要说成"需要权限"。
   - **多账号时，必须让客户从列表里挑一个**，绝不能默认绑"最近活跃"那个就开跑。
   - **单账号时也要展示出来问："就是这一个微信账号对吧？"** 让客户确认。
   - 选中的 `account_dir` 写入 `wechat.account_dir`，`wxid` 写入 `wechat.selected_account_wxid` / `selected_account_label`。

3. **确认数据源是客户的「文件传输助手」**
   - 默认从**文件传输助手**（会话 id = `filehelper`）读取链接——因为客户通常是把链接转发到文件传输助手再统一路由。
   - 必须问客户：**"从你的【文件传输助手】读链接，对吗？还是想固定某个具体聊天？"**
   - 若客户说"指定某个聊天"，**必须追问"是哪个会话？（会话名或 id）"并拿到明确会话名**——不能只问"要不要指定"就替客户定一个。确认后写入 `wechat.chat_username`（默认 `filehelper`）；让客户确认会话名拼写无误。

**收尾（拿到三问答复后，非交互写配置）**

助手用一行命令写入，**不要跑 `bootstrap_config.py`**（会卡在 `input()`）：

```bash
# Obsidian 场景
python scripts/init_local_config.py --mode obsidian --vault-root "<第1问选中的仓库路径>" \
  --wechat-enabled --chat-username "<filehelper 或 客户给的会话名>" \
  --account-dir "<第2问选中的 account_dir>" --default-action wechat_monitor --monitor-mode manual

# 本地文件夹场景：把上面前两个参数换成这一行
#   --mode local --local-root "<第1问选中的本地目录>"
```

写完后读取 `scripts/config.json`，把摘要（存哪 / 哪个微信 / 文件传输助手或指定会话）回显给客户确认，再进入实际扫描或导入。

确认完三点，把摘要（存哪 / 哪个微信 / 文件传输助手或指定会话）回显给客户，再进入实际扫描或导入。这三问同样写进了 `scripts/init_local_config.py` 的 CLI 向导（`bootstrap_config.py` / `START-HERE.bat` / `CONFIG-WIZARD.bat`），客户在 Windows 终端走 CLI 入口也会被强制逐项选择。

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

说明一下（安装后如何自动拉起配置）：

> **WorkBuddy 当前没有「技能安装后立刻自动执行脚本」的钩子**——装完技能不会自己弹配置，必须有人进到这条入口。要「装完即拉起配置、客户无需先打字」，二选一：
>
> - **方式一（推荐，最省事 · 安装后零手动）**：装完技能后，直接**双击技能目录里的 `CONFIG-WIZARD.bat`**（Windows）。它会自动装依赖并立刻启动配置向导，依次问「存哪里 / 哪个微信 / 文件传输助手」。这就是给安装人员/客户用的「装完即配」一键入口。
> - **方式二（在 WorkBuddy 里）**：召唤「微信内容路由（Windows）」专家。本技能的 `agents/openai.yaml` 已把 `default_prompt` 设为「**被召唤即无条件开始配置**」——专家一激活就会主动发起三问，**不需要客户先打任何字**，点一下发送即可开始；若已配置则直接进入日常使用。
>
> 另外，无论走哪条入口，`scripts/use_router.py` 与 `START-HERE.bat` 都会在**检测到没有 `config.json` 时自动进入配置向导**（`ensure_config()` 兜底），所以第一次进菜单也一定会先配。

- Windows 用户可以直接打开 `START-HERE.bat`

首次配置时会依次确定：

- 保存到本地还是 Obsidian
- 如果是 Obsidian，优先自动识别 vault，再由目录选择器兜底
- 如果是本地，保存目录是什么
- 平时更想手动贴链接，还是自动扫描微信
- 如果开微信扫描，要扫哪个会话、按什么频率跑
- 微信账号先用 `wechat_win_decrypt.list_all_accounts()` 列出本机所有候选（可能不止一个）；**多账号必须让客户选，单账号也要展示出来让客户确认**，确认结果写入 `wechat.account_dir` / `selected_account_wxid`（见「开工前必须向客户确认的三件事」）

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
- 多账号机器：默认进“最近登录（mtime 最新）”的账号；为免进错号，**多账号时应先问客户确认哪个微信**，再用环境变量 `VIEWER_WXID=<微信号>` 或 `config.json` 里的 `wechat.selected_account_wxid` 精确绑定到那个号。

**启动（二选一）**
- 自动拉起：运行 `node scripts/launch-viewer.mjs`（服务已在 `127.0.0.1:8731` 则直接开浏览器；否则后台启动 `viewer-server.mjs` 并自动打开浏览器）。
- 手动：双击 `START-VIEWER.bat`（Windows）/ `START-VIEWER.command`（macOS）。

首次运行请先装依赖（**两条都要**）：
- Python 依赖：`cd scripts && pip install -r requirements.txt`（需要 `cryptography` 与 `zstandard`）。
- Node 依赖（**必装**，自动提取密钥用）：`cd scripts && npm install`（安装 `koffi`，`key-extractor.js` 通过它加载 `wx_key.dll`）。若没装 koffi，自动提取会直接报错“缺少依赖”，此时应回退去装依赖，而**不是**让客户手动粘贴密钥（普通用户根本没有那段 64 位 hex）。

**前提**
- 需安装 Node.js（https://nodejs.org）与 Python 3（含 `cryptography`、`zstandard`；若要用内存提取消息内容，还需 `frida>=16.0`，见 `requirements.txt`）。
- 解密与查询已完全脱离 WxLens 原生库，不再因 DLL（`wcdb_api.dll`/`WCDB.dll`）崩溃而失败；Windows 端自动提取密钥**无需关闭 SIP**（通过独立的 `wx_key.dll` 注入，它不触发那个反盗用崩溃）。若自动提取失败，请按页面提示排查（微信是否在运行并登录 / 是否执行过 `npm install` / macOS 是否关 SIP），**不要**让客户去手动粘贴 64 位 hex 密钥——普通用户没有那段密钥，那只是开发者调试入口。

## 消息内容提取（Frida 内存路径）

> 这是**消息内容（聊天里的链接/正文）的专用提取路径**。纯 Python 磁盘解密能稳定处理 `session.db`（会话列表）、`contact.db`（联系人），但**无法处理 `message_0.db` 等消息库**：新版本微信在磁盘上对消息库做了非标准/部分加密，实测从第 ~105 页起约 98.6% 的页 HMAC 校验失败，即使密钥正确也无法还原成可打开的库。此时**唯一能拿到消息内容的路径是 Frida 内存提取**——微信在内存里保留的是解密后的明文 SQLite 页，直接扫这些页即可导出。

### 何时用
- 自动扫描跑完却 `no_new_links`（读不到聊天里的链接）
- 想从聊天记录里导出小红书 / 公众号 / 飞书 / 金山文档等链接
- 想直接导出某段会话的明文 SQLite 库

### 前提
- Windows，且 **WeChat（`Weixin.exe`）正在运行并登录**
- 已装 `frida`：`cd scripts && pip install -r requirements.txt`（requirements.txt 已含 `frida>=16.0`）
- 需要足够权限让 frida 注入目标进程（通常管理员即可）

### 用法
```bash
# 自动定位 Weixin.exe PID，扫描内存中的数据库 + 链接 + 关键词（默认 120s）
python scripts/frida_route/run_frida_scan.py --seconds 120

# 只列内存里扫到的数据库头
python scripts/frida_route/wcr_mem_scan.py

# 把内存里的库完整 dump 成可打开的 .db（二选一：base64 分块 / 二进制直传）
python scripts/frida_route/wcr_mem_extract4.py
python scripts/frida_route/wcr_mem_extract5.py

# 一次性全扫（库 + 链接 + 关键词）到 output/
python scripts/frida_route/wcr_mem_full_scan.py

# 闭环第二步：把扫到的链接按分类导入 Obsidian / 本地目录
python scripts/frida_route/import_frida_links.py
```

输出在 `scripts/frida_route/output/`：`databases.json`（含每个内存库真实的 `page_size` / `reserved`，磁盘上读不到）、`urls.txt`、`categorized_urls.json`（按 xiaohongshu / mp.weixin / feishu / kdocs / other 分类）、`keyword_hits.json`、`memdb/*.db`。

`import_frida_links.py` 读取 `categorized_urls.json`，按分类路由导入（落点由 config 的 Obsidian vault / 本地目录决定）：`xiaohongshu`→小红书 importer、`mp.weixin`→公众号 importer、`feishu`→飞书 importer；`kdocs`/其它类本 skill 暂无对应 importer 会跳过。用 `output/imported_frida_links.json` 记录已导入 URL 去重，重复运行只补新链接。

### 与磁盘解密的关系
- `session.db` / `contact.db`：继续走纯 Python 磁盘解密（`wcdb_decrypt.py`），稳定可用。
- `message_0.db` 等消息库：磁盘解密大量页失败时，**改用上面 Frida 路径**；导出的明文 `.db` 可直接用 `sqlite3` 打开查询。
- 本 `frida_route/` 目录已**提交进 git**，重装 skill 不会再丢失（以前需要手动备份到 `C:\Users\Administrator\.workbuddy\backups\`）。

### 密钥降级
实时提取密钥有 ~30s 超时风险，因此优先用 `key_file` 降级：`scripts/wechat_key.txt`（由提取工具生成，形如 `x'f82d0da4…e495'`）。Frida 路径本身不依赖密钥——它读的是内存明文，所以即使密钥提取失败，内存扫描依然能导出消息内容。

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
