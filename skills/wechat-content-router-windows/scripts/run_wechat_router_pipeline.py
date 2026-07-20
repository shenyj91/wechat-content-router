#!/usr/bin/env python3
import json
import importlib.util
import io
import sys
from pathlib import Path
from contextlib import redirect_stdout

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"


def check_dependencies(source_mode: str) -> list[str]:
    import shutil
    import subprocess
    errors = []
    if source_mode == "decrypted_files":
        try:
            import Crypto.Cipher  # noqa: F401
        except Exception:
            errors.append("pycryptodome未安装，请先运行：python -m pip install pycryptodome")
        return errors
    if source_mode != "decrypted_files":
        if not shutil.which("node"):
            errors.append("Node.js未安装，请先安装：https://nodejs.org/")
        else:
            try:
                result = subprocess.run(
                    ["node", "-e", "require('koffi'); console.log('ok')"],
                    capture_output=True, text=True, timeout=5
                )
                if "ok" not in result.stdout:
                    errors.append("koffi未安装，请在scripts目录运行：npm install koffi")
            except Exception:
                errors.append("koffi检测失败")
    return errors


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config):
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_state(state_path: Path) -> set:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return set(data.get("processed_keys", []))
    except Exception:
        return set()


def save_state(state_path: Path, processed_keys: set):
    state_path.write_text(
        json.dumps({"processed_keys": sorted(processed_keys)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_key(item: dict) -> str:
    return f"{item.get('create_time', 0)}:{item.get('local_id', 0)}:{item.get('url', '')}"


def load_importer(module_name, script_path):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_local_link_importer():
    return load_importer("wechat_router_local_links", SCRIPT_DIR / "import_latest_wechat_links.py")


def main():
    config = load_config()
    wechat = config.get("wechat") or {}

    if not wechat.get("enabled"):
        print(json.dumps({"status": "wechat_disabled"}, ensure_ascii=False, indent=2))
        return

    source_mode = (wechat.get("source_mode") or "decrypted_files").lower()
    dep_errors = check_dependencies(source_mode)
    if dep_errors:
        import sys as _sys, json as _json
        print(_json.dumps({"status": "dependency_error", "errors": dep_errors}, ensure_ascii=False))
        _sys.exit(1)
    state_path = Path(config.get("state_file") or (SCRIPT_DIR / ".wechat-router-state.json"))
    processed_keys = load_state(state_path)

    if source_mode == "decrypted_files":
        account_dir = wechat.get("account_dir")
        if not account_dir:
            print(json.dumps({
                "status": "account_not_configured",
                "error": "未选择微信账号，请先运行 use_router.py 完成账号选择配置",
            }, ensure_ascii=False, indent=2))
            sys.exit(1)
        decrypt_module = load_importer("wechat_win_decrypt", SCRIPT_DIR / "wechat_win_decrypt.py")
        try:
            with redirect_stdout(io.StringIO()):
                if not wechat.get("_cached_key"):
                    config["wechat"]["_cached_key"] = decrypt_module.extract_wechat_key()
                    save_config(config)
                decrypted = decrypt_module.decrypt_account_dbs(
                    account_dir=account_dir,
                    hex_key=config["wechat"]["_cached_key"],
                )
            importer = load_local_link_importer()
            temp_config = {
                **config,
                "wechat": {
                    "session_db": decrypted.get("session_db") or "",
                    "message_dir": decrypted.get("message_dir") or "",
                    "chat_username": wechat.get("chat_username") or "filehelper",
                },
            }
            result = importer.collect_recent_messages(temp_config)
        except Exception as e:
            print(json.dumps({
                "status": "decrypt_failed",
                "error": str(e),
            }, ensure_ascii=False, indent=2))
            sys.exit(1)

        links = result or []
        if not links:
            print(json.dumps({"status": "no_new_links", "count": 0}, ensure_ascii=False, indent=2))
            return

        new_links = []
        for item in links:
            key = make_key(item)
            if key not in processed_keys:
                new_links.append(item)

        if not new_links:
            print(json.dumps({"status": "no_new_links", "count": 0, "skipped": len(links)}, ensure_ascii=False, indent=2))
            return

        xhs_importer = load_importer("router_xhs", SCRIPT_DIR / "import_xhs_note.py")
        mp_importer = load_importer("router_mp", SCRIPT_DIR / "import_wechat_mp_article.py")
        feishu_importer = load_importer("router_feishu", SCRIPT_DIR / "import_feishu_page.py")

        imports = []
        for item in new_links:
            key = make_key(item)
            try:
                if item["type"] == "xhs":
                    res = xhs_importer.import_note(item["raw_text"], config=config)
                elif item["type"] == "mp":
                    res = mp_importer.import_article(item["url"], config=config)
                elif item["type"] == "feishu":
                    res = feishu_importer.import_page(item["url"], config=config)
                else:
                    continue
                imports.append({"type": item["type"], "url": item["url"], "result": res})
                processed_keys.add(key)
            except Exception as e:
                imports.append({"type": item["type"], "url": item["url"], "error": str(e)})

        save_state(state_path, processed_keys)
        print(json.dumps({
            "status": "imported",
            "count": len(imports),
            "skipped": len(links) - len(new_links),
            "state_file": str(state_path),
            "imports": imports,
        }, ensure_ascii=False, indent=2))
        return

    account_dir = wechat.get("account_dir")
    if not account_dir:
        print(json.dumps({
            "status": "account_not_configured",
            "error": "未选择微信账号，请先运行 use_router.py 完成账号选择配置",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    decrypt_module = load_importer(
        "wechat_win_decrypt",
        SCRIPT_DIR / "wechat_win_decrypt.py",
    )

    chat_username = wechat.get("chat_username") or "filehelper"
    cached_key = wechat.get("_cached_key")

    try:
        result = decrypt_module.decrypt_and_get_links(
            session_id=chat_username,
            limit=100,
            key=cached_key,
            account_dir=account_dir,
        )
    except Exception as e:
        print(json.dumps({
            "status": "decrypt_failed",
            "error": str(e),
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    if result.get("key") and not cached_key:
        config["wechat"]["_cached_key"] = result["key"]
        save_config(config)

    links = result.get("links", [])
    if not links:
        print(json.dumps({
            "status": "no_new_links",
            "count": 0,
        }, ensure_ascii=False, indent=2))
        return

    new_links = []
    for item in links:
        key = make_key(item)
        if key not in processed_keys:
            new_links.append(item)

    if not new_links:
        print(json.dumps({
            "status": "no_new_links",
            "count": 0,"skipped": len(links),
        }, ensure_ascii=False, indent=2))
        return

    xhs_importer = load_importer("router_xhs", SCRIPT_DIR / "import_xhs_note.py")
    mp_importer = load_importer("router_mp", SCRIPT_DIR / "import_wechat_mp_article.py")
    feishu_importer = load_importer("router_feishu", SCRIPT_DIR / "import_feishu_page.py")

    imports = []
    for item in new_links:
        key = make_key(item)
        try:
            if item["type"] == "xhs":
                res = xhs_importer.import_note(item["raw_text"], config=config)
            elif item["type"] == "mp":
                res = mp_importer.import_article(item["url"], config=config)
            elif item["type"] == "feishu":
                res = feishu_importer.import_page(item["url"], config=config)
            else:
                continue
            imports.append({"type": item["type"], "url": item["url"], "result": res})
            processed_keys.add(key)
        except Exception as e:
            imports.append({"type": item["type"], "url": item["url"], "error": str(e)})

    save_state(state_path, processed_keys)

    print(json.dumps({
        "status": "imported",
        "count": len(imports),
        "skipped": len(links) - len(new_links),
        "state_file": str(state_path),
        "imports": imports,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
