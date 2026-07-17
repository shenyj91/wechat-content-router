# wechat-content-router

> 把**微信里转来的内容链接**，自动识别并落成你自己的资料。  
> 当前优先支持：**小红书**、**微信公众号**。  
> 可落到 **Obsidian**，也可直接落到**本地文件夹**。

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-wechat--content--router-blueviolet)](skills/wechat-content-router/SKILL.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Codex-black)](#快速开始)

---

## 这是什么

`wechat-content-router` 不是一个“只处理某个平台链接”的小工具，  
而是一个更适合真实使用场景的 **微信入口母 skill**：

- 你把链接转到微信
- 它自动识别链接类型
- 再分发到对应 importer
- 最后把内容落到你的知识库或本地目录

它解决的不是“打开链接”，而是：

- **把内容真正存下来**
- **把资料变成可搜索、可复用的资产**
- **减少手工复制、判断、整理的重复劳动**

---

## 适合谁

适合这些人：

- 想把小红书 / 公号内容系统化沉淀的人
- 做知识库、资料归档、选题库的人
- 想把微信 filehelper 变成“内容收集入口”的人
- 不想折腾 Obsidian，只想先下载到本地的人

---

## 现在能做什么

### 支持的输入

| 输入 | 路由 | 输出 |
|---|---|---|
| 小红书链接 / 分享文案 | `xhs` | Markdown + 图片 + 可选 OCR |
| 微信公众号文章链接 | `mp` | Markdown + 原文链接 + 公众号信息 |
| 微信 filehelper 最近消息 | 自动识别 | 自动路由到对应 importer |

### 支持的落地模式

| 模式 | 适合场景 |
|---|---|
| Obsidian | 做知识库、长期整理、标签检索 |
| Local | 不用 Obsidian，只想先把内容存本地 |

---

## 为什么不是“单一小红书 skill”

真实使用里，用户入口通常不是平台本身，而是：

1. 先把内容转到微信
2. 再从微信 filehelper 或某个聊天里处理
3. 这个链接可能是小红书，也可能是公众号

所以更合理的产品形态应该是：

- **统一配置**
- **统一微信入口**
- **多内容路由**
- **多落地方式**

这就是 `wechat-content-router` 的定位。

---

## 快速开始

### 1）安装依赖

```bash
python3 -m pip install browser-cookie3 requests lxml zstandard
```

### 2）安装到 Codex

#### 方法 A：一键安装

```bash
bash scripts/install-to-codex.sh
```

#### 方法 B：手工复制

```bash
mkdir -p ~/.codex/skills/wechat-content-router
cp -R skills/wechat-content-router/. ~/.codex/skills/wechat-content-router/
```

---

## 配置方式

### 方案 A：导入 Obsidian

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/init_local_config.py \
  --mode obsidian \
  --vault-root "/Users/yourname/Documents/ObsidianVault"
```

### 方案 B：直接下载到本地目录

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/init_local_config.py \
  --mode local \
  --local-root "/Users/yourname/Documents/ImportedContent"
```

生成后配置文件在：

```text
~/.codex/skills/wechat-content-router/scripts/config.json
```

---

## 使用方式

### 方式 1：直接处理单条内容

#### 小红书

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/import_xhs_note.py "小红书链接或整段分享文案"
```

#### 微信公众号

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/import_wechat_mp_article.py "公众号文章链接"
```

### 方式 2：从微信自动路由

补好 `config.json` 里的微信路径后运行：

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/run_wechat_router_pipeline.py
```

它会：

1. 读取微信最近消息
2. 抽取链接
3. 判断类型
4. 调用对应 importer
5. 落到 Obsidian / 本地目录
6. 记录状态，避免重复导入

---

## 在 Codex 里怎么说

```text
用 $wechat-content-router 把这条公众号链接导入 Obsidian。
```

```text
用 $wechat-content-router 把这条小红书分享文案导入本地文件夹。
```

```text
用 $wechat-content-router 跑一次最近微信 filehelper 的链接自动导入。
```

---

## 当前版本能力边界

当前版本已经支持：

- `xhs`：小红书导入
- `mp`：微信公众号导入
- `wechat router`：从指定微信会话自动抓最近链接
- `obsidian / local`：双落地模式

后续可继续扩展：

- Quark 路由
- 百度网盘路由
- 会话选择器
- 更友好的普通用户安装流程

---

## 仓库结构

```text
wechat-content-router-skill/
├── README.md
├── INSTALL.md
├── USAGE.md
├── LICENSE
├── .claude-plugin/
│   └── marketplace.json
├── scripts/
│   └── install-to-codex.sh
├── examples/
│   └── sample-router-output.json
└── skills/
    └── wechat-content-router/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/
        │   ├── config-template.json
        │   └── routes.md
        └── scripts/
            ├── init_local_config.py
            ├── import_xhs_note.py
            ├── import_wechat_mp_article.py
            ├── import_latest_wechat_links.py
            ├── run_wechat_router_pipeline.py
            ├── ocr.swift
            └── ocr_corrections.json
```

---

## 你还可以看

- [INSTALL.md](INSTALL.md)
- [USAGE.md](USAGE.md)
- [skills/wechat-content-router/SKILL.md](skills/wechat-content-router/SKILL.md)
- [examples/sample-router-output.json](examples/sample-router-output.json)

---

## License

[MIT](LICENSE)
