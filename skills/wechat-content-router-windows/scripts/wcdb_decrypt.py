#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wcdb_decrypt.py — 纯 Python 的 WCDB / SQLCipher 4 解密器（零原生依赖，容错版）

背景
----
微信 4.x 的本地数据库使用腾讯开源的 WCDB（其 SQLCipher 分支）加密。本模块只用
标准库 + `cryptography` 实现 SQLCipher 4 的页面解密，不依赖任何会崩溃的私有 DLL。

密钥派生 / HMAC / IV 布局对照 WCDB 实际使用的 Tencent/sqlcipher 源码核实：

  * cipher key 来源：raw key（x'hex' 直接当密钥）或 passphrase（PBKDF2(password, salt, kdf_iter, 32)）
  * hmac_key = PBKDF2(cipher_key, salt XOR mask, fast_kdf_iter=2, 32)
    —— 两次独立 PBKDF2（不是 SQLCipher 旧版一次 PBKDF2 切分）
  * IV 直接存放在每页 reserve 区（不是用页码推导）
  * HMAC 输入 = (加密区 + 页内 IV)，末尾追加 4 字节页码（默认小端 LE）
  * reserve = hmac_sz + iv_sz(16)，向上取整到 block(16) 的倍数

关于"文件头"的重要事实
----------------------
加密 SQLCipher 库里，从 offset 16 起全部是密文，连 page_size(offset 16-17) 和
reserved(offset 20) 都无法从文件直接读出（只有前 16 字节 salt 是明文）。因此本解密器
**不读文件头字段**，而是暴力枚举 (page_size, hmac_algorithm) 组合，用「page1 的 HMAC
是否命中」做快速门控，命中后再整库解密。命中配置后逐页容错（见下）。

本次重构的关键改进
------------------
1. **逐页容错**：旧版遇到第一个 HMAC 不匹配就丢弃整个库（导致 message_0.db 读不到
   内容）。新版逐页解密，page1 HMAC 校验通过即视为 key 正确，其余页失败就清零保留、
   继续；返回"尽力解密"结果 + 失败页数统计（partial）。
2. **page1 HMAC 门控**：只有 page1 的 HMAC 命中才接受该候选配置，避免用错 key 输出伪明文。
3. **暴力枚举 page_size + hmac_algorithm**：page_size ∈ {1024,2048,4096,8192,65536}，
   hmac 算法 ∈ {SHA1,SHA256,SHA512}（reserve = hmac_sz+16）。rest 轴：raw_key、kdf_algo、
   pgno(le/be)、salt_masked、kdf_iter、fast_kdf_iter。
4. **--diagnose 模式**：逐配置打印 page1 校验结果 + 最佳配置下每页 HMAC 命中区间，
   便于在真机定位「为什么第 X 页起挂」。

仅用于处理**你自己**的微信数据。

用法
----
  python3 wcdb_decrypt.py --key <64hex> --in message_0.db
  python3 wcdb_decrypt.py --key <64hex> --in /path/to/db_storage --out /path/to/plain
  python3 wcdb_decrypt.py --key <64hex> --diagnose --in message_0.db
  from wcdb_decrypt import decrypt_wcdb
  plain_bytes = decrypt_wcdb(encrypted_bytes, key_bytes)   # (纯文本 SQLite 字节, 命中配置)
"""
import sys
import os
import struct
import hashlib
import hmac as hmac_mod
import argparse
import json

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.stderr.write("需要 cryptography 库：pip install cryptography\n")
    raise

IV_SZ = 16                 # AES 块大小 / IV 长度
KEY_SZ = 32                # AES-256
FAST_KDF_ITER_DEFAULT = 2  # SQLCipher 默认 fast_kdf_iter
HMAC_SALT_MASK = 0x3A

HASH = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}
HMAC_SZ = {"SHA1": 20, "SHA256": 32, "SHA512": 64}
# 候选 page_size（微信普遍 4096，但 message 库可能不同，全部尝试）
PAGE_SIZES = [4096, 1024, 2048, 8192, 65536]

SQLITE_MAGIC = b"SQLite format 3\x00"


def _roundup(n, block):
    return n if (n % block == 0) else ((n // block) + 1) * block


def _pbkdf2(algo, password, salt, iters, dklen):
    return hashlib.pbkdf2_hmac(HASH[algo], password, salt, iters, dklen)


def _aes_cbc_decrypt(key, iv, data):
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    d = cipher.decryptor()
    return d.update(data) + d.finalize()


def _derive_keys(key_bytes, salt, cfg):
    if cfg["raw_key"]:
        cipher_key = key_bytes[:KEY_SZ]
    else:
        cipher_key = _pbkdf2(cfg["kdf_algorithm"], key_bytes, salt, cfg["kdf_iter"], KEY_SZ)
    if cfg["use_hmac"]:
        hmac_salt = bytes(b ^ HMAC_SALT_MASK if cfg["salt_masked"] else b for b in salt)
        hmac_key = _pbkdf2(cfg["kdf_algorithm"], cipher_key, hmac_salt,
                           cfg["fast_kdf_iter"], KEY_SZ)
    else:
        hmac_key = None
    return cipher_key, hmac_key


def _decrypt_all(data, key_bytes, cfg, page_size, reserve):
    """逐页解密，容错。返回 (out_bytes, n_fail, failed_pages) 或 None（page1 校验不过）。

    - page1 的 HMAC 必须命中，否则视为 key/配置错误，返回 None。
    - 其余页 HMAC 不命中：该页正文清零，计入 failed_pages，继续。
    """
    hmac_algo = cfg["hmac_algorithm"]
    use_hmac = cfg["use_hmac"]
    if len(data) < page_size or len(data) % page_size != 0:
        return None

    salt = data[0:16]
    try:
        cipher_key, hmac_key = _derive_keys(key_bytes, salt, cfg)
    except Exception:
        return None

    hmac_sz = HMAC_SZ[hmac_algo] if use_hmac else 0
    n_pages = len(data) // page_size

    out = bytearray(len(data))
    failed_pages = []

    for pageno in range(1, n_pages + 1):
        page = data[(pageno - 1) * page_size: pageno * page_size]
        region_start = 16 if pageno == 1 else 0
        size = page_size - region_start - reserve

        enc = page[region_start: region_start + size]
        iv = page[region_start + size: region_start + size + IV_SZ]
        hmac_stored = page[region_start + size + IV_SZ:
                           region_start + size + IV_SZ + hmac_sz]

        try:
            plain = _aes_cbc_decrypt(cipher_key, iv, enc)
        except Exception:
            plain = None

        ok = False
        if plain is not None:
            if use_hmac:
                hmac_input = page[region_start: region_start + size + IV_SZ]
                pgno_bytes = struct.pack(">I" if cfg["hmac_pgno"] == "be" else "<I", pageno)
                hmac_input = hmac_input + pgno_bytes
                calc = hmac_mod.new(hmac_key, hmac_input, HASH[hmac_algo]).digest()
                ok = hmac_mod.compare_digest(calc[:hmac_sz], hmac_stored)
            else:
                ok = plain.startswith(SQLITE_MAGIC)

        if not ok:
            if pageno == 1:
                return None  # key/配置错误
            failed_pages.append(pageno)
            continue

        if pageno == 1:
            out[0:16] = SQLITE_MAGIC
            out[16: 16 + size] = plain
        else:
            out[(pageno - 1) * page_size: (pageno - 1) * page_size + size] = plain

    return bytes(out), len(failed_pages), failed_pages


def _quick_page1(data, key_bytes, cfg, page_size, reserve):
    """只解密 page1 并校验 HMAC，用于快速门控（避免无谓地整库解密）。"""
    if len(data) < page_size:
        return False
    salt = data[0:16]
    try:
        cipher_key, hmac_key = _derive_keys(key_bytes, salt, cfg)
    except Exception:
        return False
    hmac_sz = HMAC_SZ[cfg["hmac_algorithm"]] if cfg["use_hmac"] else 0
    page = data[0:page_size]
    region_start = 16
    size = page_size - region_start - reserve
    enc = page[region_start: region_start + size]
    iv = page[region_start + size: region_start + size + IV_SZ]
    hmac_stored = page[region_start + size + IV_SZ: region_start + size + IV_SZ + hmac_sz]
    try:
        plain = _aes_cbc_decrypt(cipher_key, iv, enc)
    except Exception:
        return False
    if cfg["use_hmac"]:
        hmac_input = page[region_start: region_start + size + IV_SZ]
        pgno_bytes = struct.pack(">I" if cfg["hmac_pgno"] == "be" else "<I", 1)
        hmac_input = hmac_input + pgno_bytes
        calc = hmac_mod.new(hmac_key, hmac_input, HASH[cfg["hmac_algorithm"]]).digest()
        return hmac_mod.compare_digest(calc[:hmac_sz], hmac_stored)
    return plain.startswith(SQLITE_MAGIC)


def _build_configs():
    """候选参数空间（枚举所有无法从文件直接确定的轴）。

    page_size 与 hmac_algorithm 在 decrypt_wcdb 外层枚举（决定 reserve）；
    这里枚举其余轴。
    """
    configs = []
    algos = ["SHA512", "SHA256", "SHA1"]
    kdf_iters = [256000, 64000, 4000, 1000]
    fast_iters = [2, 4000]
    for raw_key in (True, False):
        for kdf_algo in algos:
            for pgno in ("le", "be"):
                for salt_masked in (True, False):
                    for kdf_iter in kdf_iters:
                        for fast_kdf_iter in fast_iters:
                            configs.append({
                                "raw_key": raw_key,
                                "kdf_iter": kdf_iter,
                                "hmac_algorithm": None,   # 由外层注入
                                "kdf_algorithm": kdf_algo,
                                "hmac_pgno": pgno,
                                "salt_masked": salt_masked,
                                "use_hmac": True,
                                "fast_kdf_iter": fast_kdf_iter,
                            })
    configs.append({"raw_key": True, "kdf_iter": 256000, "hmac_algorithm": None,
                    "kdf_algorithm": "SHA512", "hmac_pgno": "le", "salt_masked": True,
                    "use_hmac": False, "fast_kdf_iter": FAST_KDF_ITER_DEFAULT})
    return configs


BASE_CONFIGS = _build_configs()


def decrypt_wcdb(data, key_bytes, configs=None):
    """解密 WCDB 加密库字节。

    返回 (纯文本 SQLite 字节, 命中配置)。命中配置为 None 表示全部失败。
    容错：若某配置 page1 校验通过但后续页有失败，仍返回该尽力解密结果
    （失败页已清零），并把配置里的 'partial' / 'failed_pages' 标注出来。
    """
    configs = configs or BASE_CONFIGS
    if len(data) < 512:
        return None, None

    perfect = None
    best_effort = None
    best_fail = None

    for page_size in PAGE_SIZES:
        if len(data) % page_size != 0:
            continue
        for hmac_algo in ("SHA512", "SHA256", "SHA1"):
            reserve = (HMAC_SZ[hmac_algo] + IV_SZ) if True else IV_SZ
            reserve = _roundup(reserve, 16)
            for base in configs:
                if base["use_hmac"] and base["hmac_algorithm"] is not None and base["hmac_algorithm"] != hmac_algo:
                    continue
                cfg = dict(base)
                cfg["hmac_algorithm"] = hmac_algo
                if not _quick_page1(data, key_bytes, cfg, page_size, reserve):
                    continue
                res = _decrypt_all(data, key_bytes, cfg, page_size, reserve)
                if res is None:
                    continue
                out, n_fail, failed_pages = res
                cfg = dict(cfg)
                cfg["partial"] = n_fail > 0
                cfg["failed_pages"] = failed_pages
                cfg["page_size"] = page_size
                cfg["reserved"] = reserve
                if n_fail == 0:
                    return out, cfg
                if best_effort is None or n_fail < best_fail:
                    best_effort = (out, cfg)
                    best_fail = n_fail

    if best_effort is not None:
        sys.stderr.write(
            f"[WARN] 尽力解密：{best_fail} 个页 HMAC 不匹配（已清零），"
            f"schema/可用页仍可读取。失败页(前20): {best_effort[1]['failed_pages'][:20]}"
            f"{'…' if len(best_effort[1]['failed_pages']) > 20 else ''}\n")
        return best_effort
    return None, None


def diagnose(data, key_bytes):
    """打印诊断：逐 (page_size, hmac_algo) 配置的 page1 校验 + 最佳配置逐页命中区间。"""
    lines = []
    if len(data) < 512:
        return "[DIAG] 文件过小，非合法 SQLite 库。"
    lines.append(f"[DIAG] 文件长度 {len(data)} 字节；尝试 page_size ∈ {PAGE_SIZES}")
    if len(data) % 4096 != 0 and len(data) % 1024 != 0:
        lines.append(f"[DIAG] ⚠ 文件长度不是常见 page_size 的整数倍"
                     f"（末尾可能有非数据库段 / WAL / 垃圾尾，导致尾部页无法解密）。")
    hits = []
    for page_size in PAGE_SIZES:
        if len(data) % page_size != 0:
            continue
        for hmac_algo in ("SHA512", "SHA256", "SHA1"):
            reserve = _roundup(HMAC_SZ[hmac_algo] + IV_SZ, 16)
            for base in BASE_CONFIGS:
                if base["use_hmac"] and base["hmac_algorithm"] is not None and base["hmac_algorithm"] != hmac_algo:
                    continue
                cfg = dict(base); cfg["hmac_algorithm"] = hmac_algo
                if not _quick_page1(data, key_bytes, cfg, page_size, reserve):
                    continue
                res = _decrypt_all(data, key_bytes, cfg, page_size, reserve)
                if res is None:
                    continue
                out, n_fail, failed_pages = res
                hits.append((page_size, hmac_algo, cfg, n_fail, failed_pages))
                if n_fail == 0:
                    lines.append(f"  ✅ page_size={page_size} {hmac_algo} raw={cfg['raw_key']} "
                                 f"kdf_algo={cfg['kdf_algorithm']} pgno={cfg['hmac_pgno']} "
                                 f"mask={cfg['salt_masked']} kdf_iter={cfg['kdf_iter']} fast={cfg['fast_kdf_iter']} "
                                 f"→ 全解成功(0 失败)")
    if not hits:
        lines.append("[DIAG] 无任何配置的 page1 HMAC 命中 → 密钥错误或 db 非 WCDB/SQLCipher。")
        return "\n".join(lines)
    # 选最佳（失败最少）做逐页区间
    best = min(hits, key=lambda h: h[3])
    _, hmac_algo, cfg, n_fail, failed_pages = best
    lines.append(f"[DIAG] 最佳配置: page_size={best[0]} {hmac_algo} "
                 f"raw={cfg['raw_key']} pgno={cfg['hmac_pgno']} "
                 f"kdf_iter={cfg['kdf_iter']} fast={cfg['fast_kdf_iter']} "
                 f"→ 失败页 {n_fail}/{best[0] and len(data)//best[0]}")
    if failed_pages:
        ranges = []
        s = p = None
        for pg in sorted(failed_pages):
            if s is None:
                s = p = pg
            elif pg == p + 1:
                p = pg
            else:
                ranges.append((s, p)); s = p = pg
        if s is not None:
            ranges.append((s, p))
        lines.append(f"[DIAG] 失败页区间(共 {len(failed_pages)} 页): "
                     + ", ".join(f"{a}-{b}" if a != b else f"{a}" for a, b in ranges[:40]))
    return "\n".join(lines)


def decrypt_file(in_path, key_hex, out_path=None):
    key_bytes = bytes.fromhex(key_hex)
    with open(in_path, "rb") as f:
        data = f.read()
    plain, cfg = decrypt_wcdb(data, key_bytes)
    if plain is None:
        return None, None
    if out_path is None:
        base, ext = os.path.splitext(in_path)
        out_path = base + ".decrypted" + ext
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(plain)
    return out_path, cfg


def decrypt_db(in_path, out_path, hex_key):
    """兼容 wechat_win_decrypt.decrypt_account_dbs 的调用签名 (in, out, key)。"""
    out_path, cfg = decrypt_file(in_path, hex_key, out_path)
    if out_path is None:
        raise RuntimeError("所有候选参数均失败（密钥或配置不匹配）")
    return cfg


def main():
    ap = argparse.ArgumentParser(description="纯 Python WCDB/SQLCipher 容错解密器")
    ap.add_argument("--key", default=None, help="64 位十六进制密钥")
    ap.add_argument("--in", dest="in_path", required=True, help="加密库文件或目录")
    ap.add_argument("--out", default=None, help="输出目录（仅目录输入时）")
    ap.add_argument("--key-file", default=None, help="从文件读取密钥（避免命令行泄露）")
    ap.add_argument("--diagnose", action="store_true", help="仅打印诊断信息，不写文件")
    args = ap.parse_args()

    key_hex = args.key
    if args.key_file:
        with open(args.key_file, "r") as f:
            key_hex = f.read().strip()
    if not key_hex:
        sys.stderr.write("必须提供 --key 或 --key-file\n")
        sys.exit(2)
    key_bytes = bytes.fromhex(key_hex)

    if os.path.isdir(args.in_path):
        out_dir = args.out or (args.in_path.rstrip("/") + ".plain")
        os.makedirs(out_dir, exist_ok=True)
        count = 0
        for root, _, files in os.walk(args.in_path):
            for fn in files:
                if not fn.endswith(".db"):
                    continue
                src = os.path.join(root, fn)
                rel = os.path.relpath(src, args.in_path)
                dst = os.path.join(out_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as f:
                    data = f.read()
                if args.diagnose:
                    sys.stderr.write(f"\n=== {rel} ===\n")
                    sys.stderr.write(diagnose(data, key_bytes) + "\n")
                    continue
                res, cfg = decrypt_file(src, key_hex, dst)
                if res:
                    count += 1
                    sys.stderr.write(f"[OK] {rel}  raw_key={cfg['raw_key']} "
                                     f"{cfg['kdf_algorithm']}/{cfg['hmac_algorithm']} "
                                     f"pgno={cfg['hmac_pgno']} use_hmac={cfg['use_hmac']}"
                                     f"{'  [partial ' + str(len(cfg['failed_pages'])) + ' 失败页]' if cfg.get('partial') else ''}\n")
                else:
                    sys.stderr.write(f"[FAIL] {rel}\n")
        if not args.diagnose:
            sys.stderr.write(f"解密成功 {count} 个库\n")
    else:
        with open(args.in_path, "rb") as f:
            data = f.read()
        if args.diagnose:
            print(diagnose(data, key_bytes))
            return
        res, cfg = decrypt_file(args.in_path, key_hex, args.out)
        if res:
            sys.stderr.write(f"[OK] {res}\nconfig={json.dumps(cfg, ensure_ascii=False)}\n")
        else:
            sys.stderr.write("[FAIL] 所有候选参数均失败\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
