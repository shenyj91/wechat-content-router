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

如果要启用 Windows 版内置 WCDB 解密，再装：

```bash
python -m pip install pycryptodome
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

- 公众号、小红书、飞书在 `storage.mode=local` 时都会强制走 **PDF 主产物**

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

### 最推荐：直接跑首次配置向导

```bash
python3 skills/wechat-content-router-macos/scripts/init_local_config.py
```

或 Windows：

```bash
python skills/wechat-content-router-windows/scripts/init_local_config.py
```

它会直接问你：

- 保存到本地还是 Obsidian
- 路径是什么
- OCR 默认开启，不再单独询问
- 手动贴链接还是自动扫微信
- 如果自动扫微信：固定文件传输助手，还是固定某个聊天对象
- 要不要间隔扫描

### 仍然支持命令行方式

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

- `routes.xhs.save_pdf = true`
- `routes.xhs.prefer_pdf_preview = true`
- `routes.xhs.pdf_source = "browser_render"`
- `routes.mp.save_pdf = true`
- `routes.mp.prefer_pdf_preview = true`
- `routes.mp.pdf_source = "browser_render"`
- `routes.feishu.enabled = true`
- `routes.feishu.save_pdf = true`
- `routes.feishu.prefer_pdf_preview = true`
- `routes.feishu.pdf_source = "browser_render"`

---

## 六、如果你要走微信自动路由

启动器会自动完成账号识别和 WCDB 解密；你只需要在首次配置时选好：

- 保存到哪里
- 绑定哪个微信账号
- 监控哪个会话
- 轮询方式

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
python3 ~/.codex/skills/wechat-content-router-macos/scripts/use_router.py
```

Windows 版如果是本地目录安装，直接打开启动器：

```text
START-HERE.bat
```

macOS 可以直接打开：

```text
START-HERE.command
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
python3 scripts/use_router.py
```

### Windows

```bash
cd skills/wechat-content-router-windows
python scripts/use_router.py
```

Windows 版最省事的入口就是：

```text
START-HERE.bat
```
