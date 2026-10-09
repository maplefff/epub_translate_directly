"""解開 Adobe ADEPT 加密的 EPUB：用帳號私鑰解出書本金鑰，再逐檔 AES 解密、解壓。

移植自 DeDRM_tools 的 ineptepub.py 與 acsm-to-epub 的 zeroedzipinfo.py（GPLv3）。
Copyright © 2009-2022 by i♥cabbages, Apprentice Harper et al. — https://github.com/noDRM/DeDRM_tools
改動：只留 Python 3 的解密流程；拿掉命令列與 Tk 介面、B&N PassHash 書的處理。
"""
import base64, hashlib, os, zipfile, zlib
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo
from lxml import etree
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA

NSMAP = {"adept": "http://ns.adobe.com/adept", "enc": "http://www.w3.org/2001/04/xmlenc#"}
ADOBE_AES = "http://www.w3.org/2001/04/xmlenc#aes128-cbc"
ADOBE_AES_RAW = "http://ns.adobe.com/adept/xmlenc#aes128-cbc-uncompressed"   # 影音檔之類不壓縮的


def _adept(tag):
    return "{%s}%s" % (NSMAP["adept"], tag)


def _enc(tag):
    return "{%s}%s" % (NSMAP["enc"], tag)


def _unpad(data):
    return data[:-data[-1]]


class ZeroedZipInfo(ZipInfo):
    """Python 的 zipfile 存檔時會把為 0 的 external_attr 改成 0o600<<16；原檔是 0 就要維持 0。
    https://github.com/python/cpython/issues/87713"""

    def __init__(self, zinfo):
        for k in self.__slots__:
            if hasattr(zinfo, k):
                setattr(self, k, getattr(zinfo, k))

    def __getattribute__(self, name):
        if name == "external_attr":
            return 0
        return object.__getattribute__(self, name)


class Decryptor:
    def __init__(self, bookkey, encryption):
        # 同一個 CBC 物件跨檔案沿用：每個檔案的前 16 bytes 是 IV，解出來的第一塊本來就要丟掉，
        # 所以前一個檔案留下的鏈結狀態不影響結果。
        self._aes = AES.new(bookkey, AES.MODE_CBC, b"\x00" * 16)
        self._encryption = etree.fromstring(encryption)
        self._encrypted, self._raw = set(), set()
        self._has_remaining = False
        remove = []
        for elem in self._encryption.findall("./%s/%s/%s" % (_enc("EncryptedData"), _enc("CipherData"),
                                                             _enc("CipherReference"))):
            path = elem.get("URI")
            if path is None:
                continue
            method = elem.getparent().getparent().find(_enc("EncryptionMethod")).get("Algorithm")
            if method == ADOBE_AES:
                self._encrypted.add(path)
                remove.append(elem.getparent().getparent())
            elif method == ADOBE_AES_RAW:
                self._raw.add(path)
                remove.append(elem.getparent().getparent())
            else:
                self._has_remaining = True          # 例如字型混淆，不屬於 DRM，留著
        for e in remove:
            e.getparent().remove(e)

    def remaining_xml(self):
        """還有非 Adobe 的加密項目（字型混淆）時，回傳刪掉 Adobe 項目後的 encryption.xml。"""
        if not self._has_remaining:
            return None
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(
            self._encryption, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")

    def decrypt(self, path, data):
        if path in self._encrypted or path in self._raw:
            data = _unpad(self._aes.decrypt(data)[16:])
            if path not in self._raw:
                data = _decompress(data)
        return data


def _decompress(data):
    dc = zlib.decompressobj(-15)
    try:
        out = dc.decompress(data)
        ex = dc.decompress(b"Z") + dc.flush()
        return out + ex if ex else out
    except zlib.error:
        return data                 # 可能本來就沒壓縮


def _remove_hardening(rights, keytype, keydata):
    """RMSDK >= 10 的「強化」ADEPT：書本金鑰外面多包一層，用 keyType 推出的 KEK 解開。"""
    text = lambda name: "".join(rights.findtext(".//%s" % _adept(name)))
    kekiv = UUID(int=UUID(text("resource")).int ^ UUID(text("device")).int
                 ^ UUID(text("fulfillment")[:36]).int).bytes
    rem = int(keytype, 10) % 16
    h = hashlib.sha256(keytype.encode("ascii")).digest()
    kek = h[2 * rem:16 + rem] + h[rem:2 * rem]
    return _unpad(AES.new(kek, AES.MODE_CBC, kekiv).decrypt(keydata))


def is_encrypted(path):
    with ZipFile(path) as z:
        names = set(z.namelist())
    return "META-INF/rights.xml" in names and "META-INF/encryption.xml" in names


def decrypt_book(userkey_der, inpath, outpath):
    """回傳 (狀態, 訊息)：0 成功；1 原本就沒有 DRM；2 失敗。"""
    with ZipFile(inpath) as inf:
        names = inf.namelist()
        if "META-INF/rights.xml" not in names or "META-INF/encryption.xml" not in names:
            return 1, "沒有 Adobe DRM"
        rights = etree.fromstring(inf.read("META-INF/rights.xml"))
        keyelem = rights.find(".//%s" % _adept("encryptedKey"))
        if keyelem is None:
            return 2, "rights.xml 裡沒有 encryptedKey"
        bookkey, keytype = keyelem.text, keyelem.attrib.get("keyType", "0")
        if len(bookkey) == 64:
            return 2, "這是 B&N PassHash 加密的書，不支援"
        if len(bookkey) < 172:
            return 2, "不是 Adobe ADEPT 加密的 EPUB"

        try:
            bookkey = base64.b64decode(bookkey)
            if int(keytype, 10) > 2:
                bookkey = _remove_hardening(rights, keytype, bookkey)
            bookkey = PKCS1_v1_5.new(RSA.importKey(userkey_der)).decrypt(bookkey, None)
        except ValueError:
            bookkey = None
        # 私鑰不對時 PKCS#1 v1.5 不一定丟例外，可能回傳空字串或長度不對的垃圾
        if not bookkey or len(bookkey) not in (16, 24, 32):
            return 2, "私鑰解不開書本金鑰（這本書不是用這組 Adobe ID 領的？）"

        try:
            decryptor = Decryptor(bookkey, inf.read("META-INF/encryption.xml"))
            order = ["mimetype"] + [n for n in names if n not in ("mimetype", "META-INF/rights.xml")]
            with ZipFile(outpath, "w", compression=ZIP_DEFLATED, allowZip64=False) as outf:
                for path in order:
                    if path not in names:
                        continue
                    data = inf.read(path)
                    if path == "META-INF/encryption.xml":
                        data = decryptor.remaining_xml()
                        if data is None:
                            continue
                    else:
                        data = decryptor.decrypt(path, data)
                    outf.writestr(_zipinfo(inf, path), data)
        except Exception as e:
            return 2, f"解密時發生錯誤：{type(e).__name__}: {e}"
    return 0, "解密完成"


def _zipinfo(inf, path):
    zi = ZipInfo(path)
    zi.compress_type = ZIP_STORED if path == "mimetype" else ZIP_DEFLATED
    old = inf.getinfo(path)
    # 沿用原檔的時間戳與屬性
    zi.date_time, zi.comment, zi.extra = old.date_time, old.comment, old.extra
    zi.internal_attr, zi.external_attr = old.internal_attr, old.external_attr
    zi.volume, zi.create_system, zi.create_version = old.volume, old.create_system, old.create_version
    if any(ord(c) >= 128 for c in path) or any(b >= 128 for b in zi.comment):
        zi.flag_bits |= 0x800           # 檔名含非 ASCII 字元時標記 UTF-8
    return ZeroedZipInfo(zi) if zi.external_attr == 0 else zi
