"""向 Adobe 註冊一組匿名 ID 並啟用這台「裝置」：建裝置檔 → 建使用者 → 匿名登入 → 啟用。

只在授權目錄是空的時候用得到；這會在 Adobe 伺服器上建立一個匿名帳號，
所以只能由使用者自己執行（python -m epubtrans acsm-register）。

移植自 acsm-calibre-plugin 的 libadobeAccount.py 與 register_ADE_account.py（GPLv3）。
Copyright (c) 2021-2023 Leseratte10 — https://github.com/Leseratte10/acsm-calibre-plugin
改動：只留匿名註冊需要的部分，拿掉 AdobeID 登入、匿名轉 AdobeID、代理裝置、切換 ADE 版本；
不再用 input() 詢問。
"""
import base64, locale, platform, struct
from lxml import etree
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.asn1 import DerSequence
from . import adept_protocol as P
from .adept_protocol import AdeptError, ad


def _check_version(i):
    if not 0 <= i < len(P.VER_CONFIG_NAMES) or P.VER_BUILD_IDS[i] not in P.VER_ALLOWED_BUILD_IDS_AUTHORIZE:
        raise AdeptError(f"這個 ADE 版本不能用來註冊：{i}")


def _use_https(i):
    return P.VER_BUILD_IDS[i] >= P.VER_NEED_HTTPS_BUILD_ID_LIMIT


def create_device_file(i):
    _check_version(i)
    serial = P.make_serial()
    root = etree.Element(etree.QName(P.NS, "deviceInfo"))
    etree.SubElement(root, etree.QName(P.NS, "deviceType")).text = "standalone"
    # 下面三個不會送給 Adobe
    etree.SubElement(root, etree.QName(P.NS, "deviceClass")).text = "Desktop"
    etree.SubElement(root, etree.QName(P.NS, "deviceSerial")).text = serial
    etree.SubElement(root, etree.QName(P.NS, "deviceName")).text = platform.uname()[1]
    for name, value in (("hobbes", P.VER_HOBBES_VERSIONS[i]),
                        # 不回報真實作業系統，免得 Adobe 看到一堆 Linux／macOS 的請求
                        ("clientOS", P.VER_OS_IDENTIFIERS[i]),
                        ("clientLocale", _language())):
        v = etree.SubElement(root, etree.QName(P.NS, "version"))
        v.set("name", name)
        v.set("value", value)
    etree.SubElement(root, etree.QName(P.NS, "fingerprint")).text = P.make_fingerprint(serial)
    P.write_xml(P.device_path(), root)


def _language():
    try:
        lang = (locale.getlocale()[0] or "").split("_")[0]
    except Exception:
        lang = ""
    return lang or "en"


def create_user(i):
    root = etree.Element("activationInfo")
    root.set("xmlns", P.NS)
    info = etree.SubElement(root, etree.QName(P.NS, "activationServiceInfo"))
    base = P.ACS_SERVER_HTTPS if _use_https(i) else P.ACS_SERVER_HTTP
    resp = etree.fromstring(P.http_get(base + "/ActivationServiceInfo"))
    auth_url = resp.findtext(ad("authURL"))
    user_info_url = resp.findtext(ad("userInfoURL"))
    certificate = resp.findtext(ad("certificate"))
    if auth_url is None or user_info_url is None or certificate is None:
        raise AdeptError("Adobe 的 ActivationServiceInfo 回應格式不符")
    etree.SubElement(info, etree.QName(P.NS, "authURL")).text = auth_url
    etree.SubElement(info, etree.QName(P.NS, "userInfoURL")).text = user_info_url
    etree.SubElement(info, etree.QName(P.NS, "activationURL")).text = base
    etree.SubElement(info, etree.QName(P.NS, "certificate")).text = certificate
    resp2 = etree.fromstring(P.http_get(auth_url + "/AuthenticationServiceInfo"))
    etree.SubElement(info, etree.QName(P.NS, "authenticationCertificate")).text = resp2.findtext(ad("certificate"))
    P.write_xml(P.activation_path(), root)


def _encrypt_login(username, password, auth_cert_b64):
    """<裝置金鑰><帳號長度><帳號><密碼長度><密碼>，用 Adobe 驗證憑證的公鑰加密。匿名時帳密皆空。"""
    buf = bytearray(P.devkey())
    for s in (username, password):
        b = s.encode("utf-8")
        buf += struct.pack("B", len(b)) + b
    cert = DerSequence()
    cert.decode(base64.b64decode(auth_cert_b64))
    tbs = DerSequence()
    tbs.decode(cert[0])
    return PKCS1_v1_5.new(RSA.importKey(tbs[6])).encrypt(bytes(buf))


def _sign_in_request(auth_cert_b64):
    root = etree.Element(etree.QName(P.NS, "signIn"))
    root.set("method", "anonymous")
    etree.SubElement(root, etree.QName(P.NS, "signInData")).text = \
        base64.b64encode(_encrypt_login("", "", auth_cert_b64))
    for pub_tag, priv_tag in (("publicAuthKey", "encryptedPrivateAuthKey"),
                              ("publicLicenseKey", "encryptedPrivateLicenseKey")):
        key = RSA.generate(1024, e=65537)
        etree.SubElement(root, etree.QName(P.NS, pub_tag)).text = \
            base64.b64encode(key.publickey().exportKey("DER"))
        etree.SubElement(root, etree.QName(P.NS, priv_tag)).text = \
            base64.b64encode(P.encrypt_with_device_key(key.exportKey("DER", pkcs=8)))
    return '<?xml version="1.0"?>\n' + etree.tostring(
        root, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")


def sign_in_anonymous():
    act = etree.parse(P.activation_path())
    info = "./%s/%s" % (ad("activationServiceInfo"), "%s")
    auth_cert = act.find(info % ad("authenticationCertificate")).text
    url = act.find(info % ad("authURL")).text + "/SignInDirect"
    reply = P.post_adept(url, _sign_in_request(auth_cert))
    try:
        cred = etree.fromstring(reply.encode("utf-8"))
    except etree.XMLSyntaxError:
        raise AdeptError("登入回應無法解析：" + reply[:300]) from None
    if cred.tag == ad("error"):
        raise AdeptError("Adobe 拒絕登入：" + (cred.get("data") or reply))
    if cred.tag != ad("credentials"):
        raise AdeptError("登入回應的根節點不對：" + cred.tag)

    private_key = P.decrypt_with_device_key(base64.b64decode(cred.findtext(ad("encryptedPrivateLicenseKey"))))
    # 原實作就是用字串接出 credentials 節點（etree 處理這裡的 namespace 很彆扭），照做以保持格式一致
    old = etree.tostring(act, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")
    with open(P.activation_path(), "w") as f:
        f.write('<?xml version="1.0"?>\n')
        f.write(old.replace("</activationInfo>", ""))
        f.write('<adept:credentials xmlns:adept="http://ns.adobe.com/adept">\n')
        f.write("<adept:user>%s</adept:user>\n" % cred.findtext(ad("user")))
        f.write("<adept:pkcs12>%s</adept:pkcs12>\n" % cred.findtext(ad("pkcs12")))
        f.write("<adept:licenseCertificate>%s</adept:licenseCertificate>\n" % cred.findtext(ad("licenseCertificate")))
        f.write("<adept:privateLicenseKey>%s</adept:privateLicenseKey>\n" % base64.b64encode(private_key).decode("latin-1"))
        f.write("<adept:authenticationCertificate>%s</adept:authenticationCertificate>\n" % auth_cert)
        f.write("</adept:credentials>\n")
        f.write("</activationInfo>\n")


def _activate_request(i):
    dev = etree.parse(P.device_path())
    act = etree.parse(P.activation_path())
    ver = {v.get("name"): v.get("value") for v in dev.findall(ad("version"))}
    if not all(ver.get(k) for k in ("hobbes", "clientOS", "clientLocale")):
        raise AdeptError("device.xml 缺少版本資訊")
    fp, dtype = dev.findtext(ad("fingerprint")), dev.findtext(ad("deviceType"))
    r = '<?xml version="1.0"?>'
    r += '<adept:activate xmlns:adept="http://ns.adobe.com/adept" requestType="initial">'
    r += "<adept:fingerprint>%s</adept:fingerprint>" % fp
    r += "<adept:deviceType>%s</adept:deviceType>" % dtype
    r += "<adept:clientOS>%s</adept:clientOS>" % ver["clientOS"]
    r += "<adept:clientLocale>%s</adept:clientLocale>" % ver["clientLocale"]
    r += "<adept:clientVersion>%s</adept:clientVersion>" % P.VER_SUPP_VERSIONS[i]
    r += "<adept:targetDevice>"
    r += "<adept:softwareVersion>%s</adept:softwareVersion>" % ver["hobbes"]
    r += "<adept:clientOS>%s</adept:clientOS>" % ver["clientOS"]
    r += "<adept:clientLocale>%s</adept:clientLocale>" % ver["clientLocale"]
    r += "<adept:clientVersion>%s</adept:clientVersion>" % P.VER_SUPP_VERSIONS[i]
    r += "<adept:deviceType>%s</adept:deviceType>" % dtype
    r += "<adept:productName>%s</adept:productName>" % "ADOBE Digitial Editions"   # ADE 本身就拼錯
    r += "<adept:fingerprint>%s</adept:fingerprint>" % fp
    r += "</adept:targetDevice>"
    r += P.add_nonce()
    r += "<adept:user>%s</adept:user>" % act.find("./%s/%s" % (ad("credentials"), ad("user"))).text
    r += "</adept:activate>"
    return r


def activate_device(i):
    _check_version(i)
    req = etree.fromstring(_activate_request(i))
    etree.SubElement(req, etree.QName(P.NS, "signature")).text = P.sign_node(req)
    data = '<?xml version="1.0"?>\n' + etree.tostring(
        req, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")
    base = P.ACS_SERVER_HTTPS if _use_https(i) else P.ACS_SERVER_HTTP
    reply = P.post_adept(base + "/Activate", data)
    try:
        token = etree.fromstring(reply.encode("utf-8"))
    except etree.XMLSyntaxError:
        raise AdeptError("啟用回應無法解析：" + reply[:300]) from None
    if token.tag == ad("error"):
        raise AdeptError("Adobe 拒絕啟用：" + (token.get("data") or reply))
    if token.tag != ad("activationToken"):
        raise AdeptError("啟用回應的根節點不對：" + token.tag)
    with open(P.activation_path()) as f:
        old = f.read().replace("</activationInfo>", "")
    with open(P.activation_path(), "w") as f:
        f.write(old)
        f.write(reply)
        f.write("</activationInfo>\n")


def register_anonymous(i=P.DEFAULT_VERSION_INDEX):
    _check_version(i)
    P.create_devkey_file()
    create_device_file(i)
    create_user(i)
    sign_in_anonymous()
    activate_device(i)


def private_license_key_der():
    """解密書本金鑰用的 RSA 私鑰（DER）。activation.xml 存的值前 26 bytes 是檔頭。"""
    act = etree.parse(P.activation_path())
    node = act.find("./%s/%s" % (ad("credentials"), ad("privateLicenseKey")))
    if node is None or not (node.text or "").strip():
        raise AdeptError("activation.xml 缺少 privateLicenseKey")
    return base64.b64decode(node.text)[26:]


def user_uuid():
    act = etree.parse(P.activation_path())
    return act.findtext("./%s/%s" % (ad("credentials"), ad("user")))
