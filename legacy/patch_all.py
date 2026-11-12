#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_all.py - Комплексный патчер проекта Tool Advisor v8.4.
Выполняет:
  1. Исправление прав администратора в app.py.
  2. Внедрение векторного поиска схожести (TF-IDF + Cosine Similarity) в src/training.py.
  3. Настройку .env и data/llm_config.json под OmniRoute (AUDIT_SAMPLE_RATE=1.0).
  4. Патч src/reviewer.py для 100% использования прокси.
"""
import json
import os
import shutil
import re
import base64

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def step(msg: str) -> None:
    print(f"\n>>> {msg}")

def ok(msg: str) -> None:
    print(f"  [OK] {msg}")

def warn(msg: str) -> None:
    print(f"  [!] {msg}")

def backup_file(path: str) -> None:
    if os.path.exists(path):
        bak_path = path + ".all.bak"
        if not os.path.exists(bak_path):
            shutil.copy2(path, bak_path)
            ok(f"Создана резервная копия: {os.path.relpath(bak_path, ROOT_DIR)}")

def patch_app_py() -> None:
    step("Патч app.py (права администратора)...")
    path = os.path.join(ROOT_DIR, "app.py")
    if not os.path.exists(path):
        warn("app.py не найден, пропуск.")
        return
    backup_file(path)
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    new_admin_ok = """    def _admin_ok(self) -> bool:
        tok = self.headers.get("X-Admin-Token", "")
        if ADMIN_TOKEN:
            return hmac.compare_digest(tok.encode(), ADMIN_TOKEN.encode())
        client_ip = self.client_address[0]
        return (not PUBLIC) and (
            client_ip in ("127.0.0.1", "::1", "localhost")
            or client_ip.startswith("192.168.")
            or client_ip.startswith("10.")
            or client_ip.startswith("172.")
            or client_ip.lower() in ("cdek1", "cdek1.rinscom.com", "desktop", "pc")
        )"""

    if "def _admin_ok(self) -> bool:" in content:
        content = re.sub(r'def _admin_ok\(self\) -> bool:.*?(?=\n    def |\Z)', new_admin_ok + '\n', content, flags=re.S)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok("app.py успешно пропатчен (права админки исправлены)")
    else:
        warn("Метод _admin_ok не найден в app.py")

def patch_training_py() -> None:
    step("Обновление src/training.py (векторный поиск TF-IDF + Cosine Similarity)...")
    path = os.path.join(ROOT_DIR, "src", "training.py")
    if os.path.exists(path):
        backup_file(path)
    
    # Base64 encoded string of the correct training.py to prevent formatting errors
    training_b64 = "IiIiCnNyYy90cmFpbmluZy5weSAtINC+0LHRg9GH0LXQvdC40LUg0L/QsNGA0YHQtdGA0LAg0L3QsCDQv9GA0LjQvNC10YDQsNGFINGC0LXRhdC90L7Qu9C+0LPQsCDRgSDQstC10LrRgtC+0YDQvdGL0Lwg0L/QvtC40YHQutC+0Lwg0YHRhdC+0LbQtdGB0YLQuCAoVEYtSURGIC8gQ29zaW5lIFNpbWlsYXJpdHkpLgoiIiIKaW1wb3J0IGNzdgppbXBvcnQgbWF0aAppbXBvcnQgb3MKaW1wb3J0IHJlCmltcG9ydCB0aHJlYWRpbmcKaW1wb3J0IHRpbWUKZnJvbSB0eXBpbmcgaW1wb3J0IEFueSwgRGljdCwgTGlzdCwgT3B0aW9uYWwKClBBVEggPSBvcy5wYXRoLmpvaW4oImRhdGEiLCAidHJhaW5pbmdfZXhhbXBsZXMuY3N2IikKTUFURVJJQUxTX0NTViA9IG9zLnBhdGguam9pbigiZGF0YSIsICJtYXRlcmlhbHMuY3N2IikKRklFTERTID0gWyJpZCIsICJ0cyIsICJxdWVyeSIsICJxdWVyeV9ub3JtIiwgInBhcnNlcl9pc28iLCAicGFyc2VyX29wZXJhdGlvbiIsICJwYXJzZXJfdG9wX3NrdXMiLAogICAgICAgICAgImNvcnJlY3RfaXNvIiwgImNvcnJlY3Rfb3BlcmF0aW9uIiwgImNvcnJlY3Rfc2t1cyIsICJjb21tZW50IiwgInN0YXR1cyIsICJydWxlc19hZGRlZCJdCklTT19PSyA9IHsiUCIsICJNIiwgIksiLCAiTiIsICJTIiwgIkgifQpPUF9PSyA9IHsiZmluaXNoaW5nIiwgInNlbWlfZmluaXNoaW5nIiwgInJvdWdoaW5nIn0KX0xBVElOMkNZUiA9IHN0ci5tYWtldHJhbnMoImFiY2Voa21vcHR4eSIsICLQsNCy0YHQtdC90LrQvNC+0YDRgtGF0YMiKQpfbG9jayA9IHRocmVhZGluZy5Mb2NrKCkKX2NhY2hlOiBEaWN0W3N0ciwgQW55XSA9IHsibXRpbWUiOiAwLjAsICJyb3dzIjogW119CgpkZWYgbm9ybWFsaXplKHRleHQ6IHN0cikgLT4gc3RyOgogICAgdCA9ICh0ZXh0IG9yICIiKS5sb3dlcigpLnJlcGxhY2UoItGRIiwgItC1IikudHJhbnNsYXRlKF9MQVRJTjJDWVIpCiAgICB0ID0gcmUuc3ViKHIiW15cd1wtXSsiLCAiICIsIHQsIGZsYWdzPXJlLlUpCiAgICByZXR1cm4gcmUuc3ViKHIiXHMrIiwgIiAiLCB0KS5zdHJpcCgpCgpkZWYgX3Rva2VuaXplKHRleHQ6IHN0cikgLT4gTGlzdFtzdHJdOgogICAgcmV0dXJuIFt3IGZvciB3IGluIG5vcm1hbGl6ZSh0ZXh0KS5zcGxpdCgpIGlmIGxlbih3KSA+IDFdCgpkZWYgX3JlYWQoKSAtPiBMaXN0W0RpY3Rbc3RyLCBzdHJdXToKICAgIHRyeToKICAgICAgICBtdCA9IG9zLnBhdGguZ2V0bXRpbWUoUEFUSCkKICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgIHJldHVybiBbXQogICAgaWYgbXQgPT0gX2NhY2hlWyJtdGltZSJdOgogICAgICAgIHJldHVybiBfY2FjaGVbInJvd3MiXQogICAgcm93cyA9IFtdCiAgICB0cnk6CiAgICAgICAgd2l0aCBvcGVuKFBBVEgsICJyIiwgZW5jb2Rpbmc9InV0Zi04LXNpZyIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGZvciByIGluIGNzdi5EaWN0UmVhZGVyKGYsIGRlbGltaXRlcj0iOyIpOgogICAgICAgICAgICAgICAgaWYgKHIuZ2V0KCJxdWVyeSIpIG9yICIiKS5zdHJpcCgpOgogICAgICAgICAgICAgICAgICAgIHJvd3MuYXBwZW5kKHtrOiAoci5nZXQoaykgb3IgIiIpIGZvciBrIGluIEZJRUxEU30pCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJvd3MgPSBbXQogICAgX2NhY2hlLnVwZGF0ZShtdGltZT1tdCwgcm93cz1yb3dzKQogICAgcmV0dXJuIHJvd3MKCmRlZiBfd3JpdGUocm93czogTGlzdFtEaWN0W3N0ciwgc3RyXV0pIC0+IE5vbmU6CiAgICBvcy5tYWtlZGlycyhvcy5wYXRoLmRpcm5hbWUoUEFUSCksIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIG9wZW4oUEFUSCwgInciLCBlbmNvZGluZz0idXRmLTgtc2lnIiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICB3ID0gY3N2LkRpY3RXcml0ZXIoZiwgZmllbGRuYW1lcz1GSUVMRFMsIGRlbGltaXRlcj0iOyIsIGV4dHJhc2FjdGlvbj0iaWdub3JlIikKICAgICAgICB3LndyaXRlaGVhZGVyKCkKICAgICAgICB3LndyaXRlcm93cyhyb3dzKQogICAgdHJ5OgogICAgICAgIF9jYWNoZVsibXRpbWUiXSA9IG9zLnBhdGguZ2V0bXRpbWUoUEFUSCkKICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgIHBhc3MKICAgIF9jYWNoZVsicm93cyJdID0gcm93cwoKZGVmIGxpc3RfZXhhbXBsZXMobGltaXQ6IGludCA9IDMwMCkgLT4gTGlzdFtEaWN0W3N0ciwgc3RyXV06CiAgICB3aXRoIF9sb2NrOgogICAgICAgIHJldHVybiBsaXN0KF9yZWFkKCkpWy1saW1pdDpdWzo6LTFdCgpkZWYgY291bnQoKSAtPiBpbnQ6CiAgICB3aXRoIF9sb2NrOgogICAgICAgIHJldHVybiBsZW4oX3JlYWQoKSkKCmRlZiBhZGRfZXhhbXBsZShxdWVyeTogc3RyLCBjb3JyZWN0X2lzbzogc3RyID0gIiIsIGNvcnJlY3Rfb3BlcmF0aW9uOiBzdHIgPSAiIiwgY29ycmVjdF9za3VzOiBzdHIgPSAiIiwgY29tbWVudDogc3RyID0gIiIsCiAgICAgICAgICAgICAgICBwYXJzZXI6IE9wdGlvbmFsW0RpY3Rbc3RyLCBBbnldXSA9IE5vbmUpIC0+IERpY3Rbc3RyLCBzdHJdOgogICAgaXNvID0gKGNvcnJlY3RfaXNvIG9yICIiKS5zdHJpcCgpLnVwcGVyKCkKICAgIG9wID0gKGNvcnJlY3Rfb3BlcmF0aW9uIG9yICIiKS5zdHJpcCgpLmxvd2VyKCkKICAgIG9wID0geyJtZWRpdW0iOiAic2VtaV9maW5pc2hpbmcifS5nZXQob3AsIG9wKQogICAgc2t1cyA9ICI7ICIuam9pbihzLnN0cmlwKCkgZm9yIHMgaW4gcmUuc3BsaXQociJbOywKXSsiLCBjb3JyZWN0X3NrdXMgb3IgIiIpIGlmIHMuc3RyaXAoKSlbOjUwMF0KICAgIGVudHJ5ID0gewogICAgICAgICJpZCI6ICIiLCAidHMiOiB0aW1lLnN0cmZ0aW1lKCIlWS0lbS0lZCAlSDolTTolUyIpLCAicXVlcnkiOiAocXVlcnkgb3IgIiIpLnN0cmlwKClbOjUwMF0sCiAgICAgICAgInF1ZXJ5X25vcm0iOiBub3JtYWxpemUocXVlcnkpLCAicGFyc2VyX2lzbyI6IHN0cigocGFyc2VyIG9yIHt9KS5nZXQoImlzbyIpIG9yICIiKSwKICAgICAgICAicGFyc2VyX29wZXJhdGlvbiI6IHN0cigocGFyc2VyIG9yIHt9KS5nZXQoIm9wZXJhdGlvbiIpIG9yICIiKSwKICAgICAgICAicGFyc2VyX3RvcF9za3VzIjogIjsgIi5qb2luKChwYXJzZXIgb3Ige30pLmdldCgidG9wX3NrdXMiKSBvciBbXSlbOjMwMF0sCiAgICAgICAgImNvcnJlY3RfaXNvIjogaXNvIGlmIGlzbyBpbiBJU09fT0sgZWxzZSAiIiwgImNvcnJlY3Rfb3BlcmF0aW9uIjogb3AgaWYgb3AgaW4gT1BfT0sgZWxzZSAiIiwKICAgICAgICAiY29ycmVjdF9za3VzIjogc2t1cywgImNvbW1lbnQiOiAoY29tbWVudCBvciAiIikuc3RyaXAoKVs6NjAwXSwgInN0YXR1cyI6ICJuZXciLCAicnVsZXNfYWRkZWQiOiAiIiwKICAgIH0KICAgIHdpdGggX2xvY2s6CiAgICAgICAgcm93cyA9IGxpc3QoX3JlYWQoKSkKICAgICAgICByb3dzID0gW3IgZm9yIHIgaW4gcm93cyBpZiByWyJxdWVyeV9ub3JtIl0gIT0gZW50cnlbInF1ZXJ5X25vcm0iXV0KICAgICAgICBlbnRyeVsiaWQiXSA9IHN0cihtYXgoW2ludChyWyJpZCJdKSBmb3IgciBpbiByb3dzIGlmIHN0cihyWyJpZCJdKS5pc2RpZ2l0KCldICsgWzBdKSArIDEpCiAgICAgICAgcm93cy5hcHBlbmQoZW50cnkpCiAgICAgICAgX3dyaXRlKHJvd3MpCiAgICByZXR1cm4gZW50cnkKCmRlZiBkZWxldGVfZXhhbXBsZShleF9pZDogc3RyKSAtPiBib29sOgogICAgd2l0aCBfbG9jazoKICAgICAgICByb3dzID0gbGlzdChfcmVhZCgpKQogICAgICAgIG5ldyA9IFtyIGZvciByIGluIHJvd3MgaWYgclsiaWQiXSAhPSBzdHIoZXhfaWQpXQogICAgICAgIGlmIGxlbihuZXcpID09IGxlbihyb3dzKToKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgX3dyaXRlKG5ldykKICAgICAgICByZXR1cm4gVHJ1ZQoKZGVmIGxvb2t1cChxdWVyeTogc3RyKSAtPiBPcHRpb25hbFtEaWN0W3N0ciwgc3RyXV06CiAgICBpZiBvcy5lbnZpcm9uLmdldCgiVFJBSU5JTkdfRElTQUJMRSIpID09ICIxIjoKICAgICAgICByZXR1cm4gTm9uZQogICAgd2l0aCBfbG9jazoKICAgICAgICByb3dzID0gW3IgZm9yIHIgaW4gX3JlYWQoKSBpZiByWyJzdGF0dXMiXSAhPSAicmVqZWN0ZWQiIGFuZCAoclsiY29ycmVjdF9pc28iXSBvciByWyJjb3JyZWN0X29wZXJhdGlvbiJdIG9yIHJbImNvcnJlY3Rfc2t1cyJdKV0KICAgIGlmIG5vdCByb3dzOgogICAgICAgIHJldHVybiBOb25lCgogICAgcV90b2tlbnMgPSBfdG9rZW5pemUocXVlcnkpCiAgICBpZiBub3QgcV90b2tlbnM6CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkb2NfdG9rZW5zX2xpc3QgPSBbX3Rva2VuaXplKHJbInF1ZXJ5Il0pIGZvciByIGluIHJvd3NdCiAgICB0b3RhbF9kb2NzID0gbGVuKHJvd3MpCiAgICBkZiA9IHt9CiAgICBmb3IgdG9rcyBpbiBkb2NfdG9rZW5zX2xpc3Q6CiAgICAgICAgZm9yIHQgaW4gc2V0KHRva3MpOgogICAgICAgICAgICBkZlt0XSA9IGRmLmdldCh0LCAwKSArIDEKCiAgICBkZWYgZ2V0X3ZlY3Rvcih0b2tzKToKICAgICAgICB2ID0ge30KICAgICAgICBmb3IgdCBpbiB0b2tzOgogICAgICAgICAgICB2W3RdID0gdi5nZXQodCwgMCkgKyAxCiAgICAgICAgbm9ybV9zcSA9IDAuMAogICAgICAgIHJlcyA9IHt9CiAgICAgICAgZm9yIHQsIHRmIGluIHYuaXRlbXMoKToKICAgICAgICAgICAgaWRmID0gbWF0aC5sb2coKHRvdGFsX2RvY3MgLyAoZGYuZ2V0KHQsIDEpKSkpICsgMS4wCiAgICAgICAgICAgIHZhbCA9IHRmICogaWRmCiAgICAgICAgICAgIHJlc1t0XSA9IHZhbAogICAgICAgICAgICBub3JtX3NxICs9IHZhbCAqIHZhbAogICAgICAgIG5vcm0gPSBtYXRoLnNxcnQobm9ybV9zcSkgaWYgbm9ybV9zcSA+IDAgZWxzZSAxLjAKICAgICAgICByZXR1cm4ge2s6IHcgLyBub3JtIGZvciBrLCB3IGluIHJlcy5pdGVtcygpfQoKICAgIHFfdmVjID0gZ2V0X3ZlY3RvcihxX3Rva2VucykKICAgIGJlc3RfbWF0Y2ggPSBOb25lCiAgICBiZXN0X3Njb3JlID0gMC4wCgogICAgZm9yIGlkeCwgciBpbiBlbnVtZXJhdGUocm93cyk6CiAgICAgICAgZF92ZWMgPSBnZXRfdmVjdG9yKGRvY190b2tlbnNfbGlzdFtpZHhdKQogICAgICAgIHNjb3JlID0gc3VtKHFfdmVjW3RdICogZF92ZWNbdF0gZm9yIHQgaW4gcV92ZWMgaWYgdCBpbiBkX3ZlYykKICAgICAgICBpZiByWyJxdWVyeV9ub3JtIl0gPT0gbm9ybWFsaXplKHF1ZXJ5KToKICAgICAgICAgICAgc2NvcmUgPSAxLjAKCiAgICAgICAgaWYgc2NvcmUgPiBiZXN0X3Njb3JlOgogICAgICAgICAgICBiZXN0X3Njb3JlID0gc2NvcmUKICAgICAgICAgICAgYmVzdF9tYXRjaCA9IHIKCiAgICBpZiBiZXN0X21hdGNoIGFuZCBiZXN0X3Njb3JlID49IDAuMzU6CiAgICAgICAgcmV0dXJuIGJlc3RfbWF0Y2gKICAgIHJldHVybiBOb25lCgpkZWYgc3VnZ2VzdF90b2tlbnMocXVlcnk6IHN0cikgLT4gTGlzdFtzdHJdOgogICAgb3V0ID0gW10KICAgIGZvciB0b2sgaW4gcmUuZmluZGFsbChyIlswLTlBLVphLXrQkC3Qr9CwLdGP0IHRkV1bMC05QS1aYS160JAt0K/QsC3Rj9CB0ZFcLS4vXXsxLH0iLCBxdWVyeSBvciAiIik6CiAgICAgICAgbG93ID0gdG9rLmxvd2VyKCkuc3RyaXAoIi0uLyIpCiAgICAgICAgaWYgbGVuKGxvdykgPCAzIG9yIGxvdyBpbiB7ItGC0L7Rh9C10L3QuNC1IiwgItGH0LjRgdGC0L7QstC+0LUiLCAi0YfQuNGB0YLQvtCy0LDRjyIsICLRh9C10YDQvdC+0LLQsNGPIiwgItGH0LXRgNC90L7QstC+0LUiLCAi0L/QvtC70YPRh9C40YHRgtC+0LLQsNGPIiwgItC/0L7Qu9GD0YfQuNGB0YLQvtCy0L7QtSIsICLQvtCx0YDQsNCx0L7RgtC60LAiLCAi0L/Qu9Cw0YHRgtC40L3QsCIsICLQv9C70LDRgdGC0LjQvdGLIiwgItC/0L7QtNCx0LXRgNC4IiwgItC90YPQttC90LAiLCAi0L3Rg9C20L3QviIsICLQtNC70Y8iLCAi0L/QviIsICLQuNC3IiwgItC/0L7QtCIsICLQv9GA0LgiLCAi0LHQtdC3IiwgItGH0YLQviIsICLQutCw0LoiLCAi0LzQvCIsICLRiNGCIiwgItGB0YLQsNC70LgiLCAi0YHRgtCw0LvRjCJ9OgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIGxvdyBub3QgaW4gb3V0OgogICAgICAgICAgICBvdXQuYXBwZW5kKGxvdykKICAgIHJldHVybiBvdXRbOjhdCgpkZWYgYWRkX21hdGVyaWFsX3J1bGVzKHRva2VuczogTGlzdFtzdHJdLCBpc286IHN0ciwgbm90ZTogc3RyID0gIiIpIC0+IGludDoKICAgIGlzbyA9IChpc28gb3IgIiIpLnN0cmlwKCkudXBwZXIoKQogICAgaWYgaXNvIG5vdCBpbiBJU09fT0s6CiAgICAgICAgcmV0dXJuIDAKICAgIGV4aXN0aW5nID0gIiIKICAgIGlmIG9zLnBhdGguZXhpc3RzKE1BVEVSSUFMU19DU1YpOgogICAgICAgIHdpdGggb3BlbihNQVRFUklBTFNfQ1NWLCAiciIsIGVuY29kaW5nPSJ1dGYtOC1zaWciKSBhcyBmOgogICAgICAgICAgICBleGlzdGluZyA9IGYucmVhZCgpCiAgICBhZGRlZCA9IDAKICAgIGxpbmVzID0gW10KICAgIGZvciB0IGluIHRva2VuczoKICAgICAgICB0ID0gbm9ybWFsaXplKHQpLnJlcGxhY2UoIiAiLCAiIikKICAgICAgICBpZiBsZW4odCkgPCAzOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGVzYyA9IHJlLmVzY2FwZSh0KQogICAgICAgIHBhdCA9IHIiKD88IVvQsC3Rj2EtejAtOV0pIiArIGVzYyArIHIiKD8hW9CwLdGPYS16MC05XSkiCiAgICAgICAgaWYgcGF0IGluIGV4aXN0aW5nOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGxpbmVzLmFwcGVuZChmJyJ7cGF0fSIse2lzb30sInsobm90ZSBvciAi0LTQvtCx0LDQstC70LXQvdC+INC/0L4g0L/RgNC40LzQtdGA0YMg0YLQtdGF0L3QvtC70L7Qs9CwIikucmVwbGFjZShjaHIoMzQpLCAiIil9IicpCiAgICAgICAgYWRkZWQgKz0gMQogICAgaWYgbGluZXM6CiAgICAgICAgb3MubWFrZWRpcnMob3MucGF0aC5kaXJuYW1lKE1BVEVSSUFMU19DU1YpLCBleGlzdF9vaz1UcnVlKQogICAgICAgIG5lZWRfaGVhZGVyID0gbm90IGV4aXN0aW5nLnN0cmlwKCkKICAgICAgICB3aXRoIG9wZW4oTUFURVJJQUxTX0NTViwgImEiLCBlbmNvZGluZz0idXRmLTgtc2lnIiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgaWYgbmVlZF9oZWFkZXI6CiAgICAgICAgICAgICAgICBmLndyaXRlKCJwYXR0ZXJuLGlzbyxub3RlXG4iKQogICAgICAgICAgICBlbGlmIG5vdCBleGlzdGluZy5lbmRzd2l0aCgiXG4iKToKICAgICAgICAgICAgICAgIGYud3JpdGUoIlxuIikKICAgICAgICAgICAgZi53cml0ZSgiXG4iLmpvaW4obGluZXMpICsgIlxuIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gc3JjLm1hdGVyaWFsc19tYXBwaW5nIGltcG9ydCByZWxvYWRfbWF0ZXJpYWxfcnVsZXMKICAgICAgICAgICAgcmVsb2FkX21hdGVyaWFsX3J1bGVzKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICByZXR1cm4gYWRkZWQK"
    
    try:
        training_code = base64.b64decode(training_b64).decode("utf-8")
        with open(path, "w", encoding="utf-8") as f:
            f.write(training_code)
        ok("src/training.py обновлен на векторный поиск схожести (TF-IDF)")
    except Exception as e:
        warn(f"Ошибка при обновлении src/training.py: {e}")

def write_env_and_config() -> None:
    step("Настройка файлов конфигурации (.env и data/llm_config.json) под OmniRoute...")
    env_path = os.path.join(ROOT_DIR, ".env")
    backup_file(env_path)

    desired_env = {
        "ADVISOR_MODE": "local",
        "LLM_BASE_URL": "https://your-omniroute-endpoint.com/v1",
        "LLM_API_KEY": "ваш_ключ_omniroute",
        "LLM_MODELS": "gpt-4o-mini",
        "LLM_TIMEOUT": "60",
        "LLM_MAX_TOKENS": "500",
        "REVIEW_ENABLED": "1",
        "AUDIT_SAMPLE_RATE": "1.0",
        "REVIEW_MAX_PER_HOUR": "500",
        "REVIEW_MAX_PER_DAY": "5000",
        "ADVISOR_DEFAULT_SOURCE": "both"
    }

    existing_lines = []
    seen_keys = set()
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                raw = line.rstrip("\r\n")
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in desired_env:
                        existing_lines.append(f"{k}={desired_env[k]}")
                        seen_keys.add(k)
                        continue
                existing_lines.append(raw)

    for k, v in desired_env.items():
        if k not in seen_keys:
            existing_lines.append(f"{k}={v}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(existing_lines).strip() + "\n")
    ok("Файл .env обновлен для OmniRoute (AUDIT_SAMPLE_RATE=1.0, ADVISOR_DEFAULT_SOURCE=both)")

    data_dir = os.path.join(ROOT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    cfg_path = os.path.join(data_dir, "llm_config.json")
    backup_file(cfg_path)
    cfg_data = {
        "api_key": "ваш_ключ_omniroute",
        "base_url": "https://your-omniroute-endpoint.com/v1",
        "models": ["gpt-4o-mini"],
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    ok("Файл data/llm_config.json синхронизирован с OmniRoute")

def patch_reviewer_py() -> None:
    step("Проверка и патч src/reviewer.py для 100% использования...")
    path = os.path.join(ROOT_DIR, "src", "reviewer.py")
    if not os.path.exists(path):
        warn("src/reviewer.py не найден, пропуск.")
        return
    backup_file(path)
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    orig = content
    content = content.replace(
        'os.environ.get("AUDIT_SAMPLE_RATE", os.environ.get("REVIEW_SAMPLE_RATE", "0.15"))',
        'os.environ.get("AUDIT_SAMPLE_RATE", os.environ.get("REVIEW_SAMPLE_RATE", "1.0"))'
    )
    content = content.replace(
        'os.environ.get("REVIEW_SAMPLE_RATE", "0.15")',
        'os.environ.get("REVIEW_SAMPLE_RATE", "1.0")'
    )

    if content != orig:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok("src/reviewer.py успешно пропатчен на 100% использование (AUDIT_SAMPLE_RATE=1.0)")
    else:
        ok("src/reviewer.py уже настроен на 100% использование")

def main() -> None:
    print("=" * 68)
    print("  КОМПЛЕКСНЫЙ ПАТЧЕР TOOL ADVISOR (OMNIROUTE + VECTOR TRAINING + ADMIN FIX)")
    print("=" * 68)

    if not os.path.exists(os.path.join(ROOT_DIR, "app.py")) or not os.path.exists(os.path.join(ROOT_DIR, "src")):
        print("[ОШИБКА] Запустите этот патчер из корневой папки проекта!")
        input("\nНажмите Enter для выхода...")
        return

    patch_app_py()
    patch_training_py()
    write_env_and_config()
    patch_reviewer_py()

    print("\n" + "=" * 68)
    print("  ГОТОВО! Все изменения успешно применены.")
    print("  Не забудьте обновить URL и ключ в .env на реальные от OmniRoute.")
    print("=" * 68)
    try:
        input("\nНажмите Enter для выхода...")
    except EOFError:
        pass

if __name__ == "__main__":
    main()
