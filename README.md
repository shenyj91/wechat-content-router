# wechat-content-router

> 把**微信 filehelper / 微信消息里转来的内容链接**，按类型路由进你的 Obsidian。

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-wechat--content--router-blueviolet)](skills/wechat-content-router/SKILL.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

这个公共版不是只做“小红书导入”，而是做**微信入口路由**：

- 小红书链接 → 落成 Obsidian Markdown
- 微信公众号文章 → 落成 Obsidian Markdown
- 也可以不进 Obsidian，直接下载到本地普通文件夹
- 以后还能继续挂别的路由（夸克 / 百度网盘等）

---

## 为什么要做成母 skill

真正给别人用时，入口往往不是“我手里有一个小红书 URL”，而是：

- 我把链接转发到微信
- 我从 filehelper / 某个聊天里再处理
- 这个链接可能是小红书，也可能是公众号

所以公共版应该做成：

- **一个统一配置文件**
- **一个统一微信入口**
- **多个内容路由**

现在这版内置两条最核心路由：

1. `xhs`：小红书图文/分享文案导入
2. `mp`：微信公众号文章导入

---

## 它能做什么

| 输入 | 路由 | 输出 |
|---|---|---|
| 小红书链接 / 分享文案 | `xhs` | 本地 Markdown + 图片 + 可选 OCR |
| 微信公众号文章链接 | `mp` | 本地 Markdown，尽量保留原排版 HTML |
| 微信 filehelper 最近消息 | 自动识别 | 自动分发到对应 importer |

---

## 快速开始

### 1）安装依赖

```bash
python3 -m pip install browser-cookie3 requests lxml zstandard
```

### 2）初始化配置

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/init_local_config.py \
  --vault-root "/Users/yourname/Documents/ObsidianVault"
```

会生成：

```text
~/.codex/skills/wechat-content-router/scripts/config.json
```

如果你不想接 Obsidian，只想直接落到本地目录：

```bash
python3 ~/.codex/skills/wechat-content-router/scripts/init_local_config.py \
  --mode local \
  --local-root "/Users/yourname/Documents/ImportedContent"
```

### 3）如果你要走微信自动链路，再把这些路径补进去

- `session.db`
- 解密后的 `message_*.db` 目录
- 可选的微信解密脚本路径

### 4）对 Agent 说

```text
用 $wechat-content-router 把最近微信 filehelper 里的链接导入 Obsidian。
```

或者：

```text
用 $wechat-content-router 把这条公众号链接导入 Obsidian。
```

---

## 目录结构

```text
wechat-content-router-skill/
├── README.md
├── LICENSE
├── examples/
│   └── sample-router-output.json
├── .claude-plugin/
│   └── marketplace.json
└── skills/
    └── wechat-content-router/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/
        │   ├── config-template.json
        │   └── routes.md
        └── scripts/
            ├── init_local_config.py
            ├── run_wechat_router_pipeline.py
            ├── import_latest_wechat_links.py
            ├── import_xhs_note.py
            ├── import_wechat_mp_article.py
            ├── ocr.swift
            └── ocr_corrections.json
```

---

## 当前状态

这版已经把“微信入口 + 小红书 + 公众号”这件事收成一个母 skill 结构。

- `xhs`：可直接用
- `mp`：可直接用
- `wechat router`：可直接扫最近微信消息并自动识别路由
- `quark / baidu`：后续可继续挂接成扩展路由

---

## License

[MIT](LICENSE)
