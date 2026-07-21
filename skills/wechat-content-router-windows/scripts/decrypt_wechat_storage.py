#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decrypt_wechat_storage.py — 解密整个微信 db_storage 目录（纯 Python，零原生依赖）

这是 WxLens `wcdb_api.dll` / `WCDB.dll` 的**纯 Python 替代品**。那个 DLL 在新版
会崩溃（SIGSEGV），且反盗用（InitProtection）无法绕过。本脚本只用
`wcdb_decrypt.py` 做 SQLCipher 4 / WCDB 页面解密，不需要任何私有二进制。

它读取 key-extractor.js 产出的 64 位十六进制密钥（或手动指定的 --key / --key-file），
递归解密输入目录下的所有 *.db（含子目录，结构保持不变），输出到明文目录。

仅用于处理**你自己**的微信数据。

用法
----
  # 解密某个 account 目录下的 db_storage（自动定位 db_storage 子目录）
  python3 decrypt_wechat_storage.py --key <64hex> --in "E:/Weixin Data/xxxx" --out "E:/知识星球/decrypted"

  # 直接给 db_storage 目录
  python3 decrypt_wechat_storage.py --key <64hex> --in "E:/.../db_storage" --out "E:/.../decrypted"

  # 从文件读密钥（key-extractor.js 的 key.tmp / status.json 里的 key 字段）
  python3 decrypt_wechat_storage.py --key-file key.txt --in ... --out ...
"""
import sys
import os
import json
import argparse

# 同目录下的解密器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wcdb_decrypt import decrypt_wcdb

# 这些库通常不需要解密（或解密后无 SQLite 结构）；跳过可省时间
SKIP_NAMES = {"fts_db", "fts", "index", "session_large"}


def find_db_storage(in_path):
    """输入可能是 account 目录（含 db_storage 子目录）或直接是 db_storage。"""
    if os.path.isfile(in_path):
        return None
    cand = os.path.join(in_path, "db_storage")
    if os.path.isdir(cand):
        return cand
    return in_path


def load_key(args):
    if args.key:
        return args.key.strip()
    if args.key_file:
        txt = open(args.key_file, "r", encoding="utf-8").read().strip()
        # 兼容从 status.json 直接抠出来的 JSON
        try:
            obj = json.loads(txt)
            if isinstance(obj, dict) and obj.get("key"):
                return obj["key"].strip()
        except Exception:
            pass
        # 或直接是 64hex
        return txt
    raise SystemExit("必须提供 --key 或 --key-file")


def main():
    ap = argparse.ArgumentParser(description="纯 Python 解密微信 db_storage（替代 WxLens DLL）")
    ap.add_argument("--key", default=None, help="64 位十六进制密钥")
    ap.add_argument("--key-file", default=None, help="从文件读取密钥（明文 64hex 或含 key 字段的 JSON）")
    ap.add_argument("--in", dest="in_path", required=True, help="account 目录或 db_storage 目录")
    ap.add_argument("--out", dest="out_path", required=True, help="明文输出目录")
    ap.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    args = ap.parse_args()

    key_hex = load_key(args)
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 32:
        sys.stderr.write(f"[ERR] 密钥长度应为 32 字节（64 hex），实际 {len(key_bytes)} 字节\n")
        sys.exit(2)

    storage = find_db_storage(args.in_path)
    if storage is None:
        sys.stderr.write("[ERR] 输入必须是目录\n")
        sys.exit(2)
    sys.stderr.write(f"[INFO] 加密库根目录: {storage}\n")

    out_root = args.out_path
    os.makedirs(out_root, exist_ok=True)

    decrypted = 0
    failed = 0
    skipped = 0

    if args.no_recursive:
        entries = [storage]
    else:
        entries = [root for root, _, _ in os.walk(storage)] or [storage]

    for root in entries:
        for fn in sorted(os.listdir(root)):
            if not fn.lower().endswith(".db"):
                continue
            base = fn[:-3].lower()
            if base in SKIP_NAMES or base.endswith("_fts"):
                skipped += 1
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, storage)
            dst = os.path.join(out_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with open(src, "rb") as f:
                    data = f.read()
                plain, cfg = decrypt_wcdb(data, key_bytes)
            except Exception as e:
                sys.stderr.write(f"[FAIL] {rel}: 读取/解密异常 {e}\n")
                failed += 1
                continue
            if plain is None:
                sys.stderr.write(f"[FAIL] {rel}: 所有候选参数均失败（密钥或配置不匹配）\n")
                failed += 1
                continue
            with open(dst, "wb") as f:
                f.write(plain)
            decrypted += 1
            sys.stderr.write(f"[OK] {rel}  raw_key={cfg['raw_key']} "
                             f"{cfg['kdf_algorithm']}/{cfg['hmac_algorithm']} "
                             f"pgno={cfg['hmac_pgno']} use_hmac={cfg['use_hmac']}\n")

    sys.stderr.write(f"\n解密完成: 成功 {decrypted}，失败 {failed}，跳过 {skipped}\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
