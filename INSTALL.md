# INSTALL

## 适用对象

这份安装说明给两类人：

1. 想把 skill 装进 Codex 使用的人
2. 想先把仓库 clone 到本地再手工安装的人

---

## 一、先准备环境

需要本机具备：

- macOS / Windows
- Python 3.10+
- 已安装 Codex（如果你要装进 Codex）

安装 Python 依赖：

```bash
python3 -m pip install browser-cookie3 requests lxml zstandard
```

如果你要启用“公众号浏览器渲染 PDF 导出”，还要安装 Node.js 依赖：

### macOS

```bash
cd skills/wechat-content-router-macos
npm install
```

### Windows

```bash
cd skills/wechat-content-router-windows
npm install
```

然后安装 Playwright 浏览器内核：

```bash
npx playwright install chromium
```

如果你安装 **Windows 版** 并需要 OCR，还要额外安装：

```bash
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install "paddleocr[all]"
```

---

## 二、安装方式

这个仓库支持两种使用方式：

1. **装进 Codex / skill 目录**
2. **不装进 Codex，直接当普通本地目录运行**

---

## 三、安装到 Codex

### 方法 A：安装 macOS 版

先 clone 仓库：

```bash
git clone https://github.com/YOUR_NAME/wechat-content-router.git
cd wechat-content-router
```

然后执行：

```bash
bash scripts/install-to-codex.sh
```

安装完成后，skill 会被复制到：

```text
~/.codex/skills/wechat-content-router-macos
```

---

### 方法 B：手工复制安装 macOS 版

```bash
mkdir -p ~/.codex/skills/wechat-content-router-macos
cp -R skills/wechat-content-router-macos/. ~/.codex/skills/wechat-content-router-macos/
```

---

### 方法 C：手工复制安装 Windows 版

如果你要准备 Windows 版目录，复制：

```bash
mkdir -p ~/.codex/skills/wechat-content-router-windows
cp -R skills/wechat-content-router-windows/. ~/.codex/skills/wechat-content-router-windows/
```

Windows 版当前 OCR 后端是：

- `PaddleOCR`

说明：

- 公众号在 `storage.mode=local` 时会强制走 **PDF 主产物**
- 飞书路由已经预留，但还没接入最终渲染链路
- 小红书本地 PDF 仍是后续增强项

---

## 四、作为普通本地目录运行

如果你不是用 Codex 安装，而是装进**其他智能体**，或者直接把仓库当本地工具目录跑，直接这样进入对应目录即可：

### macOS 版

```bash
cd skills/wechat-content-router-macos
python3 scripts/init_local_config.py --help
```

### Windows 版

```bash
cd skills/wechat-content-router-windows
python scripts/init_local_config.py --help
```

这时不要再假设路径一定是：

```text
~/.codex/skills/...
```

---

## 五、初始化配置

### 方案 1：导入 Obsidian

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/init_local_config.py \
  --mode obsidian \
  --vault-root "/Users/yourname/Documents/ObsidianVault"
```

### 方案 2：直接下载到本地文件夹

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/init_local_config.py \
  --mode local \
  --local-root "/Users/yourname/Documents/ImportedContent"
```

`--mode local` 生成的配置会默认带上：

- `routes.mp.save_pdf = true`
- `routes.mp.prefer_pdf_preview = true`
- `routes.mp.pdf_source = "browser_render"`
- `routes.feishu` 预留配置

---

## 六、如果你要走微信自动路由

还要补这些配置到：

```text
~/.codex/skills/wechat-content-router-macos/scripts/config.json
```

要补的字段：

- `wechat.enabled`
- `wechat.session_db`
- `wechat.message_dir`
- `wechat.chat_username`
- `wechat.message_table`
- `wechat.decrypt_workdir`
- `wechat.decrypt_python`
- `wechat.decrypt_script`

把：

```json
"wechat": {
  "enabled": true
}
```

打开即可。

---

## 七、验证安装成功

你可以直接跑：

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/init_local_config.py --help
```

或者在 Codex 里说：

```text
用 $wechat-content-router-macos 把这条公众号链接导入本地。
```

如果能识别 skill，就说明安装成功。

如果你是普通目录运行方式，也可以直接测试：

### macOS

```bash
cd skills/wechat-content-router-macos
python3 scripts/init_local_config.py --help
```

### Windows

```bash
cd skills/wechat-content-router-windows
python scripts/init_local_config.py --help
```
