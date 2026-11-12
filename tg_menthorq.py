import json
import os
import uuid
import urllib.parse
import urllib.request
import pandas as pd

SHEET_ID = "1_FWy_B9a6t1txau06PbeEMy9S9B1GsMgWZLGfMmMG7w"
CFG_PATH = os.path.expanduser("~/.telegram_config.json")
STATE_PATH = os.path.expanduser("~/.optionhub_mq_sent.json")


def load_tg():
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            return c.get("token", ""), c.get("chat_id", "")
    return "", ""


def send_tg(token, chat_id, text):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i in range(0, len(text), 3800):
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text[i:i + 3800],
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return False
    return True


def send_tg_photo_url(token, chat_id, img_url, caption=""):
    if not token or not chat_id or not img_url:
        return False
    req_img = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req_img, timeout=15) as r:
        img_bytes = r.read()
    boundary = uuid.uuid4().hex
    parts = []
    for name, val in [("chat_id", str(chat_id)), ("caption", caption[:1020])]:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"chart.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode("utf-8")
        + img_bytes
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status == 200


def main():
    token, chat_id = load_tg()
    if not token or not chat_id:
        print("Missing telegram config")
        return

    sent = []
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                sent = json.load(f)
        except Exception:
            sent = []
    sent_set = set(sent)

    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=" + urllib.parse.quote("AI노트_뉴스시황")
    df = pd.read_csv(url).fillna("")
    if df.empty or "섹션" not in df.columns:
        return

    mq_df = df[df["섹션"].astype(str).str.contains("맨도큐|Menthor|GeeksOfFinance|SpotGamma|UnusualWhales", case=False, na=False)]
    photo_items = []
    text_items = []

    for _, r in mq_df.iterrows():
        dt = str(r.get("날짜", "")).strip()
        tk = str(r.get("종목", "")).strip()
        ko = str(r.get("한글 번역/해석", "")).strip()
        img_url = str(r.get("이미지URL", "")).strip()
        key = f"{dt}|{tk}|{ko[:40]}"
        if key not in sent_set and ko:
            if img_url.startswith("http"):
                photo_items.append((key, dt, tk, ko, img_url))
            else:
                text_items.append((key, dt, tk, ko))

    # 1) 이미지가 있는 리포트는 사진 + 밑에 한글 설명(캡션)으로 개별 전송
    for key, dt, tk, ko, img_url in photo_items:
        cap = f"📊 [{tk} GEX 리포트] ({dt})\n\n{ko}"
        ok = False
        try:
            ok = send_tg_photo_url(token, chat_id, img_url, caption=cap)
        except Exception:
            ok = send_tg(token, chat_id, cap)
        if ok:
            sent.append(key)
            sent_set.add(key)

    # 2) 텍스트 전용 리포트는 날짜별로 묶어서 전송
    by_date = {}
    for key, dt, tk, ko in text_items:
        by_date.setdefault(dt, []).append((key, tk, ko))

    for dt, items in by_date.items():
        lines = [f"📐 [Menthor Q 그릭스·GEX 리포트] ({dt})", ""]
        for _, tk, ko in items:
            lines.append(f"🔹 {tk}")
            lines.append(ko)
            lines.append("")
        lines.append("🌐 대시보드: http://132.226.3.145:8501")
        if send_tg(token, chat_id, "\n".join(lines)):
            for key, _, _ in items:
                sent.append(key)
                sent_set.add(key)

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(sent[-200:], f, ensure_ascii=False, indent=2)
    print(f"Sent {len(photo_items)} photos, {len(text_items)} text items.")


if __name__ == "__main__":
    main()