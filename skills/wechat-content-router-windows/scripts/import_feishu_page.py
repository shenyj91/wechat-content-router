#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
RENDER_SCRIPT_PATH = Path(__file__).with_name("render_feishu_page.mjs")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(config_path=None):
    env_path = os.environ.get("WECHAT_CONTENT_ROUTER_CONFIG")
    path = Path(config_path or env_path or DEFAULT_CONFIG_PATH).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    config = load_json(path, {})
    config["_config_path"] = str(path.resolve())
    return config


def route_config(config: dict) -> dict:
    route = ((config.get("routes") or {}).get("feishu") or {}).copy()
    route.setdefault("enabled", True)
    route.setdefault("import_root", "微信导入/飞书")
    route.setdefault("pdf_source", "browser_render")
    storage_mode = ((config.get("storage") or {}).get("mode") or "obsidian").lower()
    if storage_mode == "local":
        route["save_pdf"] = True
        route["prefer_pdf_preview"] = True
    else:
        route.setdefault("save_pdf", False)
        route.setdefault("prefer_pdf_preview", bool(route.get("save_pdf")))
    return route


def resolve_vault_path(config: dict, relative_or_absolute: str) -> Path:
    value = Path(relative_or_absolute).expanduser()
    if value.is_absolute():
        return value
    storage = config.get("storage") or {}
    mode = (storage.get("mode") or "obsidian").lower()
    if mode == "local":
        local_root = storage.get("local_root") or ""
        if not local_root:
            raise RuntimeError("storage.mode=local 但没有配置 storage.local_root")
        return Path(local_root).expanduser() / value
    vault_root = config.get("vault_root") or ""
    if not vault_root:
        raise RuntimeError("storage.mode=obsidian 但没有配置 vault_root")
    return Path(vault_root).expanduser() / value


def sanitize_file_name(name: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", str(name or ""))
    safe = re.sub(r"\s+", " ", safe).strip()
    return (safe or "飞书文档")[:80]


def unique_path(folder: Path, title: str, suffix: str, overwrite: bool = False) -> Path:
    base = sanitize_file_name(title)
    candidate = folder / f"{base}.{suffix}"
    if overwrite or not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = folder / f"{base} {counter}.{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def clean_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", str(text or ""))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_markdown(*, title: str, source_url: str, body_text: str) -> str:
    def q(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    lines = [
        "---",
        f'title: "{q(title)}"',
        f'sourceUrl: "{q(source_url)}"',
        'platform: "feishu"',
        f'imported_at: "{datetime.now().isoformat()}"',
        "---",
        "",
        f"# {title}",
        "",
        f"原文链接：{source_url}",
        "",
    ]
    if body_text:
        lines += [body_text, ""]
    return "\n".join(lines).strip() + "\n"


def render_page(url: str, pdf_path: Path | None = None) -> dict:
    if not RENDER_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"Feishu render script not found: {RENDER_SCRIPT_PATH}")
    node_cmd = os.environ.get("PLAYWRIGHT_NODE") or "node"
    command = [node_cmd, str(RENDER_SCRIPT_PATH), url]
    if pdf_path is not None:
        command.append(str(pdf_path))
    # cwd 固定到脚本所在目录（scripts/），并注入 skill 的 node_modules，
    # 确保无论从哪个目录运行都能解析到 playwright（ESM import 按脚本位置向上查找，
    # 这里再设 cwd/NODE_PATH 双保险）。
    script_dir = RENDER_SCRIPT_PATH.parent
    skill_node_modules = script_dir.parent / "node_modules"
    env = dict(os.environ)
    if skill_node_modules.exists():
        env["NODE_PATH"] = str(skill_node_modules)
    result = subprocess.run(command, capture_output=True, text=True, cwd=str(script_dir), env=env)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        if "Executable doesn't exist" in message or "chromium" in message.lower() or "playwright" in message.lower():
            message += ("\n[提示] 飞书渲染依赖 Playwright 的 Chromium。请在该 skill 目录运行："
                        " npm i playwright && npx playwright install chromium")
        raise RuntimeError(message or "Feishu page render failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Feishu render result parse failed: {error}") from error


def import_page(url: str, config=None, overwrite: bool = False) -> dict[str, str | int]:
    config = config or load_config()
    route = route_config(config)
    if not route.get("enabled", True):
        raise RuntimeError("Feishu route is disabled in config")

    target_folder = resolve_vault_path(config, route["import_root"])
    target_folder.mkdir(parents=True, exist_ok=True)

    placeholder_title = "飞书文档"
    pdf_path = unique_path(target_folder, placeholder_title, "pdf", overwrite=overwrite) if route.get("save_pdf", False) else None
    pdf_error = ""
    try:
        rendered = render_page(url, pdf_path)
    except Exception as error:
        if pdf_path is not None and pdf_path.exists():
            pdf_path.unlink()
        pdf_path = None
        pdf_error = str(error)
        rendered = render_page(url, None)

    title = sanitize_file_name(rendered.get("title") or placeholder_title)
    final_url = rendered.get("source_url") or url
    body_text = clean_text(rendered.get("body_text") or "")

    note_path = unique_path(target_folder, title, "md", overwrite=overwrite)
    if pdf_path is not None and not overwrite:
        desired_pdf_path = unique_path(target_folder, title, "pdf", overwrite=False)
        if desired_pdf_path != pdf_path and pdf_path.exists():
            pdf_path.rename(desired_pdf_path)
            pdf_path = desired_pdf_path
    markdown = build_markdown(title=title, source_url=final_url, body_text=body_text)
    note_path.write_text(markdown, encoding="utf-8")

    return {
        "note_path": str(note_path),
        "pdf_path": str(pdf_path) if pdf_path else "",
        "preview_path": str(pdf_path) if (pdf_path and route.get("prefer_pdf_preview", True)) else str(note_path),
        "title": title,
        "source_url": final_url,
        "body_length": len(body_text),
        "config_path": config.get("_config_path", ""),
        "pdf_error": pdf_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--config")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = import_page(args.url, config=load_config(args.config), overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
