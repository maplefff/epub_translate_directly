"""ACSM → 解密後的 EPUB（python -m epubtrans fetch "書名" [ACSM 路徑]）。

.acsm 只是一張領書憑證（XML），不是書本身。流程：
  讀 ACSM（書名、格式、期限）→ 向書商的 Adobe Content Server 領書 → 下載 ADEPT 加密的 EPUB
  → 補上 rights.xml → 用這台裝置的 Adobe 授權解密 → process/書名/{原書名}.epub

之後 extract 會自動改讀這份 EPUB，其餘流程與一般 EPUB 相同。

領書會連線到書商與 Adobe 的伺服器，而且一張 ACSM 通常只能被一組 Adobe ID 領取，所以獨立成
fetch 指令，extract 不會自動觸發。已經領過（書本目錄裡已有解密後的 EPUB）就直接跳過。

Adobe 授權檔（device.xml、activation.xml、devicesalt）放在專案根目錄的 adept/，不進版控：
解密用的私鑰就在裡面，刪掉只能重新註冊一組新 ID，舊 ID 領過的書就再也領不回來。
不要把這三個檔的內容貼到任何地方。

去 DRM 只限自己購買的書、自己閱讀，不要散布。

這個套件的程式碼移植自以 GPLv3 釋出的 acsm-calibre-plugin（Leseratte10）與 DeDRM_tools
（Apprentice Harper et al.），授權條款見同目錄的 COPYING；出處寫在各檔開頭。
"""
import os, shutil, zipfile
from copy import deepcopy
from datetime import datetime, timezone
from lxml import etree
from ...core.config import ADEPT_DIR, safe_filename
from . import adept_account, adept_fulfill, decrypt_epub
from . import adept_protocol as P
from .adept_protocol import AdeptError, ad

DC = "http://purl.org/dc/elements/1.1/"
FORMATS = {"application/epub+zip": "EPUB", "application/pdf": "PDF"}


def read_acsm(path):
    """ACSM 的書目資訊：title、author、format（MIME）、expiration（UTC datetime 或 None）、operator。"""
    try:
        x = etree.parse(path)
    except (OSError, etree.XMLSyntaxError) as e:
        raise SystemExit(f"讀不了 ACSM：{path}（{e}）")
    if etree.QName(x.getroot()).localname != "fulfillmentToken":
        raise SystemExit(f"這不是 ACSM 領書憑證：{path}")
    meta = "./%s/%s/{%s}%%s" % (ad("resourceItemInfo"), ad("metadata"), DC)
    exp = (x.findtext(ad("expiration")) or "").strip()
    try:
        exp = datetime.fromisoformat(exp.replace("Z", "+00:00")) if exp else None
    except ValueError:
        exp = None
    return {"title": (x.findtext(meta % "title") or "").strip(),
            "author": (x.findtext(meta % "creator") or "").strip(),
            "format": (x.findtext(meta % "format") or "").strip(),
            "expiration": exp,
            "operator": (x.findtext(ad("operatorURL")) or "").strip()}


def fetched_epub_name(acsm_path):
    """fetch 產出的 EPUB 檔名：依 ACSM 裡的書名，不用 ACSM 自己的檔名（書商多半叫 URLLink.acsm）。"""
    title = read_acsm(acsm_path)["title"] or os.path.splitext(os.path.basename(acsm_path))[0]
    return safe_filename(title) + ".epub"


def _use_account():
    P.set_account_dir(ADEPT_DIR)
    if not os.path.exists(P.activation_path()):
        raise SystemExit(f"找不到 Adobe 授權：{P.activation_path()}\n"
                         f"把既有的 device.xml、activation.xml、devicesalt 放進 {ADEPT_DIR}，"
                         f"或由使用者自己執行 `python -m epubtrans acsm-register` 註冊一組匿名 ID。")


def _locate_acsm(cfg, acsm_path):
    if acsm_path:
        src = os.path.abspath(os.path.expanduser(acsm_path))
        info = read_acsm(src)
        dest = os.path.join(cfg.dir, safe_filename(info["title"] or cfg.name) + ".acsm")
        if os.path.abspath(dest) != src:
            if os.path.exists(dest):
                print(f"以新的 ACSM 覆蓋 {os.path.basename(dest)}")
            shutil.copyfile(src, dest)
        return dest
    f = cfg.book.get("source_file") or ""
    if f.lower().endswith(".acsm"):
        return os.path.join(cfg.dir, f)
    cands = [x for x in sorted(os.listdir(cfg.dir)) if x.lower().endswith(".acsm")]
    if len(cands) == 1:
        return os.path.join(cfg.dir, cands[0])
    raise SystemExit(f"書本目錄裡有 {len(cands)} 個 .acsm；請給 ACSM 路徑，"
                     f"或在 system_prompts.yaml 的 book.source_file 指定。")


def run(cfg, acsm_path=None, force=False):
    acsm = _locate_acsm(cfg, acsm_path)
    info = read_acsm(acsm)
    exp = info["expiration"]
    print(f"書名：{info['title'] or '?'}　作者：{info['author'] or '?'}")
    print(f"格式：{FORMATS.get(info['format'], info['format'] or '?')}　書商：{info['operator'] or '?'}")
    if exp:
        left = (exp - datetime.now(timezone.utc)).total_seconds()
        state = f"剩 {int(left // 3600)} 小時 {int(left % 3600 // 60)} 分" if left > 0 else "已過期"
        print(f"ACSM 期限：{exp.astimezone():%Y-%m-%d %H:%M}（本地時間，{state}）")

    out = os.path.join(cfg.dir, fetched_epub_name(acsm))
    if os.path.exists(out):
        print(f"已經領過：{out}\n要重領就先刪掉這個檔案。")
        return out
    if info["format"] == "application/pdf":
        raise SystemExit("這張 ACSM 領的是 PDF。目前只支援 EPUB 格式的 ACSM（ADEPT 加密的 PDF 無法解密）。")
    if exp and exp <= datetime.now(timezone.utc) and not force:
        raise SystemExit("ACSM 已過期，伺服器多半會拒絕。請回書商網站重新下載一張 ACSM"
                         "（加 --force 可以硬試一次）。")
    _use_account()

    work = cfg.wpath("acsm")
    os.makedirs(work, exist_ok=True)
    stem = os.path.splitext(os.path.basename(out))[0]
    encrypted = os.path.join(work, stem + "_encrypted.epub")
    decrypted = os.path.join(work, stem + "_decrypted.epub")
    try:
        print("向書商領書…")
        reply = adept_fulfill.fulfill(acsm)
        result = etree.fromstring(reply.encode("utf-8")).find(ad("fulfillmentResult"))
        url = result.findtext("./%s/%s" % (ad("resourceItemInfo"), ad("src")))
        if not url:
            raise AdeptError("領書回應裡沒有下載網址")
        print("下載加密的 EPUB…")
        P.download(url, encrypted)
        _inject_rights(encrypted, result)
        print("解密…")
        status, msg = decrypt_epub.decrypt_book(adept_account.private_license_key_der(), encrypted, decrypted)
    except AdeptError as e:
        raise SystemExit(f"領書失敗：{e}\n{_hint(str(e))}")
    if status == 2:
        raise SystemExit(f"解密失敗：{msg}\n加密檔保留在 {encrypted}")
    if status == 1:
        print("這本書本來就沒有 DRM。")
        shutil.copyfile(encrypted, decrypted)
    os.replace(decrypted, out)
    os.remove(encrypted)

    with zipfile.ZipFile(out) as z:
        left = [n for n in z.namelist() if n == "META-INF/encryption.xml"]
    print(f"寫入 {out}（{os.path.getsize(out) / 1024 / 1024:.1f} MB）")
    if left:
        print("※ 仍有 encryption.xml：只剩字型混淆之類的非 DRM 項目，閱讀器照常能開。")
    return out


def _inject_rights(path, result):
    """下載回來的 EPUB 通常沒有 META-INF/rights.xml（ADE 會自己補），解密要用裡面的 encryptedKey。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    if "META-INF/container.xml" not in names:
        raise AdeptError("下載到的檔案不是 EPUB（缺 META-INF/container.xml）")
    if "META-INF/rights.xml" in names:
        return
    token = result.find("./%s/%s" % (ad("resourceItemInfo"), ad("licenseToken")))
    if token is None:
        raise AdeptError("領書回應裡沒有 licenseToken")
    rights = etree.Element(ad("rights"), nsmap=P.NSMAP)
    rights.append(deepcopy(token))
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("META-INF/rights.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                   + etree.tostring(rights, encoding="utf-8", pretty_print=True).decode("utf-8"))


HINTS = {
    "E_ADEPT_REQUEST_EXPIRED": "ACSM 已過期：請回書商網站重新下載一張。",
    "E_LIC_ALREADY_FULFILLED_BY_ANOTHER_USER": "這張 ACSM 已被別的 Adobe ID 領過，這組授權領不了。",
    "E_GOOGLE_DEVICE_LIMIT_REACHED": "書商的裝置數量已滿：請到書商網站移除舊裝置。",
    "E_ACT_TOO_MANY_ACTIVATIONS": "這組 Adobe ID 啟用的裝置太多。",
}


def _hint(msg):
    return next((h for k, h in HINTS.items() if k in msg), "")


def register():
    """註冊一組匿名 Adobe ID（ADE 3.0）。會在 Adobe 伺服器上建立帳號，只能由使用者自己執行。"""
    P.set_account_dir(ADEPT_DIR)
    if os.path.exists(P.activation_path()):
        raise SystemExit(f"{ADEPT_DIR} 已經有授權，不重新註冊（重新註冊會讓舊 ID 領過的書領不回來）。")
    os.makedirs(ADEPT_DIR, exist_ok=True)
    try:
        adept_account.register_anonymous()
    except AdeptError as e:
        raise SystemExit(f"註冊失敗：{e}")
    print(f"註冊完成：{adept_account.user_uuid()}\n授權檔在 {ADEPT_DIR}（不要刪除，也不要外流）")
