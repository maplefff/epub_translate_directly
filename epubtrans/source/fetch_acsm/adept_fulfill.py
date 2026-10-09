"""向書商的 Adobe Content Server 領書：簽署 fulfill 請求、必要時先向書商驗證、取回授權服務憑證。

移植自 acsm-calibre-plugin 的 libadobeFulfill.py（GPLv3）。
Copyright (c) 2021-2023 Leseratte10 — https://github.com/Leseratte10/acsm-calibre-plugin
改動：拿掉借閱歸還與領書通知（原本的 acsm-to-epub 預設就不通知）、ADE 1.7.2 的舊格式請求、
calibre 設定檔；錯誤一律丟 AdeptError。
"""
import base64
from lxml import etree
from . import adept_protocol as P
from .adept_protocol import AdeptError, ad

DC = "http://purl.org/dc/elements/1.1/"


def _activation():
    return etree.parse(P.activation_path())


def _text(tree, *tags):
    node = tree.find("./" + "/".join(ad(t) for t in tags))
    return None if node is None else node.text


def build_fulfill_request(acsm):
    act = etree.parse(P.activation_path())
    dev = etree.parse(P.device_path())
    user = _text(act, "credentials", "user")
    device = _text(act, "activationToken", "device")
    fingerprint = _text(act, "activationToken", "fingerprint")
    device_type = _text(act, "activationToken", "deviceType")
    if not fingerprint or not device_type:
        # 正常的授權不會缺；缺了就退回 device.xml 的值
        fingerprint, device_type = dev.findtext(ad("fingerprint")), dev.findtext(ad("deviceType"))

    ver = {v.get("name"): v.get("value") for v in dev.findall(ad("version"))}
    version = ver.get("hobbes")
    try:
        client_version = P.VER_SUPP_VERSIONS[P.VER_HOBBES_VERSIONS.index(version)]
    except ValueError:
        client_version = "3.0.1.91394"      # 舊版 10.0.4 之類不在清單上，都屬於 ADE 3.0
    if client_version == "ADE WIN 9,0,1131,27":
        raise AdeptError("不支援以 ADE 1.7.2 身分領書")

    r = '<?xml version="1.0"?>'
    r += '<adept:fulfill xmlns:adept="http://ns.adobe.com/adept">'
    r += "<adept:user>%s</adept:user>" % user
    r += "<adept:device>%s</adept:device>" % device
    r += "<adept:deviceType>%s</adept:deviceType>" % device_type
    r += etree.tostring(acsm, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")
    r += "<adept:targetDevice>"
    r += "<adept:softwareVersion>%s</adept:softwareVersion>" % version
    r += "<adept:clientOS>%s</adept:clientOS>" % ver.get("clientOS")
    r += "<adept:clientLocale>%s</adept:clientLocale>" % ver.get("clientLocale")
    r += "<adept:clientVersion>%s</adept:clientVersion>" % client_version
    r += "<adept:deviceType>%s</adept:deviceType>" % device_type
    r += "<adept:productName>%s</adept:productName>" % "ADOBE Digitial Editions"   # ADE 本身就拼錯
    r += "<adept:fingerprint>%s</adept:fingerprint>" % fingerprint
    r += "<adept:activationToken>"
    r += "<adept:user>%s</adept:user>" % user
    r += "<adept:device>%s</adept:device>" % device
    r += "</adept:activationToken>"
    r += "</adept:targetDevice>"
    r += "</adept:fulfill>"
    return r


def _signed(xml_str):
    node = etree.fromstring(xml_str)
    etree.SubElement(node, etree.QName(P.NS, "signature")).text = P.sign_node(node)
    return '<?xml version="1.0"?>\n' + etree.tostring(
        node, encoding="utf-8", pretty_print=True, xml_declaration=False).decode("utf-8")


def build_init_license_service_request(auth_url):
    r = '<?xml version="1.0"?>'
    r += '<adept:licenseServiceRequest xmlns:adept="http://ns.adobe.com/adept" identity="user">'
    r += "<adept:operatorURL>%s</adept:operatorURL>" % auth_url
    r += P.add_nonce()
    r += "<adept:user>%s</adept:user>" % _text(_activation(), "credentials", "user")
    r += "</adept:licenseServiceRequest>"
    return _signed(r)


def decrypted_cert():
    p12 = base64.b64decode(_text(_activation(), "credentials", "pkcs12"))
    return P.cert_from_pkcs12(p12, base64.b64encode(P.devkey()))


def build_auth_request():
    act = _activation()
    r = '<?xml version="1.0"?>\n'
    r += '<adept:credentials xmlns:adept="http://ns.adobe.com/adept">\n'
    r += "<adept:user>%s</adept:user>\n" % _text(act, "credentials", "user")
    r += "<adept:certificate>%s</adept:certificate>\n" % base64.b64encode(decrypted_cert()).decode("utf-8")
    r += "<adept:licenseCertificate>%s</adept:licenseCertificate>\n" % _text(act, "credentials", "licenseCertificate")
    r += "<adept:authenticationCertificate>%s</adept:authenticationCertificate>\n" % \
        _text(act, "credentials", "authenticationCertificate")
    r += "</adept:credentials>"
    return r


def do_operator_auth(operator_url):
    auth_url = operator_url
    if auth_url.endswith("Fulfill"):
        auth_url = auth_url.replace("/Fulfill", "")
    reply = P.post_adept(auth_url + "/Auth", build_auth_request())
    if "<success" not in reply:
        raise AdeptError("書商驗證失敗：" + reply[:500])
    activation_url = _text(_activation(), "activationToken", "activationURL")
    resp = P.post_adept(activation_url + "/InitLicenseService", build_init_license_service_request(auth_url))
    if "<success" not in resp:
        raise AdeptError("InitLicenseService 失敗：" + resp[:500])


def operator_auth(operator_url):
    """這個書商沒驗證過才驗證，驗證後記進 activation.xml 的 operatorURLList。"""
    act = _activation()
    for m in act.findall("./%s/%s" % (ad("operatorURLList"), ad("operatorURL"))):
        if (m.text or "").strip() == operator_url:
            return
    do_operator_auth(operator_url)
    lst = act.find(ad("operatorURLList"))
    if lst is None:
        lst = etree.SubElement(act.getroot(), etree.QName(P.NS, "operatorURLList"), nsmap=P.NSMAP)
        etree.SubElement(lst, etree.QName(P.NS, "user")).text = _text(act, "credentials", "user")
    etree.SubElement(lst, etree.QName(P.NS, "operatorURL")).text = operator_url
    P.write_xml(P.activation_path(), act.getroot())


def fetch_license_service_certificate(license_url, operator_url):
    act = _activation()
    for m in act.findall("./%s/%s" % (ad("licenseServices"), ad("licenseServiceInfo"))):
        if m.findtext(ad("licenseURL")) == license_url:
            return
    resp = P.http_get(operator_url + "/LicenseServiceInfo?licenseURL=" + license_url).decode("utf-8")
    if "<licenseServiceInfo" not in resp or "<error" in resp:
        raise AdeptError("取得授權服務憑證失敗：" + resp[:500])
    x = etree.fromstring(resp.encode("utf-8"))
    lst = act.find(ad("licenseServices"))
    if lst is None:
        lst = etree.SubElement(act.getroot(), etree.QName(P.NS, "licenseServices"), nsmap=P.NSMAP)
    info = etree.SubElement(lst, etree.QName(P.NS, "licenseServiceInfo"))
    etree.SubElement(info, etree.QName(P.NS, "licenseURL")).text = x.findtext(ad("licenseURL"))
    etree.SubElement(info, etree.QName(P.NS, "certificate")).text = x.findtext(ad("certificate"))
    P.write_xml(P.activation_path(), act.getroot())


def fulfill(acsm_path):
    """送出領書請求，回傳伺服器的 fulfillmentResult（XML 字串）。"""
    if not _text(_activation(), "credentials", "pkcs12"):
        raise AdeptError("activation.xml 缺少授權資料")
    acsm = etree.parse(acsm_path)
    operator_url = (acsm.findtext(ad("operatorURL")) or "").strip()
    if not operator_url:
        raise AdeptError("ACSM 裡沒有 operatorURL")

    request = _signed(build_fulfill_request(acsm))
    fulfill_url = operator_url + "/Fulfill"
    operator_auth(fulfill_url)
    reply = P.post_adept(fulfill_url, request)
    if "<error" in reply and "E_ADEPT_DISTRIBUTOR_AUTH" in reply:
        do_operator_auth(fulfill_url)       # 有些書商每次都要重新驗證
        reply = P.post_adept(fulfill_url, request)
    if "<error" in reply:
        raise AdeptError("領書失敗：" + reply[:1000])

    result = etree.fromstring(reply.encode("utf-8"))
    license_url = result.findtext("./" + "/".join(ad(t) for t in (
        "fulfillmentResult", "resourceItemInfo", "licenseToken", "licenseURL")))
    fetch_license_service_certificate(license_url, operator_url)
    return reply
