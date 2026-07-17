# wechat-content-router

> 一个 **WeChat-first** 的内容导入 skill。  
> 现在按平台拆成两个发布版本：**macOS 版** 和 **Windows 版**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Codex-black)](#安装哪个版本)

---

## 现在的发布方式

这个仓库现在不是单一 skill，而是**双版本发布**：

### 1）macOS 版
- skill 名：`wechat-content-router-macos`
- 适合：macOS 用户
- OCR：使用 **Swift + Vision**
- 特点：原生、本地、中文 OCR 体验更顺

### 2）Windows 版
- skill 名：`wechat-content-router-windows`
- 适合：Windows 用户
- OCR：使用 **PaddleOCR**
- 目标：替换 macOS 专属 OCR 方案

---

## 为什么拆成两个版本

因为当前 OCR 能力有平台差异：

- **macOS**：可以直接用 `Swift + Vision`
- **Windows**：不能跑 `AppKit / Vision / /usr/bin/swift`

所以继续用一个完全相同的 skill 名，会让普通用户误以为“所有系统都一样能跑”。

拆成两个版本以后更清楚：

- macOS 用户装 macOS 版
- Windows 用户装 Windows 版

---

## 它们共同解决什么问题

这两个版本都围绕同一个目标：

**把微信里转来的内容链接，落成你自己的资料。**

支持的主要内容：

- 小红书链接 / 分享文案
- 微信公众号文章链接

支持的落地方式：

- 导入 Obsidian
- 直接下载到本地文件夹

---

## 安装哪个版本

### 安装 macOS 版

```bash
mkdir -p ~/.codex/skills/wechat-content-router-macos
cp -R skills/wechat-content-router-macos/. ~/.codex/skills/wechat-content-router-macos/
```

### 安装 Windows 版

请安装：

- `skills/wechat-content-router-windows`

如果后续要给普通 Windows 用户分发，我们会继续补齐单独的 Windows 安装说明和 OCR 后端。

---

## 版本说明

### wechat-content-router-macos

适合：

- macOS 用户
- 需要图片 OCR
- 想直接用系统原生 OCR

当前特点：

- 微信入口路由
- 小红书导入
- 公众号导入
- Obsidian / Local 双落地
- macOS OCR 可用

### wechat-content-router-windows

适合：

- Windows 用户
- 需要 Windows OCR
- 想单独安装 Windows 版

当前特点：

- 微信入口路由结构已拆分
- Windows OCR 已切到 PaddleOCR

---

## 仓库结构

```text
wechat-content-router-skill/
├── README.md
├── INSTALL.md
├── USAGE.md
├── LAUNCH-COPY.md
├── LICENSE
├── .claude-plugin/
│   └── marketplace.json
├── scripts/
│   └── install-to-codex.sh
├── examples/
│   └── sample-router-output.json
└── skills/
    ├── wechat-content-router-macos/
    │   ├── SKILL.md
    │   ├── agents/openai.yaml
    │   ├── references/
    │   └── scripts/
    └── wechat-content-router-windows/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/
        └── scripts/
```

---

## 当前建议

### 如果你现在就是要真实使用
优先用：

- **macOS 版**

### 如果你现在是为了先把结构发布出去
可以保留：

- macOS 版可用
- Windows 版作为独立版本入口

这样仓库对外结构已经清楚，后面再继续补 Windows OCR。

---

## 相关文件

- [INSTALL.md](INSTALL.md)
- [USAGE.md](USAGE.md)
- [WINDOWS-SETUP.md](WINDOWS-SETUP.md)
- [LAUNCH-COPY.md](LAUNCH-COPY.md)
- [macOS skill](skills/wechat-content-router-macos/SKILL.md)
- [Windows skill](skills/wechat-content-router-windows/SKILL.md)

---

## License

[MIT](LICENSE)
