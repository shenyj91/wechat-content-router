#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import browser_cookie3


DEFAULT_SETTINGS = {
    "openAfterCreate": False,
    "downloadImages": True,
    "runOcr": True,
    "keepImagesInNote": True,
    "deleteImagesAfterOcr": False,
    "appendImagesAfterText": True,
    "includeFrontmatter": True,
    "includeImportedAt": True,
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.json"
OCR_SCRIPT_PATH = SCRIPT_DIR / "ocr.swift"
OCR_CORRECTIONS_PATH = SCRIPT_DIR / "ocr_corrections.json"
PDF_RENDER_SCRIPT_PATH = SCRIPT_DIR / "render_xhs_note_pdf.mjs"
XHS_URL_RE = re.compile(r"https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com)/[^\s<>\"]+")


class XHSPageUnavailableError(RuntimeError):
    pass


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path=None):
    env_path = os.environ.get("WECHAT_CONTENT_ROUTER_CONFIG") or os.environ.get("XHS_OBSIDIAN_CONFIG")
    path = Path(config_path or env_path or DEFAULT_CONFIG_PATH).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Run init_local_config.py first or set WECHAT_CONTENT_ROUTER_CONFIG."
        )
    config = load_json(path, {})
    config["_config_path"] = str(path.resolve())
    return config


def normalize_route_config(config):
    route = ((config.get("routes") or {}).get("xhs") or {}).copy()
    storage_mode = ((config.get("storage") or {}).get("mode") or "obsidian").lower()
    if route:
        merged = dict(config)
        merged["import_root"] = route.get("import_root", "微信导入/小红书")
        merged["asset_root"] = route.get("asset_root", "微信导入/小红书/assets")
        merged["route_enabled"] = route.get("enabled", True)
        merged["pdf_source"] = route.get("pdf_source", "browser_render")
        if storage_mode == "local":
            merged["save_pdf"] = True
            merged["prefer_pdf_preview"] = True
        else:
            merged["save_pdf"] = route.get("save_pdf", False)
            merged["prefer_pdf_preview"] = route.get("prefer_pdf_preview", bool(merged["save_pdf"]))
        return merged

    merged = dict(config)
    merged.setdefault("import_root", "微信导入/小红书")
    merged.setdefault("asset_root", "微信导入/小红书/assets")
    merged["route_enabled"] = True
    merged["pdf_source"] = "browser_render"
    if storage_mode == "local":
        merged["save_pdf"] = True
        merged["prefer_pdf_preview"] = True
    else:
        merged["save_pdf"] = False
        merged["prefer_pdf_preview"] = False
    return merged


def storage_root(config):
    mode = ((config.get("storage") or {}).get("mode") or "obsidian").lower()
    if mode == "local":
        local_root = (config.get("storage") or {}).get("local_root") or ""
        if not local_root:
            raise RuntimeError("storage.mode=local 但没有配置 storage.local_root")
        return Path(local_root).expanduser()
    vault_root = config.get("vault_root") or ""
    if not vault_root:
        raise RuntimeError("storage.mode=obsidian 但没有配置 vault_root")
    return Path(vault_root).expanduser()


def resolve_vault_path(config, relative_or_absolute):
    value = Path(relative_or_absolute).expanduser()
    if value.is_absolute():
        return value
    return storage_root(config) / value


def load_xhs_cookie_jars():
    jars = []
    for browser_name, loader in (
        ("chrome", browser_cookie3.chrome),
        ("firefox", browser_cookie3.firefox),
    ):
        try:
            jar = list(loader(domain_name="xiaohongshu.com"))
            if jar:
                jars.append((browser_name, jar))
        except Exception:
            continue
    return jars


def score_cookie_jar(browser_name, jar):
    names = {cookie.name for cookie in jar}
    score = len(jar)
    if browser_name == "chrome":
        score += 1000
    if "web_session" in names:
        score += 50
    if "a1" in names:
        score += 10
    if "websectiga" in names:
        score += 10
    if "id_token" in names:
        score += 5
    return score


def load_xhs_cookie_header():
    jars = load_xhs_cookie_jars()
    if not jars:
        return ""
    browser_name, jar = max(jars, key=lambda item: score_cookie_jar(item[0], item[1]))
    pairs = []
    seen = set()
    for cookie in jar:
        key = (cookie.domain, cookie.name)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(pairs)


def decode_html(value):
    return (
        str(value or "")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&#x2F;", "/")
        .replace("\\u003C", "<")
        .replace("\\u003E", ">")
        .replace("\\u0026", "&")
        .replace('\\"', '"')
    )


def strip_topic_markers(text):
    return str(text or "").replace("[话题]", "").replace("\r", "").strip()


def unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def extract_tags(text):
    return unique(re.findall(r"#[^\s#]+", str(text or "")))


def sanitize_file_name(name):
    fallback = f"xhs-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}"
    safe = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", str(name or fallback))
    safe = re.sub(r"\s+", " ", safe).strip()[:80]
    return safe or fallback


def asset_base_name(title):
    safe = sanitize_file_name(title)
    safe = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", safe)
    safe = re.sub(r"\s+", "-", safe).strip("-")
    return safe[:50] or "xhs"


def extract_meta_tag(html, key, attr="property"):
    escaped = re.escape(key)
    patterns = [
        rf'<meta[^>]+{attr}=["\']{escaped}["\'][^>]+content=["\']([^"\']+)["\'][^>]*>',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\']{escaped}["\'][^>]*>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return decode_html(match.group(1)).strip()
    return ""


def extract_title_tag(html):
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s*-\s*小红书.*$", "", decode_html(match.group(1))).strip()


def extract_canonical_url(html):
    match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\'][^>]*>',
        html,
        re.IGNORECASE,
    ) or re.search(r'"canonical"\s*:\s*"([^"]+)"', html)
    return decode_html(match.group(1)).strip() if match else ""


def extract_initial_state(html):
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", html, re.S)
    if not match:
        return None
    raw = match.group(1).strip().replace("undefined", "null").rstrip(";")
    return json.loads(raw)


def find_note_object(state):
    note_map = (((state or {}).get("note") or {}).get("noteDetailMap") or {})
    for entry in note_map.values():
        note = (entry or {}).get("note")
        if note:
            return note
    return None


def extract_xhs_url(raw_input):
    match = XHS_URL_RE.search(raw_input or "")
    if not match:
        return ""
    return match.group(0).replace("&amp;", "&")


def fetch_text(url):
    cookie_header = load_xhs_cookie_header()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.xiaohongshu.com/",
            **({"Cookie": cookie_header} if cookie_header else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return {
            "text": response.read().decode(charset, errors="replace"),
            "final_url": response.geturl(),
        }


def fetch_bytes(url):
    cookie_header = load_xhs_cookie_header()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.xiaohongshu.com/",
            **({"Cookie": cookie_header} if cookie_header else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def extension_from_url(url, fallback="jpg"):
    try:
        path = urllib.parse.urlparse(url).path
    except ValueError:
        return fallback
    match = re.search(r"\.([A-Za-z0-9]+)$", path)
    return match.group(1).lower() if match else fallback


def load_ocr_corrections():
    return load_json(OCR_CORRECTIONS_PATH, {"direct_replacements": [], "regex_replacements": []})


def clean_ocr_text(text):
    if not text:
        return ""
    corrections = load_ocr_corrections()
    for old, new in corrections.get("direct_replacements", []):
        text = text.replace(old, new)
    for pattern, replacement in corrections.get("regex_replacements", []):
        text = re.sub(pattern, replacement, text)

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        line = re.sub(r"\s*•\s*", "•", line)
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"([一-龥])\s+([一-龥])", r"\1\2", line)
        line = re.sub(r"([A-Za-z])\s+([一-龥])", r"\1\2", line)
        line = re.sub(r"([一-龥])\s+([A-Za-z])", r"\1\2", line)
        lines.append(line)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def run_ocr(image_paths):
    if not image_paths:
        return []
    command = ["/usr/bin/swift", str(OCR_SCRIPT_PATH), *[str(path) for path in image_paths]]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    parsed = json.loads(result.stdout or "{}")
    items = []
    for item in parsed.get("items") or []:
        text = (item.get("text") or "").strip()
        if text:
            items.append({
                "path": item.get("path") or "",
                "text": clean_ocr_text(text),
            })
    return items


def relative_asset_path(note_path, asset_path):
    return os.path.relpath(asset_path, start=note_path.parent).replace(os.sep, "/")


def get_unique_note_path(folder, title):
    base_name = sanitize_file_name(title)
    candidate = folder / f"{base_name}.md"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{base_name} {counter}.md"
        counter += 1
    return candidate


def get_unique_pdf_path(folder, title):
    base_name = sanitize_file_name(title)
    candidate = folder / f"{base_name}.pdf"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{base_name} {counter}.pdf"
        counter += 1
    return candidate


def render_pdf(url, pdf_path, cookie_header=""):
    if not PDF_RENDER_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"PDF render script not found: {PDF_RENDER_SCRIPT_PATH}")
    node_cmd = os.environ.get("PLAYWRIGHT_NODE") or "node"
    env = dict(os.environ)
    if cookie_header:
        env["XHS_COOKIE_HEADER"] = cookie_header
    result = subprocess.run(
        [node_cmd, str(PDF_RENDER_SCRIPT_PATH), url, str(pdf_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message or "XHS PDF render failed")


def build_markdown(data, image_refs, settings):
    lines = []
    tags = [tag.lstrip("#") for tag in data.get("tags") or []]

    def yaml_quote(value):
        return str(value).replace('"', '\\"')

    if settings.get("includeFrontmatter", True):
        lines.append("---")
        lines.append(f'title: "{yaml_quote(data["title"])}"')
        if data.get("sourceUrl"):
            lines.append(f'source: "{yaml_quote(data["sourceUrl"])}"')
        if data.get("author"):
            lines.append(f'author: "{yaml_quote(data["author"])}"')
        lines.append('platform: "xiaohongshu"')
        lines.append(f'type: "{data.get("noteType") or "unknown"}"')
        if settings.get("includeImportedAt", True):
            lines.append(f'imported_at: "{datetime.now().isoformat()}"')
        if tags:
            lines.append("tags:")
            for tag in tags:
                lines.append(f"  - {tag}")
        lines.append("---")
        lines.append("")

    lines.append(f"# {data['title']}")
    lines.append("")

    if data.get("sourceUrl"):
        lines.append(f"原文链接：{data['sourceUrl']}")
        lines.append("")

    if data.get("author"):
        lines.append(f"作者：{data['author']}")
        lines.append("")

    if data.get("body"):
        lines.append(data["body"].strip())
        lines.append("")

    if data.get("tags"):
        lines.append(" ".join(data["tags"]))
        lines.append("")

    if data.get("ocrText"):
        lines.append("## 图片文字识别")
        lines.append("")
        lines.append(data["ocrText"].strip())
        lines.append("")

    if settings.get("appendImagesAfterText", True) and image_refs:
        for ref in image_refs:
            lines.append(f"![]({ref})")
            lines.append("")
    elif settings.get("keepImagesInNote") and image_refs:
        lines.append("## 图片")
        lines.append("")
        for ref in image_refs:
            lines.append(f"![]({ref})")
            lines.append("")

    lines.append(f"> 导入方式：{data.get('fetchMethod') or '__INITIAL_STATE__'}")
    lines.append("")

    markdown = "\n".join(lines).strip() + "\n"
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown


def fetch_xhs_page_data(url):
    fetched = fetch_text(url)
    html = fetched["text"]
    final_url = fetched["final_url"]
    state = extract_initial_state(html)
    note = find_note_object(state)

    title = (
        strip_topic_markers((note or {}).get("title"))
        or extract_meta_tag(html, "og:title")
        or extract_title_tag(html)
        or f"小红书笔记 {datetime.now().strftime('%Y-%m-%d')}"
    )
    title = re.sub(r"\s*-\s*小红书.*$", "", title).strip()

    body = strip_topic_markers((note or {}).get("desc"))
    author = (((note or {}).get("user") or {}).get("nickname") or "").strip()

    images = unique(
        [
            (img or {}).get("urlDefault") or (img or {}).get("urlPre") or (img or {}).get("url") or ""
            for img in ((note or {}).get("imageList") or [])
        ]
    )

    tags = unique(
        [f"#{tag.get('name')}" for tag in ((note or {}).get("tagList") or []) if tag.get("name")]
        + extract_tags(body)
    )

    unavailable_markers = (
        "你访问的页面不见了",
        "当前笔记暂时无法浏览",
        "内容无法展示",
    )
    unavailable = (
        "/404" in final_url
        or title in unavailable_markers
        or any(marker in html for marker in unavailable_markers)
    )
    if unavailable and not note:
        raise XHSPageUnavailableError(f"XiaoHongShu note unavailable: {final_url}")

    return {
        "title": title or "小红书笔记",
        "body": body or "",
        "author": author,
        "tags": tags,
        "sourceUrl": extract_canonical_url(html) or url,
        "images": images,
        "noteType": (note or {}).get("type") or ("image" if images else "unknown"),
        "fetchMethod": "__INITIAL_STATE__" if state else "html-meta",
        "finalUrl": final_url,
    }


def import_note(raw_input, config=None, overwrite=False):
    if not OCR_SCRIPT_PATH.exists():
        raise FileNotFoundError(f"OCR script not found: {OCR_SCRIPT_PATH}")

    config = normalize_route_config(config or load_config())
    if not config.get("route_enabled", True):
        raise RuntimeError("XHS route is disabled in config")
    settings = dict(DEFAULT_SETTINGS)
    settings.update(config.get("settings") or {})

    source_url = extract_xhs_url(raw_input)
    if not source_url:
        raise ValueError("没有识别到小红书链接")

    data = fetch_xhs_page_data(source_url)

    target_folder = resolve_vault_path(config, config["import_root"])
    asset_folder = resolve_vault_path(config, config["asset_root"])
    target_folder.mkdir(parents=True, exist_ok=True)
    asset_folder.mkdir(parents=True, exist_ok=True)

    safe_title = sanitize_file_name(data["title"])
    note_path = target_folder / f"{safe_title}.md" if overwrite else get_unique_note_path(target_folder, data["title"])
    local_image_paths = []
    image_refs = []
    pdf_path = None
    pdf_error = ""

    if settings.get("downloadImages", True):
        for index, image_url in enumerate(data["images"]):
            ext = extension_from_url(image_url, "jpg")
            file_name = f"{asset_base_name(data['title'])}-{index + 1}.{ext}"
            asset_path = asset_folder / file_name
            asset_path.write_bytes(fetch_bytes(image_url))
            local_image_paths.append(asset_path)
            image_refs.append(relative_asset_path(note_path, asset_path))

    if settings.get("runOcr", True) and local_image_paths:
        data["ocrItems"] = run_ocr(local_image_paths)
        data["ocrText"] = "\n\n---\n\n".join(
            item["text"] for item in data["ocrItems"] if item.get("text")
        )

    should_delete_images = settings.get("deleteImagesAfterOcr", False) and not settings.get("appendImagesAfterText", True)
    if should_delete_images and local_image_paths:
        for asset_path in local_image_paths:
            if asset_path.exists():
                asset_path.unlink()
        if not settings.get("keepImagesInNote", False):
            image_refs = []

    markdown = build_markdown(data, image_refs, settings)
    note_path.write_text(markdown, encoding="utf-8")

    if config.get("save_pdf", False):
        pdf_candidate = note_path.with_suffix(".pdf") if overwrite else get_unique_pdf_path(target_folder, data["title"])
        try:
            render_pdf(data.get("finalUrl") or data.get("sourceUrl") or source_url, pdf_candidate, load_xhs_cookie_header())
            pdf_path = pdf_candidate
        except Exception as error:
            pdf_error = str(error)

    return {
        "note_path": str(note_path),
        "pdf_path": str(pdf_path) if pdf_path else "",
        "preview_path": str(pdf_path) if (pdf_path and config.get("prefer_pdf_preview", True)) else str(note_path),
        "title": data["title"],
        "source_url": data["sourceUrl"],
        "images_downloaded": len(local_image_paths),
        "ocr_length": len(data.get("ocrText") or ""),
        "config_path": config["_config_path"],
        "pdf_error": pdf_error,
    }


def main():
    parser = argparse.ArgumentParser(description="Import a XiaoHongShu note into an Obsidian vault.")
    parser.add_argument("input_text", help="XiaoHongShu share URL or full share text")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing note with the same title")
    args = parser.parse_args()

    config = load_config(args.config)
    result = import_note(args.input_text, config=config, overwrite=args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
