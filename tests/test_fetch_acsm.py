#!/usr/bin/env python3
"""ACSM 領書模組的離線測試：不連網、不用 Adobe 授權、不用真的書。

真的領書只能拿使用者的 ACSM 測（而且一張 ACSM 只有幾小時效期），所以把能離線驗證的部分釘住：
  - Adobe 的 XML 雜湊：標準答案取自移植前的原實作
  - 教科書 RSA 簽章：用公鑰還原後要是 00 01 FF…FF 00 + 雜湊
  - 裝置金鑰 AES 加解密來回
  - 解密：自己做一本 ADEPT 加密的 EPUB（含一個不壓縮的檔、一個字型混淆項目），解開後要和原文逐 byte 相同
  - ACSM 解析與產出檔名
"""
import base64, os, sys, tempfile, zipfile, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lxml import etree
from Crypto import Random
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from epubtrans.source.fetch_acsm import adept_protocol as P, custom_rsa, decrypt_epub, fetched_epub_name, read_acsm

RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + ("" if cond or not detail else f"\n        {detail}"))


def test_hash_node():
    xml = ('<adept:fulfill xmlns:adept="http://ns.adobe.com/adept" b="2" a="1">'
           '<adept:user>urn:uuid:00000000-0000-0000-0000-000000000000</adept:user>'
           '<adept:note>  書名 House of Debt  </adept:note>'
           '<adept:hmac>ignored</adept:hmac>'
           '<adept:signature>ignored</adept:signature>'
           '</adept:fulfill>')
    got = P.hash_node(etree.fromstring(xml)).hexdigest()
    # 移植前的 libadobe.hash_node 對同一份 XML 算出的值
    check("XML 雜湊與原實作相同（屬性排序、去頭尾空白、略過 hmac／signature）",
          got == "8af432700d66780ef837a5175efe448deb739b9b", got)


def test_signature():
    key = RSA.generate(1024)
    digest = bytes(range(20))
    sig = custom_rsa.encrypt_for_adobe_signature(key.exportKey("DER", pkcs=8), digest)
    recovered = pow(int.from_bytes(sig, "big"), key.e, key.n).to_bytes(128, "big")
    check("簽章用公鑰還原成 00 01 FF…FF 00 + 雜湊（不含 DigestInfo）",
          recovered == b"\x00\x01" + b"\xff" * (128 - 23) + b"\x00" + digest)


def test_device_key(tmp):
    P.set_account_dir(tmp)
    P.create_devkey_file()
    for n in (0, 5, 16, 33):
        data = Random.get_random_bytes(n)
        if P.decrypt_with_device_key(P.encrypt_with_device_key(data)) != data:
            check(f"裝置金鑰加解密來回（{n} bytes）", False)
            return
    check("裝置金鑰加解密來回（含剛好整除 16 的長度）", True)


def _encrypt(bookkey, data, compress=True):
    if compress:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        data = c.compress(data) + c.flush()
    pad = 16 - len(data) % 16
    iv = Random.get_random_bytes(16)
    return iv + AES.new(bookkey, AES.MODE_CBC, iv).encrypt(data + bytes([pad]) * pad)


def _make_adept_epub(path, key, files):
    bookkey = Random.get_random_bytes(16)
    enc_items = []
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        for name, (data, mode) in files.items():
            if mode == "adobe":
                z.writestr(name, _encrypt(bookkey, data))
                enc_items.append((name, "http://www.w3.org/2001/04/xmlenc#aes128-cbc"))
            elif mode == "adobe-raw":
                z.writestr(name, _encrypt(bookkey, data, compress=False))
                enc_items.append((name, "http://ns.adobe.com/adept/xmlenc#aes128-cbc-uncompressed"))
            else:
                z.writestr(name, data)
                if mode == "font":
                    enc_items.append((name, "http://www.idpf.org/2008/embedding"))
        enc = '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" ' \
              'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        for name, alg in enc_items:
            enc += (f'<enc:EncryptedData><enc:EncryptionMethod Algorithm="{alg}"/>'
                    f'<enc:CipherData><enc:CipherReference URI="{name}"/></enc:CipherData></enc:EncryptedData>')
        z.writestr("META-INF/encryption.xml", enc + "</encryption>")
        ek = base64.b64encode(PKCS1_v1_5.new(key.publickey()).encrypt(bookkey)).decode()
        z.writestr("META-INF/rights.xml", '<adept:rights xmlns:adept="http://ns.adobe.com/adept">'
                   f'<adept:licenseToken><adept:encryptedKey>{ek}</adept:encryptedKey>'
                   '</adept:licenseToken></adept:rights>')


def test_decrypt(tmp):
    key = RSA.generate(1024)
    chapter = ("<html><body>" + "<p>House of Debt 第一章，內容要夠長才壓縮得動。</p>" * 200 + "</body></html>").encode()
    image = Random.get_random_bytes(3000)
    font = b"obfuscated-font-bytes"
    files = {"OEBPS/content.opf": (b"<package/>", "plain"),
             "OEBPS/ch1.xhtml": (chapter, "adobe"),
             "OEBPS/img.jpg": (image, "adobe-raw"),
             "OEBPS/font.otf": (font, "font")}
    src, out = os.path.join(tmp, "enc.epub"), os.path.join(tmp, "dec.epub")
    _make_adept_epub(src, key, files)
    check("自製的加密 EPUB 被判定為 ADEPT 加密", decrypt_epub.is_encrypted(src))

    status, msg = decrypt_epub.decrypt_book(key.exportKey("DER"), src, out)
    check("解密回傳成功", status == 0, msg)
    z = zipfile.ZipFile(out)
    check("mimetype 排第一且不壓縮",
          z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED)
    check("壓縮過的加密檔解回原文", z.read("OEBPS/ch1.xhtml") == chapter)
    check("不壓縮的加密檔（aes128-cbc-uncompressed）解回原文", z.read("OEBPS/img.jpg") == image)
    check("rights.xml 移除", "META-INF/rights.xml" not in z.namelist())
    enc = z.read("META-INF/encryption.xml").decode() if "META-INF/encryption.xml" in z.namelist() else ""
    check("encryption.xml 只留字型混淆項目", "font.otf" in enc and "ch1.xhtml" not in enc and "img.jpg" not in enc)

    status, _ = decrypt_epub.decrypt_book(RSA.generate(1024).exportKey("DER"), src, out)
    check("用別組私鑰解密會失敗而不是產出亂碼", status == 2)


def test_read_acsm(tmp):
    p = os.path.join(tmp, "URLLink.acsm")
    with open(p, "w") as f:
        f.write('<fulfillmentToken fulfillmentType="buy" auth="user" xmlns="http://ns.adobe.com/adept">'
                '<operatorURL>https://acs4.example.com/fulfillment</operatorURL>'
                '<expiration>2026-09-28T21:24:10+00:00</expiration>'
                '<resourceItemInfo><metadata>'
                '<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">And/Or: A Novel</dc:title>'
                '<dc:format xmlns:dc="http://purl.org/dc/elements/1.1/">application/epub+zip</dc:format>'
                '</metadata></resourceItemInfo></fulfillmentToken>')
    info = read_acsm(p)
    check("讀出 ACSM 的書名、格式、書商、期限",
          info["title"] == "And/Or: A Novel" and info["format"] == "application/epub+zip"
          and info["operator"] == "https://acs4.example.com/fulfillment"
          and info["expiration"].isoformat() == "2026-09-28T21:24:10+00:00", str(info))
    check("產出檔名依書名、不用 URLLink，且換掉檔名不能用的字元",
          fetched_epub_name(p) == "And／Or： A Novel.epub", fetched_epub_name(p))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_hash_node()
        test_signature()
        test_device_key(tmp)
        test_decrypt(tmp)
        test_read_acsm(tmp)
    ok, total = sum(RESULTS), len(RESULTS)
    print(f"\n{ok}/{total} 通過")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
