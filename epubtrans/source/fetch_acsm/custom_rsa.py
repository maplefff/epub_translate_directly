"""Adobe 簽章用的「教科書 RSA」：PKCS#1 v1.5 type 1 補齊後直接用私鑰次方，不包 DigestInfo。

標準的 PKCS#1 v1.5 簽章會把雜湊包進 DigestInfo，Adobe 的協定不包，所以不能直接用
函式庫的簽章 API。

移植自 acsm-calibre-plugin 的 customRSA.py（GPLv3）。
Copyright (c) 2021-2023 Leseratte10 — https://github.com/Leseratte10/acsm-calibre-plugin
改動：只留 Python 3 的寫法。
"""
from Crypto.PublicKey import RSA


def _byte_size(n):
    return (n.bit_length() + 7) // 8


def _pad(message, target_len):
    """00 01 FF…FF 00 MESSAGE"""
    if len(message) > target_len - 11:
        raise OverflowError(f"訊息太長：{len(message)} bytes，最多 {target_len - 11}")
    return b"\x00\x01" + b"\xff" * (target_len - len(message) - 3) + b"\x00" + bytes(message)


def encrypt_for_adobe_signature(signing_key_der, message):
    key = RSA.importKey(signing_key_der)
    keylen = _byte_size(key.n)
    payload = int.from_bytes(_pad(message, keylen), "big")
    if payload > key.n:
        raise ValueError("Invalid message")
    return pow(payload, key.d, key.n).to_bytes(keylen, "big")
