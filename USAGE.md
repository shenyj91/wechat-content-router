# USAGE

## 一、你到底该用哪种模式

### 模式 A：启动器模式（推荐）
适合：

- 你希望安装后直接被一步步提问
- 你不想自己手改 `config.json`
- 你想在“手动导入 / 微信扫描 / 重新配置”之间切换

启动方式：

```bash
python3 scripts/use_router.py
```

Windows 直接打开：

```text
START-HERE.bat
```

### 模式 B：单条链接导入
适合：

- 你手里已经有一条小红书链接
- 你手里已经有一条公众号链接
- 你不想接微信自动扫描

### 模式 C：微信自动路由
适合：

- 你平时先把链接转到微信 filehelper
- 你不想自己判断链接类型
- 你想自动把最近消息落库

### 模式 D：本地直存
适合：

- 你不用 Obsidian
- 你只想把内容先下载到普通文件夹
- 你要把这套东西交给普通客户使用

### 模式 E：Windows OCR
适合：

- 你是 Windows 用户
- 你需要图片文字识别
- 你已经安装 PaddleOCR 依赖

---

## 二、先用启动器跑一遍（最推荐）

第一次使用直接运行：

```bash
python3 scripts/use_router.py
```

它会先问你：

1. 保存到本地还是 Obsidian
2. 对应路径是什么
3. OCR 默认开启，不再单独询问
4. 微信自动来源是内置 WCDB 解密还是直接扫描微信进程
5. 手动贴链接还是自动扫描微信
6. 如果扫微信，是固定文件传输助手，还是固定某个聊天对象
7. 再决定是跑一次、实时轮询还是固定间隔扫描

配置好后，会进入一个启动器菜单：

```text
1. 手动粘贴一条链接/分享文案进行导入
2. 运行一次微信自动扫描
3. 按当前配置持续扫描微信
4. 重新配置
0. 退出
```

---

## 三、单条模式怎么用

下面分两种写法：

- **Codex skill 安装方式**
- **普通本地目录运行方式**

### 小红书

#### Codex 安装方式（macOS）

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/import_xhs_note.py "小红书链接或整段分享文案"
```

#### 普通本地目录方式

```bash
cd skills/wechat-content-router-macos
python3 scripts/import_xhs_note.py "小红书链接或整段分享文案"
```

### 公众号

#### Codex 安装方式（macOS）

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/import_wechat_mp_article.py "公众号文章链接"
```

#### 普通本地目录方式

```bash
cd skills/wechat-content-router-macos
python3 scripts/import_wechat_mp_article.py "公众号文章链接"
```

如果你在配置里把：

```json
"save_pdf": true
```

打开，公众号导入时会同时保存一个 **浏览器渲染后的 PDF**。

如果同时配置：

```json
"prefer_pdf_preview": true
```

那么本地模式下会把 PDF 当成主预览结果。

补一句：

- 当 `storage.mode=local` 时，公众号路由现在会默认强制按这套规则输出

### 飞书

#### Codex 安装方式（macOS）

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/import_feishu_page.py "飞书页面链接"
```

#### 普通本地目录方式

```bash
cd skills/wechat-content-router-macos
python3 scripts/import_feishu_page.py "飞书页面链接"
```

如果走本地模式，飞书导入也会优先输出浏览器渲染后的 PDF。

---

## 四、微信自动模式怎么用

#### Codex 安装方式（macOS）

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/run_wechat_router_pipeline.py
```

#### 普通本地目录方式

```bash
cd skills/wechat-content-router-macos
python3 scripts/run_wechat_router_pipeline.py
```

内部流程：

1. 读取微信最近消息
2. 抽取链接
3. 判断类型
4. 调对应 importer
5. 写入 Obsidian 或本地目录
6. 记录已处理状态

---

## 五、最终会产出什么

### 小红书路由 `xhs`

输出通常包括：

- Markdown 笔记
- PDF（当开启 `save_pdf` 且走本地模式时）
- 图片文件
- OCR 文本
- 原始来源链接

### 公众号路由 `mp`

输出通常包括：

- Markdown 笔记
- PDF（当开启 `save_pdf` 且走本地模式时）
- 标题
- 公众号名
- 原始文章链接
- 原排版正文 HTML

### 本地模式统一规则

当用户选择 **保存到本地** 时，母规则是：

- 优先给 PDF
- `preview_path` 默认优先指向 PDF
- Markdown / 图片 / 元信息作为备份保留

当前已经落地：

- 公众号：是
- 小红书：是
- 飞书：是

所以现在最稳的理解是：

- **本地模式下的 PDF-first，当前已经真正落地在公众号、小红书、飞书路由**

---

## 六、在 Codex 里怎么说

### 例子 1

```text
用 $wechat-content-router-macos 把这条小红书分享文案导入我的本地文件夹。
```

### 例子 2

```text
用 $wechat-content-router-macos 把这条公众号文章导入 Obsidian。
```

### 例子 3

```text
用 $wechat-content-router-macos 跑一次最近微信 filehelper 的链接自动导入。
```
