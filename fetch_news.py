#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QST عربي — نظام جمع الأخبار التلقائي بالذكاء الاصطناعي
يجلب الأخبار من مصادر RSS العربية، يعيد صياغتها بمفتاح API (OpenAI / Groq / أي خدمة متوافقة)،
ويُولّد ملف articles.json الذي يقرأه الموقع. يعمل على GitHub Actions مجاناً كل ساعة.

الإعداد: ضع المفتاحين في Secrets في مستودع GitHub:
  OPENAI_API_KEY   — مفتاح خدمة الذكاء الاصطناعي (Groq مجاني للاستخدام الخفيف)
  OPENAI_BASE_URL  — مثال: https://api.groq.com/openai/v1  (اختياري، الافتراضي OpenAI)
  OPENAI_MODEL     — مثال: llama-3.3-70b-versatile  أو gpt-4o-mini
"""
import json, os, re, time, hashlib, html
from datetime import datetime, timezone, timedelta
import urllib.request
import xml.etree.ElementTree as ET

# مصادر RSS العربية (يمكنك إضافة المزيد)
FEEDS = [
    ("الجزيرة", "https://www.aljazeera.net/xml/rss/all.xml"),
    ("بي بي سي عربي", "http://feeds.bbci.co.uk/arabic/rss.xml"),
    ("العربية", "https://www.alarabiya.net/.mrss/ar.xml"),
    ("الشرق الأوسط", "https://www.aawsat.com/rss"),
    ("القدس العربي", "https://www.qudsn.com/rss"),
]
MAX_ARTICLES = 12          # عدد المقالات المولّدة في كل تشغيل
CACHE_FILE = "seen_hashes.json"
OUT_FILE = "articles.json"

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 QST-NewsBot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def parse_feed(xml_bytes, source_name):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return items
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = html.unescape(desc).strip()
        if title and link:
            items.append({"source": source_name, "title": title, "link": link, "summary": desc[:400]})
    return items

def load_seen():
    if os.path.exists(CACHE_FILE):
        try: return set(json.load(open(CACHE_FILE, encoding="utf-8")))
        except Exception: return set()
    return set()

def save_seen(seen):
    json.dump(list(seen)[-500:], open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)

def ai_rewrite(title, summary, source):
    """يطلب من الذكاء الاصطناعي كتابة مقال عربي كامل (4 فقرات) من العنوان والملخص."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        # بدون مفتاح: نكتب مقالاً بسيطاً من الملخص (وضع تجريبي)
        return fallback_rewrite(title, summary, source)
    prompt = (
        "أنت محرر صحفي عربي في قناة QST عربي. اكتب مقالاً إخبارياً مهنياً باللغة العربية الفصحى "
        "من المعلومات التالية، مكوناً من 4 فقرات متتابعة، كل فقرة سطر واحد مفصول بفاصلة سطرين. "
        "لا تضف عنواناً ولا تعليقاً، فقط الفقرات. كن دقيقاً ولا تختلق حقائق جديدة.\n\n"
        f"المصدر: {source}\nالعنوان: {title}\nالملخص: {summary}"
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
    }).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        text = data["choices"][0]["message"]["content"].strip()
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()][:4]
        if len(paras) < 2:
            paras = [p.strip() for p in text.split("\n") if p.strip()][:4]
        return paras
    except Exception as e:
        print(f"AI error: {e}")
        return fallback_rewrite(title, summary, source)

def fallback_rewrite(title, summary, source):
    return [
        f"في تطور جديد تتابعه شبكة QST عربي، يأتي هذا الخبر من مصدر {source} بعنوان: {title}.",
        f"ووفقاً للمعلومات المتاحة: {summary}",
        "وتشير المصادر إلى أن الملف لا يزال قيد التطور، وتتعهد شبكة QST عربي بمتابعة المستجدات ولحظة بلحظة.",
        "وينشر هذا المقال ضمن التحديث التلقائي لنظام جمع الأخبار الذكي، ويمكن للقراء متابعة التفاصيل عبر المصدر الأصلي.",
    ]

def guess_category(title):
    t = title
    if any(w in t for w in ["انتخاب", "برلمان", "حكومة", "وزير", "رئيس", "سفير", "مفاوض", "جيش", "غارة", "هجوم"]): return "politics"
    if any(w in t for w in ["نفط", "سهم", "بورصة", "اقتصاد", "دولار", "ذهب", "أسعار", "تضخم", "عملة"]): return "economy"
    if any(w in t for w in ["مقبرة", "آثار", "كتاب", "معرض", "فيلم", "موسيقى", "فن", "ثقافة"]): return "culture"
    return "world"

CAT_LABEL = {"politics": "سياسة", "economy": "اقتصاد", "world": "عالم", "culture": "ثقافة"}
GRADS = {
    "politics": "linear-gradient(135deg,#7c2d12,#ea580c)",
    "economy": "linear-gradient(135deg,#064e3b,#10b981)",
    "world": "linear-gradient(135deg,#134e4a,#0ea5e9)",
    "culture": "linear-gradient(135deg,#713f12,#eab308)",
}

def main():
    seen = load_seen()
    raw = []
    for name, url in FEEDS:
        try:
            xml = fetch(url)
            items = parse_feed(xml, name)
            raw.extend(items)
            print(f"[OK] {name}: {len(items)} عنصر")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
        time.sleep(1)

    fresh = []
    for it in raw:
        h = hashlib.md5(it["title"].encode("utf-8")).hexdigest()[:12]
        if h in seen:
            continue
        seen.add(h)
        it["hash"] = h
        fresh.append(it)
        if len(fresh) >= MAX_ARTICLES:
            break

    articles = []
    now = datetime.now(timezone(timedelta(hours=3)))  # بتوقيت الرياض
    for it in fresh:
        cat = guess_category(it["title"])
        body = ai_rewrite(it["title"], it["summary"], it["source"])
        slug = re.sub(r"[^a-z0-9]+", "-", hashlib.md5(it["title"].encode()).hexdigest()[:10])
        articles.append({
            "id": slug,
            "cat": cat,
            "catLabel": CAT_LABEL[cat],
            "title": it["title"],
            "time": "قبل " + str((now - now).seconds // 60 or 5) + " دقائق",
            "author": f"{it['source']} — نظام QST الذكي",
            "read": f"{max(2, len(' '.join(body))//300)} دقائق",
            "grad": GRADS[cat],
            "lede": body[0] if body else it["summary"],
            "body": body,
            "sourceLink": it["link"],
            "generatedAt": now.isoformat(),
        })
        print(f"[AI] كُتب مقال: {it['title'][:40]}...")

    # دمج مع المقالات السابقة (احتفظ بأحدث 30)
    old = []
    if os.path.exists(OUT_FILE):
        try: old = json.load(open(OUT_FILE, encoding="utf-8"))
        except Exception: old = []
    merged = articles + old
    seen_ids = set(); final = []
    for a in merged:
        if a["id"] in seen_ids: continue
        seen_ids.add(a["id"]); final.append(a)
        if len(final) >= 30: break

    json.dump(final, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    save_seen(seen)
    print(f"DONE: {len(articles)} مقال جديد، المجموع {len(final)} مقال في {OUT_FILE}")

if __name__ == "__main__":
    main()
