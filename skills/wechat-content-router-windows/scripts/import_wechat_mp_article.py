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

import requests
from lxml import etree, html

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
PDF_RENDER_SCRIPT_PATH = Path(__file__).with_name("render_wechat_mp_pdf.mjs")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36"
)


class WeChatMPArticleUnavailable(RuntimeError):
    pass


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
    route = ((config.get("routes") or {}).get("mp") or {}).copy()
    route.setdefault("enabled", True)
    route.setdefault("import_root", "微信导入/公众号")
    storage_mode = ((config.get("storage") or {}).get("mode") or "obsidian").lower()
    route.setdefault("pdf_source", "browser_render")
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
    return (safe or "微信公众号文章")[:80]


def unique_md_path(folder: Path, title: str, overwrite: bool = False) -> Path:
    base = sanitize_file_name(title)
    candidate = folder / f"{base}.md"
    if overwrite or not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = folder / f"{base} {counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def unique_pdf_path(folder: Path, title: str, overwrite: bool = False) -> Path:
    base = sanitize_file_name(title)
    candidate = folder / f"{base}.pdf"
    if overwrite or not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = folder / f"{base} {counter}.pdf"
        if not candidate.exists():
            return candidate
        counter += 1


def load_html(url: str) -> tuple[str, str]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        }
    )
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.content.decode("utf-8", errors="replace")
    if "�" in text:
        for encoding in ("utf-8-sig", "gb18030", "gbk", "big5"):
            try:
                candidate = resp.content.decode(encoding)
            except UnicodeDecodeError:
                continue
            if "�" not in candidate:
                text = candidate
                break
    return text, resp.url


def extract_title(doc: html.HtmlElement) -> str:
    for expr in (
        'string(//meta[@property="og:title"]/@content)',
        'string(//meta[@name="twitter:title"]/@content)',
        'string(//title)',
    ):
        value = (doc.xpath(expr) or "").strip()
        if value:
            value = re.sub(r"\s*[_-]\s*微信公众平台.*$", "", value).strip()
            value = re.sub(r"\s*-\s*微信公众号.*$", "", value).strip()
            return value
    return "微信公众号文章"


def extract_author(doc: html.HtmlElement) -> str:
    for expr in (
        'string(//meta[@property="og:site_name"]/@content)',
        'string(//meta[@name="author"]/@content)',
        'string(//a[@id="js_name"])',
    ):
        value = (doc.xpath(expr) or "").strip()
        if value:
            return value
    return ""


def extract_publish_time(doc: html.HtmlElement) -> str:
    for expr in (
        'string(//meta[@property="article:published_time"]/@content)',
        'string(//em[@id="publish_time"])',
        'string(//span[@id="publish_time"])',
    ):
        value = (doc.xpath(expr) or "").strip()
        if value:
            return value
    return ""


def extract_account_name(doc: html.HtmlElement) -> str:
    for expr in (
        'string(//a[@id="js_name"])',
        'string(//meta[@property="og:site_name"]/@content)',
    ):
        value = (doc.xpath(expr) or "").strip()
        if value:
            return value
    return ""


def extract_article_body(doc: html.HtmlElement) -> str:
    content = doc.xpath('//*[@id="js_content"]')
    if not content:
        return ""
    root = content[0]
    for node in root.xpath(".//script|.//style|.//noscript"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    parts = []
    for child in root.iterchildren():
        if isinstance(child, etree._Comment):
            continue
        parts.append(etree.tostring(child, encoding="unicode", method="html"))
    body = "\n".join(part for part in parts if part and part.strip())
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def build_markdown(*, title: str, account_name: str, author: str, publish_time: str, source_url: str, body: str) -> str:
    def q(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    lines = [
        "---",
        f'title: "{q(title)}"',
        f'sourceUrl: "{q(source_url)}"',
        'platform: "wechat_mp"',
        f'imported_at: "{datetime.now().isoformat()}"',
    ]
    if account_name:
        lines.append(f'account: "{q(account_name)}"')
    if author:
        lines.append(f'author: "{q(author)}"')
    if publish_time:
        lines.append(f'published_at: "{q(publish_time)}"')
    lines += ["---", "", f"# {title}", ""]
    if account_name:
        lines.append(f"公众号：{account_name}")
    if author:
        lines.append(f"作者：{author}")
    if publish_time:
        lines.append(f"发布时间：{publish_time}")
    if source_url:
        lines.append(f"原文链接：{source_url}")
    if account_name or author or publish_time or source_url:
        lines.append("")
    if body:
        lines += ["<!-- 微信公众号原排版 -->", "", body.strip(), ""]
    return "\n".join(lines).strip() + "\n"


def render_pdf(url: str, pdf_path: Path) -> None:
    if not PDF_RENDER_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"PDF render script not found: {PDF_RENDER_SCRIPT_PATH}")
    node_cmd = os.environ.get("PLAYWRIGHT_NODE") or "node"
    result = subprocess.run(
        [node_cmd, str(PDF_RENDER_SCRIPT_PATH), url, str(pdf_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message or "Playwright PDF render failed")


def import_article(url: str, config=None, overwrite: bool = False) -> dict[str, str | int]:
    config = config or load_config()
    route = route_config(config)
    if not route.get("enabled", True):
        raise RuntimeError("MP route is disabled in config")

    html_text, final_url = load_html(url)
    doc = html.fromstring(html_text)
    title = extract_title(doc)
    account_name = extract_account_name(doc)
    author = extract_author(doc)
    publish_time = extract_publish_time(doc)
    body = extract_article_body(doc)

    if not body and not title:
        raise WeChatMPArticleUnavailable(f"无法解析公众号正文: {final_url}")

    target_folder = resolve_vault_path(config, route["import_root"])
    target_folder.mkdir(parents=True, exist_ok=True)
    note_path = unique_md_path(target_folder, title, overwrite=overwrite)
    pdf_path = None
    pdf_error = ""
    markdown = build_markdown(
        title=title,
        account_name=account_name,
        author=author,
        publish_time=publish_time,
        source_url=final_url,
        body=body,
    )
    note_path.write_text(markdown, encoding="utf-8")
    if route.get("save_pdf", False):
        pdf_candidate = unique_pdf_path(target_folder, title, overwrite=overwrite)
        try:
            render_pdf(final_url, pdf_candidate)
            pdf_path = pdf_candidate
        except Exception as error:
            pdf_error = str(error)
    return {
        "note_path": str(note_path),
        "pdf_path": str(pdf_path) if pdf_path else "",
        "preview_path": str(pdf_path) if (pdf_path and route.get("prefer_pdf_preview", True)) else str(note_path),
        "title": title,
        "account_name": account_name,
        "body_length": len(body),
        "source_url": final_url,
        "config_path": config.get("_config_path", ""),
        "pdf_error": pdf_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--config")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = import_article(args.url, config=load_config(args.config), overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
