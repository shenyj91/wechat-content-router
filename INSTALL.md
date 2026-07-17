# INSTALL

## 适用对象

这份安装说明给两类人：

1. 想把 skill 装进 Codex 使用的人
2. 想先把仓库 clone 到本地再手工安装的人

---

## 一、先准备环境

需要本机具备：

- macOS / Linux
- Python 3.10+
- 已安装 Codex

安装 Python 依赖：

```bash
python3 -m pip install browser-cookie3 requests lxml zstandard
```

如果你安装 **Windows 版** 并需要 OCR，还要额外安装：

```bash
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install "paddleocr[all]"
```

---

## 二、安装到 Codex

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

---

## 三、初始化配置

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

---

## 四、如果你要走微信自动路由

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

## 五、验证安装成功

你可以直接跑：

```bash
python3 ~/.codex/skills/wechat-content-router-macos/scripts/init_local_config.py --help
```

或者在 Codex 里说：

```text
用 $wechat-content-router-macos 把这条公众号链接导入本地。
```

如果能识别 skill，就说明安装成功。
