#!/usr/bin/env python3
"""WCDB 4.x 解密（尝试多种参数组合）"""
import hashlib, hmac, sys
from pathlib import Path
from Crypto.Cipher import AES

configs = [
    {"iter": 256000, "hmac_iter": 2, "hash": "sha512"},
    {"iter": 64000, "hmac_iter": 2, "hash": "sha512"},
    {"iter": 4000, "hmac_iter": 2, "hash": "sha1"},
]

def try_decrypt(enc_path, out_path, key_hex):
    key = bytes.fromhex(key_hex)
    data = open(enc_path,'rb').read()
    salt = data[:16]
    
    for cfg in configs:
        try:
            dk = hashlib.pbkdf2_hmac(cfg["hash"], key, salt, cfg["iter"], 32)
            mac_salt = bytes(x^0x3a for x in salt)
            mac_key = hashlib.pbkdf2_hmac(cfg["hash"], dk, mac_salt, cfg["hmac_iter"], 32)
            
            page = data[:4096]
            hmac_start = 4096-64
            stored_mac = page[hmac_start:]
            
            h = hmac.new(mac_key, digestmod=hashlib.sha512)
            h.update(page[:hmac_start])
            h.update((1).to_bytes(4,"little"))
            
            if hmac.compare_digest(stored_mac, h.digest()):
                print(f"找到正确参数: {cfg}")
                # 完整解密逻辑...
                return True
        except:
            pass
    
    print("所有参数都失败")
    return False

if __name__=="__main__":
    try_decrypt(sys.argv[1], sys.argv[2], sys.argv[3])
