#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_frida_links.py — 把 Frida 内存扫描导出的链接导入 Obsidian / 本地目录。

配合 run_frida_scan.py 使用，是「Frida 扫描 → 导入 Obsidian」闭环的第二步：
  第一步：python scripts/frida_route/run_frida_scan.py --seconds 180
          → 产出 scripts/frida_route/output/categorized_urls.json
  第二步：python scripts/frida_route/import_frida_links.py
          → 按分类把链接路由到对应 importer，导入 Obsidian / 本地目录

为什么需要它：原本的 import_latest_wechat_links.py 从「磁盘解密的消息库」读链接，
而 message_0.db 在磁盘上大量页解密失败（纯 Python 解密拿不到内容）→ 永远 no_new_links。
本脚本改从 Frida 内存扫描导出的 categorized_urls.json 读链接，绕开磁盘解密，
从而拿到聊天里真正转发的链接并落库。

分类路由：
  xiaohongshu    → import_xhs_note.py    : import_note(raw_text, ...)
  mp.weixin      → import_wechat_mp_article.py : import_article(url, ...)
  feishu         → import_feishu_page.py : import_page(url, ...)
  kdocs / 其它   → 本 skill 暂无对应 importer，跳过并提示（不报错）

去重：用 output/imported_frida_links.json 记录已导入 URL，重复运行只补新链接。

用法：
  python scripts/frida_route/import_frida_links.py
  python scripts/frida_route/import_frida_links.py --input output/categorized_urls.json
  python scripts/frida_route/import_frida_links.py --config ../config.json
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # scripts/frida_route/
SCRIPTS = HERE.parent                              # scripts/
DEFAULT_CONFIG = SCRIPTS / "config.json"
DEFAULT_CATEGORIZED = HERE / "output" / "categorized_urls.json"
STATE_PATH = HERE / "output" / "imported_frida_links.json"

# 分类 -> (importer 脚本文件名, 调用函数, 入参关键字)
ROUTES = {
    "xiaohongshu": ("import_xhs_note.py", "import_note"),
    "mp.weixin": ("import_wechat_mp_article.py", "import_article"),
    "feishu": ("import_feishu_page.py", "import_page"),
}
# 本 skill 暂无对应 importer 的分类（仅提示，不报错）
SKIP_CATEGORIES = ("kdocs", "other_interesting")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] 读取 {path} 失败: {e}")
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path: Path):
    if not config_path.exists():
        raise FileNotFoundError(f"找不到 config.json: {config_path}\n请先运行 init_local_config.py 生成配置。")
    config = load_json(config_path, {})
    config["_config_path"] = str(config_path.resolve())
    return config


def load_importer(module_name: str, script_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description="把 Frida 扫描导出的链接导入 Obsidian/本地")
    ap.add_argument("--input", default=str(DEFAULT_CATEGORIZED),
                    help="categorized_urls.json 路径（默认 output/categorized_urls.json）")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="config.json 路径")
    args = ap.parse_args()

    categorized = load_json(Path(args.input), {})
    if not categorized or not any(categorized.get(c) for c in ROUTES):
        print(f"[*] 没有可导入的链接。请先运行：")
        print(f"    python scripts/frida_route/run_frida_scan.py --seconds 180")
        print(f"    它会产出 {DEFAULT_CATEGORIZED}")
        return 0

    config = load_config(Path(args.config))
    # 报告扫描阶段的 talker 过滤结果（filehelper 等）
    fi = load_json(HERE / "output" / "filter_info.json", {})
    if fi:
        if fi.get("applied"):
            print(f"[*] 扫描已按会话 {fi.get('chat_username')} 过滤：保留 {fi.get('kept')}/{fi.get('total')} 条链接")
        else:
            print(f"[!] 扫描未匹配到会话 {fi.get('chat_username')} 的链接，已回退为全部 {fi.get('total')} 条（如需严格过滤请确认微信 4.1.11 消息库 talker 存储方式）")
    state = load_json(STATE_PATH, {})
    done = set(state.get("imported_urls", []))

    results = []
    for cat, (fname, fn) in ROUTES.items():
        urls = categorized.get(cat) or []
        if not urls:
            continue
        try:
            mod = load_importer(cat, SCRIPTS / fname)
        except Exception as e:
            print(f"[ERR]  无法加载 importer {fname}: {e}")
            for u in urls:
                results.append({"category": cat, "url": u, "status": "error",
                                "error": f"importer load failed: {e}"})
            continue
        for u in urls:
            if u in done:
                continue
            try:
                if cat == "xiaohongshu":
                    r = mod.import_note(u, config=config, overwrite=True)
                else:
                    r = getattr(mod, fn)(u, config=config, overwrite=True)
                done.add(u)
                results.append({"category": cat, "url": u, "status": "ok", "result": r})
                print(f"[OK]   {cat}: {u[:120]}")
            except Exception as e:
                results.append({"category": cat, "url": u, "status": "error", "error": str(e)})
                print(f"[ERR]  {cat}: {u[:120]} -> {e}")

    skipped = 0
    for cat in SKIP_CATEGORIES:
        urls = categorized.get(cat) or []
        for u in urls:
            skipped += 1
            print(f"[SKIP] {cat}（本 skill 暂无 importer）: {u[:120]}")
        if urls:
            results.append({"category": cat, "skipped": len(urls)})

    save_json(STATE_PATH, {"imported_urls": sorted(done)})

    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_err = sum(1 for r in results if r.get("status") == "error")
    print(f"\n{'=' * 60}")
    print(f"导入完成：成功 {n_ok}，失败 {n_err}，跳过 {skipped}")
    print(f"已导入 URL 记录：{STATE_PATH}")
    if n_err:
        print(json.dumps([r for r in results if r.get("status") == "error"],
                         ensure_ascii=False, indent=2))
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
