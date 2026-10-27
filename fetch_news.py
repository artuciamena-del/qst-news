#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QST عربي - نظام جمع الاخبار التلقائي بالذكاء الاصطناعي + جلب الصور
مزودو الذكاء الاصطناعي (يُجرَّبون بالترتيب، يتوقف عند اول نجاح):
  1) Pollinations - مجاني تماماً بدون مفتاح
  2) Google Gemini - مجاني 1500 طلب/يوم (مفتاح: GEMINI_API_KEY)
  3) Groq / OpenRouter / اي خدمة متوافقة مع OpenAI - مجاني بمفتاح
  4) وضع احتياطي: كتابة من الملخص بدون ذكاء اصطناعي
"""
import json, os, re, time, hashlib, html, urllib.request
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET

FEEDS = [
    ("الجزيرة", "https://www.aljazeera.net/xml/rss/all.xml"),
    ("بي بي سي عربي", "http://feeds.bbci.co.uk/arabic/rss.xml"),
    ("العربية", "https://www.alarabiya.net/.mrss/ar.xml"),
    ("الشرق الأوسط", "https://www.aawsat.com/rss"),
    ("القدس العربي", "https://www.qudsn.com/rss"),
]
MAX_ARTICLES = 12
CACHE_FILE = "seen_hashes.json"
OUT_FILE = "articles.json"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 QST-NewsBot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def extract_image(item, desc):
    mc = item.find(MEDIA_NS + "content")
    if mc is not None and mc.get("url"):
        return mc.get("url")
    mt = item.find(MEDIA_NS + "thumbnail")
    if mt is not None and mt.get("url"):
        return mt.get("url")
    enc = item.find("enclosure")
    if enc is not None and enc.get("type", "").startswith("image") and enc.get("url"):
        return enc.get("url")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
    if m:
        return m.group(1)
    return ""

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
        desc_clean = re.sub(r"<[^>]+>", " ", desc)
        desc_clean = html.unescape(desc_clean).strip()
        image = extract_image(item, desc)
        if title and link:
            items.append({"source": source_name, "title": title, "link": link,
                          "summary": desc_clean[:400], "image": image})
    return items

def load_seen():
    if os.path.exists(CACHE_FILE):
        try: return set(json.load(open(CACHE_FILE, encoding="utf-8")))
        except Exception: return set()
    return set()

def save_seen(seen):
    json.dump(list(seen)[-600:], open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)

def post_json(url, payload, headers, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

PROMPT = (
    "انت محرر صحفي عربي في قناة QST عربي. اكتب مقالاً إخبارياً مهنياً بالعربية الفصحى "
    "من المعلومات التالية، مكوناً من 4 فقرات متتابعة مفصولة بفاصلة سطرين. "
    "لا تضف عنواناً ولا تعليقاً، فقط الفقرات. لا تختلق حقائق جديدة.\n\n"
    "المصدر: {source}\nالعنوان: {title}\nالملخص: {summary}"
)

def split_paras(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()][:4]
    if len(paras) < 2:
        paras = [p.strip() for p in text.strip().split("\n") if p.strip()][:4]
    return paras if len(paras) >= 2 else None

def ai_pollinations(title, summary, source):
    for attempt in range(2):
        try:
            data = post_json("https://text.pollinations.ai/openai",
                {"model": "openai-fast", "messages": [{"role": "user", "content": PROMPT.format(title=title, summary=summary, source=source)}], "max_tokens": 700},
                {"Content-Type": "application/json"})
            paras = split_paras(data["choices"][0]["message"]["content"])
            if paras: return paras, "pollinations-free"
        except Exception as e:
            print(f"  [Pollinations] attempt {attempt+1}: {e}")
            time.sleep(8)
    return None, None

def ai_openai_compatible(title, summary, source):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key: return None, None
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    try:
        data = post_json(base + "/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": PROMPT.format(title=title, summary=summary, source=source)}], "temperature": 0.5, "max_tokens": 700},
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        paras = split_paras(data["choices"][0]["message"]["content"])
        if paras: return paras, "openai-compatible"
    except Exception as e:
        print(f"  [OpenAI-compatible] {e}")
    return None, None

def ai_gemini(title, summary, source):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key: return None, None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    try:
        data = post_json(url,
            {"contents": [{"parts": [{"text": PROMPT.format(title=title, summary=summary, source=source)}]}],
             "generationConfig": {"temperature": 0.5, "maxOutputTokens": 700}},
            {"Content-Type": "application/json"})
        paras = split_paras(data["candidates"][0]["content"]["parts"][0]["text"])
        if paras: return paras, "gemini-free"
    except Exception as e:
        print(f"  [Gemini] {e}")
    return None, None

def fallback_rewrite(title, summary, source):
    return [
        f"في تطور جديد تتابعه شبكة QST عربي، يأتي هذا الخبر من مصدر {source} بعنوان: {title}.",
        f"ووفقاً للمعلومات المتاحة: {summary}",
        "وتشير المصادر إلى أن الملف لا يزال قيد التطور، وتتعهد شبكة QST عربي بمتابعة المستجدات لحظة بلحظة.",
        "ينشر هذا المقال ضمن التحديث التلقائي لنظام جمع الأخبار الذكي، ويمكن للقراء متابعة التفاصيل عبر المصدر الأصلي.",
    ], "fallback"

def rewrite_article(title, summary, source):
    for fn in (ai_pollinations, ai_openai_compatible, ai_gemini):
        paras, provider = fn(title, summary, source)
        if paras: return paras, provider
    return fallback_rewrite(title, summary, source)

def guess_category(title):
    t = title
    if any(w in t for w in ["وظيفة","وظائف","توظيف","فرصة عمل","مقبولين","نتائج"]): return "jobs"
    if any(w in t for w in ["انتخاب","برلمان","حكومة","وزير","رئيس","سفير","مفاوض","جيش","غارة","هجوم","صاروخ","قتلى","جبهة","احتلال","عدوان"]): return "politics"
    if any(w in t for w in ["نفط","سهم","بورصة","اقتصاد","دولار","ذهب","أسعار","تضخم","عملة","بنك","تجارة","صادرات"]): return "economy"
    if any(w in t for w in ["مقبرة","آثار","كتاب","معرض","فيلم","موسيقى","فن","ثقافة","رياضة","كرة","أولمبي"]): return "culture"
    return "world"

CAT_LABEL = {"politics": "سياسة", "economy": "اقتصاد", "world": "عالم", "culture": "ثقافة", "jobs": "وظائف"}
GRADS = {
    "politics": "linear-gradient(135deg,#7c2d12,#ea580c)",
    "economy": "linear-gradient(135deg,#064e3b,#10b981)",
    "world": "linear-gradient(135deg,#134e4a,#0ea5e9)",
    "culture": "linear-gradient(135deg,#713f12,#eab308)",
    "jobs": "linear-gradient(135deg,#1e3a8a,#6366f1)",
}

def main():
    seen = load_seen()
    raw = []
    for name, url in FEEDS:
        try:
            xml = fetch(url)
            items = parse_feed(xml, name)
            raw.extend(items)
            imgs = sum(1 for i in items if i.get("image"))
            print(f"[OK] {name}: {len(items)} (صور: {imgs})")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
        time.sleep(1)

    fresh = []
    for it in raw:
        h = hashlib.md5(it["title"].encode("utf-8")).hexdigest()[:12]
        if h in seen: continue
        seen.add(h)
        it["hash"] = h
        fresh.append(it)
        if len(fresh) >= MAX_ARTICLES: break

    articles = []
    now = datetime.now(timezone(timedelta(hours=3)))
    providers_used = {}
    for idx, it in enumerate(fresh):
        cat = guess_category(it["title"])
        body, provider = rewrite_article(it["title"], it["summary"], it["source"])
        providers_used[provider] = providers_used.get(provider, 0) + 1
        slug = hashlib.md5(it["title"].encode()).hexdigest()[:10]
        articles.append({
            "id": slug, "cat": cat, "catLabel": CAT_LABEL.get(cat, "عالم"),
            "title": it["title"], "time": f"قبل {5+idx*7} دقائق",
            "author": f"{it['source']} - نظام QST الذكي ({provider})",
            "read": f"{max(2, len(' '.join(body))//300)} دقائق",
            "grad": GRADS.get(cat, GRADS["world"]), "lede": body[0], "body": body,
            "sourceLink": it["link"], "image": it.get("image", ""),
            "generatedAt": now.isoformat(), "aiProvider": provider,
        })
        print(f"[AI/{provider}] {it['title'][:40]}... img={'Y' if it.get('image') else 'N'}")

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
    print(f"DONE: {len(articles)} new - AI providers: {providers_used} - total {len(final)}")

if __name__ == "__main__":
    main()
  
