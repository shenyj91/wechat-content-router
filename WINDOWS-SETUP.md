# WINDOWS-SETUP

## 适用对象

这份说明给：

- Windows 用户
- 想安装 `wechat-content-router-windows`
- 需要小红书图片 OCR 功能的人

---

## 一、先说明当前 Windows 版状态

Windows 版现在已经接入：

- `PaddleOCR`
- `PaddlePaddle CPU`

也就是说：

- 小红书导入：可用
- 公众号导入：可用
- 微信路由：可用
- 图片 OCR：已接入，但建议按下面步骤先做一次本机验证

---

## 二、基础环境

建议环境：

- Windows 10 / 11
- Python 3.10 或 3.11
- 已安装 Codex

先确认 Python：

```bash
python --version
```

建议看到：

```text
Python 3.10.x
```

---

## 三、安装 Windows 版 skill

你有两种跑法：

1. 装进 Codex / skill 目录
2. 不装进 Codex，直接从仓库目录运行

把仓库里的这个目录复制到本地：

```text
skills/wechat-content-router-windows
```

安装到：

```text
%USERPROFILE%\.codex\skills\wechat-content-router-windows
```

如果你在 PowerShell：

```powershell
New-Item -ItemType Directory -Force -Path $env:USERPROFILE\.codex\skills\wechat-content-router-windows
Copy-Item -Recurse -Force .\skills\wechat-content-router-windows\* $env:USERPROFILE\.codex\skills\wechat-content-router-windows\
```

### 如果你不是用 Codex 安装

直接进入仓库目录：

```powershell
cd .\skills\wechat-content-router-windows
```

然后用：

```powershell
python .\scripts\ocr_paddle.py D:\test\1.jpg
```

或：

```powershell
python .\scripts\import_xhs_note.py "小红书链接或整段分享文案"
```

不要写死成：

```text
%USERPROFILE%\.codex\skills\...
```

除非你真的就是装在那个目录里。

---

## 四、安装 Python 依赖

### 先装通用依赖

```bash
python -m pip install browser-cookie3 requests lxml zstandard
```

### 再装 PaddlePaddle CPU

```bash
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

### 再装 PaddleOCR

```bash
python -m pip install "paddleocr[all]"
```

### 如果要让公众号 / 小红书同时导出 PDF

进入 Windows 版 skill 目录后安装：

```bash
npm install
```

再执行：

```bash
npx playwright install chromium
```

### local mode 的规则

当用户选择 **保存到本地** 时，默认按：

- **PDF 作为主交付物**
- Markdown / 图片 / 元信息作为备份

当前已落地：

- 公众号：浏览器渲染 PDF
- 小红书：浏览器渲染 PDF
- 飞书：预留

如果你不需要 OCR，也可以先不装 PaddleOCR，只把配置里的：

```json
"runOcr": false
```

关掉。

---

## 五、初始化配置

### 方案 A：导入 Obsidian

```bash
python %USERPROFILE%\.codex\skills\wechat-content-router-windows\scripts\init_local_config.py --mode obsidian --vault-root "D:\ObsidianVault"
```

### 方案 B：直接导入本地目录

```bash
python %USERPROFILE%\.codex\skills\wechat-content-router-windows\scripts\init_local_config.py --mode local --local-root "D:\ImportedContent"
```

生成后配置文件在：

```text
%USERPROFILE%\.codex\skills\wechat-content-router-windows\scripts\config.json
```

---

## 六、验证 OCR 是否可用

找一张本地图片，比如：

```text
D:\test\1.jpg
```

运行：

```bash
python %USERPROFILE%\.codex\skills\wechat-content-router-windows\scripts\ocr_paddle.py D:\test\1.jpg
```

如果成功，应该输出类似：

```json
{
  "items": [
    {
      "path": "D:\\test\\1.jpg",
      "text": "识别出来的文字"
    }
  ]
}
```

---

## 七、验证小红书导入

```bash
python %USERPROFILE%\.codex\skills\wechat-content-router-windows\scripts\import_xhs_note.py "小红书链接或整段分享文案"
```

重点看这些字段：

- `note_path`
- `images_downloaded`
- `ocr_length`

如果 `ocr_length > 0`，说明 OCR 路径已经跑通。

## 七点五、验证本地 PDF

如果你启用：

```json
"save_pdf": true,
"prefer_pdf_preview": true
```

那么公众号导入后，返回结果里应该优先看到：

- `pdf_path`
- `preview_path`

---

## 八、常见问题

### 1）报错：`PaddleOCR 未安装`
说明你还没装：

```bash
python -m pip install "paddleocr[all]"
```

### 2）报错：`No module named paddleocr`
说明当前运行的 Python 和你安装依赖的 Python 不是同一个。

先查：

```bash
python -c "import sys; print(sys.executable)"
```

再确认依赖装到的是同一个 Python。

### 3）OCR 很慢
第一次运行通常会慢一些，因为会初始化模型。

### 4）暂时不想折腾 OCR
直接把配置里的：

```json
"runOcr": false
```

关掉，先用导入能力。

---

## 九、推荐验证顺序

建议按这个顺序测：

1. `init_local_config.py`
2. `ocr_paddle.py` 单图测试
3. `import_xhs_note.py` 测单条小红书
4. `import_wechat_mp_article.py` 测单条公众号
5. `run_wechat_router_pipeline.py` 测微信自动路由

---

## 十、目前建议

如果你是首次使用，建议：

- 先关掉 `runOcr`
- 先验证导入主链路
- 再单独打开 OCR 测试

这样定位问题最快。

如果你现在最在意“客户本地下载看起来像页面原样”，优先先测：

1. 小红书导入
2. PDF 是否成功生成
3. `preview_path` 是否指向 PDF
