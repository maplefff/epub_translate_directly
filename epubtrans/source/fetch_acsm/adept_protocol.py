"""Adobe ADEPT 協定的共用工具：授權檔路徑、裝置金鑰、HTTP、nonce、XML 雜湊與簽章。

移植自 acsm-calibre-plugin 的 libadobe.py（GPLv3）。
Copyright (c) 2021-2023 Leseratte10 — https://github.com/Leseratte10/acsm-calibre-plugin
改動：
  - 只留 Python 3 的寫法；雜湊改用 hashlib（與 Crypto.Hash.SHA 結果相同）。
  - 授權檔目錄由 set_account_dir() 指定，不再以目前工作目錄為準。
  - PKCS#12 改用 cryptography 解析（原本用 oscrypto）。
  - 固定 TLS 1.2 改用 minimum_version／maximum_version（PROTOCOL_TLSv1_2 已棄用）。
  - HTTP 失敗一律丟 AdeptError，不回傳 None 讓呼叫端在 .decode() 才出錯。
"""
import base64, hashlib, os, ssl, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from lxml import etree
from Crypto import Random
from Crypto.Cipher import AES
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from . import custom_rsa

NS = "http://ns.adobe.com/adept"
NSMAP = {"adept": NS}
ACS_SERVER_HTTP = "http://adeactivate.adobe.com/adept"
ACS_SERVER_HTTPS = "https://adeactivate.adobe.com/adept"

# 模擬的 ADE 版本。五個清單的長度必須相同，索引一一對應。
VER_CONFIG_NAMES = ["ADE 1.7.2", "ADE 2.0.1", "ADE 3.0.1", "ADE 4.0.3", "ADE 4.5.10", "ADE 4.5.11"]
VER_SUPP_VERSIONS = ["ADE WIN 9,0,1131,27", "2.0.1.78765", "3.0.1.91394", "4.0.3.123281",
                     "com.adobe.adobedigitaleditions.exe v4.5.10.186048",
                     "com.adobe.adobedigitaleditions.exe v4.5.11.187303"]
VER_HOBBES_VERSIONS = ["9.0.1131.27", "9.3.58046", "10.0.85385", "12.0.123217", "12.5.4.186049", "12.5.4.187298"]
VER_OS_IDENTIFIERS = ["Windows Vista", "Windows Vista", "Windows 8", "Windows 8", "Windows 8", "Windows 8"]
VER_BUILD_IDS = [1131, 78765, 91394, 123281, 186048, 187303]
VER_ALLOWED_BUILD_IDS_AUTHORIZE = [78765, 91394, 123281, 187303]
VER_NEED_HTTPS_BUILD_ID_LIMIT = 123281      # 這個 build 以上用 HTTPS
DEFAULT_VERSION_INDEX = 2                   # ADE 3.0.1，與原本 acsm_to_epub.sh 註冊時的選擇相同


class AdeptError(Exception):
    pass


def ad(tag):
    return "{%s}%s" % (NS, tag)


# ── 授權檔 ────────────────────────────────────────────────────────────
_account_dir = None
_devkey = None


def set_account_dir(path):
    global _account_dir, _devkey
    _account_dir, _devkey = path, None


def _path(name):
    if _account_dir is None:
        raise AdeptError("尚未指定 Adobe 授權檔目錄（set_account_dir）")
    return os.path.join(_account_dir, name)


def devkey_path():
    return _path("devicesalt")


def device_path():
    return _path("device.xml")


def activation_path():
    return _path("activation.xml")


def devkey():
    global _devkey
    if _devkey is None:
        with open(devkey_path(), "rb") as f:
            _devkey = f.read()
    return _devkey


def create_devkey_file():
    global _devkey
    _devkey = Random.get_random_bytes(16)
    with open(devkey_path(), "wb") as f:
        f.write(_devkey)


def write_xml(path, root):
    """原專案寫 activation.xml／device.xml 的固定格式：宣告一行 + pretty_print。"""
    with open(path, "w") as f:
        f.write('<?xml version="1.0"?>\n')
        f.write(etree.tostring(root, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8"))


def make_serial():
    """隨機序號：一串亂數的 SHA1。Adobe 只看得到它的雜湊，不必模仿 ADE 的算法。"""
    return hashlib.sha1(Random.get_random_bytes(256)).hexdigest().lower()


def make_fingerprint(serial):
    """base64(sha1(serial + 裝置金鑰))"""
    s = serial + devkey().decode("latin-1")
    return base64.b64encode(hashlib.sha1(s.encode("latin-1")).digest()).decode("ascii")


# ── HTTP ─────────────────────────────────────────────────────────────
# 很多書商的憑證過期或無效，ADE 照樣連得上，所以不驗憑證。
# Cloudflare 會擋 TLS 1.3（ADE 不支援），所以固定用 TLS 1.2。
HEADERS = {"Accept": "*/*", "User-Agent": "book2png"}
TIMEOUT = 60


def _ssl_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _open(url, data=None, content_type=None):
    if "://" not in url:
        url = "http://" + url           # 有些書商的網址少了協定
    headers = dict(HEADERS)
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url=url, headers=headers, data=data)
    try:
        return urllib.request.urlopen(req, context=_ssl_ctx(), timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:2000]
        raise AdeptError(f"HTTP {e.code}：{url}\n{body}") from None
    except urllib.error.URLError as e:
        raise AdeptError(f"連線失敗：{url}（{e.reason}）") from None


def http_get(url):
    with _open(url) as r:
        return r.read()


def post_adept(url, document):
    """送出 ADEPT XML 請求，回傳回應文字。"""
    with _open(url, document.encode("utf-8"), "application/vnd.adobe.adept+xml") as r:
        return r.read().decode("utf-8")


def download(url, outpath):
    with _open(url) as r, open(outpath, "wb") as f:
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


# ── 加解密與簽章 ─────────────────────────────────────────────────────
def encrypt_with_device_key(data):
    data = bytes(data)
    pad = 16 - (len(data) % 16)          # 剛好整除時補一整塊 16
    data += bytes([pad]) * pad
    iv = Random.get_random_bytes(16)
    return iv + AES.new(devkey(), AES.MODE_CBC, iv).encrypt(data)


def decrypt_with_device_key(data):
    dec = AES.new(devkey(), AES.MODE_CBC, data[:16]).decrypt(data[16:])
    return dec[:-dec[-1]]


def add_nonce(now=None):
    """nonce＝自西元 1 年起的毫秒數（little-endian 8 bytes）＋ 4 bytes 的 0；有效期 10 分鐘。"""
    dt = now or datetime.now(timezone.utc).replace(tzinfo=None)
    ntime = int((dt - datetime(1970, 1, 1)).total_seconds() * 1000) + 62167219200000
    final = ntime.to_bytes(8, "little") + (0).to_bytes(4, "little")
    exp = (dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ("<adept:nonce>%s</adept:nonce>" % base64.b64encode(final).decode("utf-8")
            + "<adept:expiration>%s</adept:expiration>" % exp)


def _pkcs12_password():
    return base64.b64encode(devkey())


def cert_from_pkcs12(p12, password):
    _, cert, _ = pkcs12.load_key_and_certificates(p12, password)
    return cert.public_bytes(Encoding.DER)


def _signing_key_der():
    act = etree.parse(activation_path())
    node = act.find("./%s/%s" % (ad("credentials"), ad("pkcs12")))
    if node is None or not (node.text or "").strip():
        raise AdeptError("activation.xml 缺少 credentials/pkcs12，授權不完整")
    key, _, _ = pkcs12.load_key_and_certificates(base64.b64decode(node.text), _pkcs12_password())
    return key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())


def sign_node(node):
    digest = hash_node(node).digest()
    block = custom_rsa.encrypt_for_adobe_signature(_signing_key_der(), digest)
    return base64.b64encode(block).decode()


# ── Adobe 的 XML 雜湊 ─────────────────────────────────────────────────
ASN_NS_TAG, ASN_CHILD, ASN_END_TAG, ASN_TEXT, ASN_ATTRIBUTE = 1, 2, 3, 4, 5


def hash_node(node):
    ctx = hashlib.sha1()
    _hash_node(node, ctx)
    return ctx


def _hash_node(node, ctx):
    q = etree.QName(node.tag)
    if q.localname in ("hmac", "signature"):
        if q.namespace == NS:
            return                      # Adobe 的 hmac 與 signature 不納入雜湊
        print("警告：hmac／signature 出現在非預期的 namespace " + str(q.namespace))

    _tag(ctx, ASN_NS_TAG)
    _str(ctx, q.namespace or "")
    _str(ctx, q.localname)

    # 屬性要排序（規格說依 namespace 再依名稱、以 UTF-8 逐 byte 比；這裡沿用原實作的字串排序）
    for attr in sorted(node.keys()):
        qa = etree.QName(attr)
        _tag(ctx, ASN_ATTRIBUTE)
        _str(ctx, qa.namespace or "")
        _str(ctx, qa.localname)
        _str(ctx, node.get(attr))

    _tag(ctx, ASN_CHILD)

    if node.text is not None:
        text = node.text.strip()
        done = 0
        while done < len(text):         # 每段最多 0x7fff 字
            n = min(len(text) - done, 0x7fff)
            _tag(ctx, ASN_TEXT)
            _str(ctx, text[done:done + n])
            done += n

    for child in node:
        _hash_node(child, ctx)

    _tag(ctx, ASN_END_TAG)


def _str(ctx, s):
    b = s.encode("utf-8")
    ctx.update(bytes([len(b) // 256, len(b) & 0xFF]))
    ctx.update(b)


def _tag(ctx, tag):
    if tag <= 5:
        ctx.update(bytes([tag]))
