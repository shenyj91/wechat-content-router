#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wcdb_decrypt.py — 纯 Python 的 WCDB / SQLCipher 4 解密器（零原生依赖）

背景
----
微信 4.x 的本地数据库使用腾讯开源的 WCDB（其 SQLCipher 分支）加密。
此前依赖 WxLens 私有 DLL（wx_key.dll / WCDB.dll）做密钥提取 + 解密，
但该 DLL 在新版本会崩溃（SIGSEGV），且反盗用保护无法绕过。

本模块不依赖任何私有二进制，只用标准库 + `cryptography` 实现 SQLCipher 4
的页面解密。密钥派生 / HMAC / IV 布局已对照 **WCDB 实际使用的**
Tencent/sqlcipher @ f049bed66 源码（`src/crypto_impl.c`）逐一核实：

  * cipher key 来源：raw key（x'hex' 直接当密钥）或 passphrase（PBKDF2(password, salt, kdf_iter, 32)）
  * hmac_key = PBKDF2(cipher_key, kdf_salt XOR 0x3a, fast_kdf_iter=2, 32)
    —— 注意是「两次独立 PBKDF2」，不是 SQLCipher 旧版的「一次 PBKDF2 切分」
  * IV 直接存放在每页 reserve 区（不是用页码推导）
  * HMAC 输入 = (加密区 + 页内 IV)，末尾追加 4 字节页码（默认小端 LE）
  * reserve = hmac_sz + iv_sz(16)，向上取整到 block(16) 的倍数
  * 默认参数（已从 WCDB.dll 数据段逆向确认）：kdf_iter=256000、page_size=4096、
    hmac_salt_mask=0x3a、use_hmac=1、hmac/kdf 算法=SHA512、fast_kdf_iter=2

解密器会对一小组合法的参数预设做暴力尝试，命中 HMAC 校验即返回。

仅用于处理**你自己**的微信数据。

用法
----
  python3 wcdb_decrypt.py --key <64hex> --in message_0.db
  python3 wcdb_decrypt.py --key <64hex> --in /path/to/db_storage --out /path/to/plain
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

PAGE_SIZE = 4096
IV_SZ = 16                 # AES 块大小 / IV 长度
KEY_SZ = 32                # AES-256
FAST_KDF_ITER = 2          # SQLCipher 默认 fast_kdf_iter
HMAC_SALT_MASK = 0x3A

HASH = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}
HMAC_SZ = {"SHA1": 20, "SHA256": 32, "SHA512": 64}

SQLITE_MAGIC = b"SQLite format 3\x00"


def _roundup(n, block):
    return n if (n % block == 0) else ((n // block) + 1) * block


def _pbkdf2(algo, password, salt, iters, dklen):
    return hashlib.pbkdf2_hmac(HASH[algo], password, salt, iters, dklen)


def _aes_cbc_decrypt(key, iv, data):
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    d = cipher.decryptor()
    return d.update(data) + d.finalize()


def derive_keys(key_bytes, salt, cfg):
    """返回 (cipher_key, hmac_key)。

    - raw_key=True : cipher_key = key_bytes（32 字节原文）
    - raw_key=False: cipher_key = PBKDF2(key_bytes, salt, kdf_iter, 32)
    - hmac_key     : PBKDF2(cipher_key, salt^mask, fast_kdf_iter, 32)（use_hmac 时）
    """
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


def _try_config(data, key_bytes, cfg):
    """尝试用某个配置解密整库。成功返回 (纯文本 SQLite 字节, 命中配置)；失败返回 (None, None)。"""
    page_size = cfg["page_size"]
    hmac_algo = cfg["hmac_algorithm"]
    use_hmac = cfg["use_hmac"]

    if len(data) < page_size or len(data) % page_size != 0:
        return None, None

    salt = data[0:16]
    try:
        cipher_key, hmac_key = derive_keys(key_bytes, salt, cfg)
    except Exception:
        return None, None

    hmac_sz = HMAC_SZ[hmac_algo]
    reserve = (hmac_sz + IV_SZ) if use_hmac else IV_SZ
    reserve = _roundup(reserve, 16)
    n_pages = len(data) // page_size

    out = bytearray(len(data))

    for pageno in range(1, n_pages + 1):
        page = data[(pageno - 1) * page_size: pageno * page_size]
        region_start = 16 if pageno == 1 else 0
        # page 1 的明文头（salt）占前 16 字节，不参与加密；可加密区要再减去这 16 字节
        size = page_size - region_start - reserve

        enc = page[region_start: region_start + size]
        iv = page[region_start + size: region_start + size + IV_SZ]
        hmac_stored = page[region_start + size + IV_SZ:
                           region_start + size + IV_SZ + hmac_sz]

        try:
            plain = _aes_cbc_decrypt(cipher_key, iv, enc)
        except Exception:
            return None, None

        if use_hmac:
            # HMAC 输入 = (本页加密区 + 页内 IV)，末尾追加 4 字节页码
            hmac_input = page[region_start: region_start + size + IV_SZ]
            pgno_bytes = struct.pack(">I" if cfg["hmac_pgno"] == "be" else "<I", pageno)
            hmac_input = hmac_input + pgno_bytes
            calc = hmac_mod.new(hmac_key, hmac_input, HASH[hmac_algo]).digest()
            if not hmac_mod.compare_digest(calc[:hmac_sz], hmac_stored):
                return None, None
        else:
            # 无 HMAC：仅对 page 1 做粗略校验
            if pageno == 1 and not plain.startswith(SQLITE_MAGIC):
                return None, None

        # 重组明文页
        if pageno == 1:
            out[0:16] = SQLITE_MAGIC           # codec 写入的常量 magic
            out[16: 16 + size] = plain
            out[16 + size: page_size] = b"\x00" * (page_size - 16 - size)  # 清掉 reserve
        else:
            out[(pageno - 1) * page_size: (pageno - 1) * page_size + size] = plain
            out[(pageno - 1) * page_size + size: pageno * page_size] = \
                b"\x00" * reserve

    # 整体校验：page 1 必须是合法 SQLite 头
    if out[0:16] == SQLITE_MAGIC:
        return bytes(out), cfg
    return None, None


# 候选参数空间（按最可能命中排序：raw key + SHA512/SHA512 + LE + use_hmac）
def _build_configs():
    configs = []
    algos = ["SHA512", "SHA256", "SHA1"]
    for raw_key in (True, False):
        for hmac_algo in algos:
            for kdf_algo in algos:
                for pgno in ("le", "be"):
                    for salt_masked in (True, False):
                        configs.append({
                            "raw_key": raw_key,
                            "kdf_iter": 256000,
                            "hmac_algorithm": hmac_algo,
                            "kdf_algorithm": kdf_algo,
                            "hmac_pgno": pgno,
                            "salt_masked": salt_masked,
                            "use_hmac": True,
                            "page_size": PAGE_SIZE,
                            "fast_kdf_iter": FAST_KDF_ITER,
                        })
    # 无 HMAC 的几个常见组合（兜底）
    configs.append({"raw_key": True, "kdf_iter": 256000, "hmac_algorithm": "SHA512",
                    "kdf_algorithm": "SHA512", "hmac_pgno": "le", "salt_masked": True,
                    "use_hmac": False, "page_size": PAGE_SIZE, "fast_kdf_iter": FAST_KDF_ITER})
    return configs


CANDIDATE_CONFIGS = _build_configs()


def decrypt_wcdb(data, key_bytes, configs=None):
    """解密 WCDB 加密库字节。返回 (纯文本 SQLite 字节, 命中配置)。失败返回 (None, None)。"""
    configs = configs or CANDIDATE_CONFIGS
    for cfg in configs:
        try:
            plain, cfg_hit = _try_config(data, key_bytes, cfg)
        except Exception:
            plain, cfg_hit = None, None
        if plain is not None:
            return plain, cfg_hit
    return None, None


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
    """兼容 wechat_win_decrypt.decrypt_account_dbs 的调用签名 (in, out, key)。

    解密单个库到 out_path；命中返回配置 dict，失败抛 RuntimeError。
    这样解密链路完全走纯 Python，不再依赖会崩溃的 WxLens DLL。
    """
    out_path, cfg = decrypt_file(in_path, hex_key, out_path)
    if out_path is None:
        raise RuntimeError("所有候选参数均失败（密钥或配置不匹配）")
    return cfg


def main():
    ap = argparse.ArgumentParser(description="纯 Python WCDB/SQLCipher 解密器")
    ap.add_argument("--key", required=True, help="64 位十六进制密钥")
    ap.add_argument("--in", dest="in_path", required=True, help="加密库文件或目录")
    ap.add_argument("--out", default=None, help="输出目录（仅目录输入时）")
    ap.add_argument("--key-file", default=None, help="从文件读取密钥（避免命令行泄露）")
    args = ap.parse_args()

    key_hex = args.key
    if args.key_file:
        with open(args.key_file, "r") as f:
            key_hex = f.read().strip()

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
                res, cfg = decrypt_file(src, key_hex, dst)
                if res:
                    count += 1
                    sys.stderr.write(f"[OK] {rel}  raw_key={cfg['raw_key']} "
                                     f"{cfg['kdf_algorithm']}/{cfg['hmac_algorithm']} "
                                     f"pgno={cfg['hmac_pgno']} use_hmac={cfg['use_hmac']}\n")
                else:
                    sys.stderr.write(f"[FAIL] {rel}\n")
        sys.stderr.write(f"解密成功 {count} 个库\n")
    else:
        res, cfg = decrypt_file(args.in_path, key_hex, args.out)
        if res:
            sys.stderr.write(f"[OK] {res}\nconfig={json.dumps(cfg, ensure_ascii=False)}\n")
        else:
            sys.stderr.write("[FAIL] 所有候选参数均失败\n")
            sys.exit(1)


if __name__ == "__main__":
    main()
