"""
Emir.ai — Full Stack Backend
Endpoints: /chat /vision /title /admin /login /logout
"""
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context, session
from groq import Groq
from duckduckgo_search import DDGS
import os, json, re, time, hashlib
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "emirai-secret-2025")
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Model Tiers ──────────────────────────────
MODEL_TIERS = {
    "fast":     "llama-3.1-8b-instant",
    "balanced": "llama-3.1-8b-instant",
    "pro":      "llama-3.3-70b-versatile",
}
MODEL_PARAMS = {
    "fast":     {"max_tokens": 400,  "temperature": 0.6},
    "balanced": {"max_tokens": 800,  "temperature": 0.7},
    "pro":      {"max_tokens": 1200, "temperature": 0.75},
}

# ── System Prompt ────────────────────────────
BASE_SYSTEM = """Sen Emir.ai'sin — zeki, samimi ve yardımsever bir Türkçe yapay zeka asistanı.

KİŞİLİK:
• Sıcak ama profesyonel üslup kullan
• Kullanıcıya adıyla hitap et (söylenirse)
• Emojileri yeri geldiğinde, aşırıya kaçmadan kullan

TÜRKÇE KURALLARI:
• Yabancı kelimeleri gereksiz kullanma ("query" → "sorgu", "update" → "güncelle")
• Ekleri doğru kullan; kelimeleri birleştirme
• Dolgu ifadelerden ("esasen", "aslında bakarsak") kaçın
• Noktalama işaretlerini doğru kullan

YANIT FORMATI:
• Kod için ``` kullan ve dil belirt
• Listeler için - veya 1. kullan
• Önemli kavramları **kalın** yaz
• Gereksiz uzatma; özlü ol

ÖZEL DURUMLAR:
• "Fotoğraf gönder" veya görsel analiz istenirse: "Görüntüyü şu an doğrudan göremiyorum, ama 📎 butonuyla yükleyip analiz ettirebilirsin."
• Uydurma; bilmiyorsan dürüstçe söyle
• İnternet araması sonucu verilmişse onu kullan ve kaynakları belirt
• Şakalar doğal ve kaliteli olsun; kötü şaka yapmaktansa yapma"""

# ── Mock Auth ────────────────────────────────
DEMO_USERS = {
    "demo":  hashlib.sha256("demo123".encode()).hexdigest(),
    "admin": hashlib.sha256("1234".encode()).hexdigest(),
}

# ── Mock Analytics ───────────────────────────
analytics = {
    "total_messages": 0,
    "model_usage": defaultdict(int),
    "chat_log": [],       # last 20
    "users": defaultdict(lambda: {"messages": 0, "last_active": 0}),
}

# ── Spam Protection ──────────────────────────
rate_limits = defaultdict(list)  # ip → [timestamps]
RATE_WINDOW  = 60   # seconds
RATE_MAX     = 20   # messages per window

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    rate_limits[ip] = [t for t in rate_limits[ip] if now - t < RATE_WINDOW]
    if len(rate_limits[ip]) >= RATE_MAX:
        return True
    rate_limits[ip].append(now)
    return False

# ── Internet Search ──────────────────────────
SEARCH_PATTERN = re.compile(
    r"\b(hava durumu|hava nasıl|kaç derece"
    r"|bugün(kü)?|şu an(da)?|şu sıralar"
    r"|son dakika|son haber|güncel haber"
    r"|kim kazandı|maç sonucu|skor"
    r"|dolar kaç|euro kaç|bitcoin fiyat[ıi]"
    r"|borsa|altın fiyat"
    r"|ne zaman açıl|ne zaman kapan"
    r"|2025\s*(yılı|haberleri|gelişmeleri)"
    r"|güncel|en son|yeni çıkan"
    r"|seçim sonuç|deprem)\b",
    re.IGNORECASE | re.UNICODE
)

def internet_ara(sorgu: str):
    try:
        with DDGS() as d:
            r = list(d.text(sorgu, region="tr-tr", max_results=4, timelimit="m"))
            if not r:
                r = list(d.text(sorgu, region="tr-tr", max_results=4))
            if r:
                return "\n\n".join(
                    f"• **{s.get('title','')}**\n  {s.get('body','')}\n  Kaynak: {s.get('href','')}"
                    for s in r
                )
    except Exception as e:
        print(f"[Arama hatası] {e}")
    return None

def arama_gerekli_mi(mesaj: str) -> bool:
    return bool(SEARCH_PATTERN.search(mesaj))

def context_hazirla(msgs: list, max_msgs=10) -> list:
    return msgs[-max_msgs:] if len(msgs) > max_msgs else msgs

# ── Routes ───────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/admin")
def admin():
    return send_from_directory("static", "admin.html")

@app.route("/login", methods=["POST"])
def login():
    data     = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    pw_hash  = hashlib.sha256(password.encode()).hexdigest()
    if DEMO_USERS.get(username) == pw_hash:
        session["user"] = username
        return jsonify({"ok": True, "username": username, "isAdmin": username == "admin"})
    return jsonify({"ok": False, "error": "Kullanıcı adı veya şifre yanlış"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/chat", methods=["POST"])
def chat():
    ip = request.remote_addr
    if is_rate_limited(ip):
        def fallback():
            yield f"data: {json.dumps({'type':'token','text':'Sistem yoğun, biraz bekle gng 🙃'})}\n\n"
            yield f"data: {json.dumps({'type':'done'})}\n\n"
        return Response(stream_with_context(fallback()), mimetype="text/event-stream",
                        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    data      = request.json or {}
    mesajlar  = data.get("messages", [])
    custom    = data.get("customPrompt", "").strip()
    username  = data.get("userName", "").strip()
    tier      = data.get("modelTier", "balanced")
    if tier not in MODEL_TIERS: tier = "balanced"

    if not mesajlar:
        return jsonify({"error": "Mesaj yok"}), 400

    son_mesaj = mesajlar[-1].get("content", "")

    sistem = BASE_SYSTEM
    if username:
        sistem += f"\n\nKullanıcının adı: **{username}** — adıyla hitap et."
    if custom:
        sistem += f"\n\nKullanıcı tercihleri:\n{custom}"

    arama_yapildi = False
    if arama_gerekli_mi(son_mesaj):
        bilgi = internet_ara(son_mesaj)
        if bilgi:
            sistem += f"\n\n---\n🔍 **İnternet Araması:**\n{bilgi}\n---\nBu bilgileri kullan, kaynakları belirt."
            arama_yapildi = True

    hazir = context_hazirla(mesajlar)

    # Analytics
    analytics["total_messages"] += 1
    analytics["model_usage"][tier] += 1
    analytics["users"][ip]["messages"] += 1
    analytics["users"][ip]["last_active"] = time.time()
    log_entry = {"user": username or ip, "message": son_mesaj[:80], "tier": tier, "ts": time.time()}
    analytics["chat_log"].insert(0, log_entry)
    analytics["chat_log"] = analytics["chat_log"][:20]

    def generate():
        try:
            if arama_yapildi:
                yield f"data: {json.dumps({'type':'search','active':True})}\n\n"

            stream = client.chat.completions.create(
                model=MODEL_TIERS[tier],
                messages=[{"role":"system","content":sistem}] + hazir,
                max_tokens=MODEL_PARAMS[tier]["max_tokens"],
                temperature=MODEL_PARAMS[tier]["temperature"],
                stream=True,
            )
            for chunk in stream:
                d = chunk.choices[0].delta
                if d.content:
                    yield f"data: {json.dumps({'type':'token','text':d.content})}\n\n"

            yield f"data: {json.dumps({'type':'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':'Bir hata oluştu, tekrar dene.'})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/vision", methods=["POST"])
def vision():
    data      = request.json or {}
    image_b64 = data.get("image")
    mime      = data.get("mimeType", "image/jpeg")
    soru      = data.get("question", "Bu görseli Türkçe detaylıca açıkla. Varsa metinleri oku, nesneleri ve sahneyi tanımla.")
    if not image_b64:
        return jsonify({"error": "Görsel yok"}), 400
    try:
        r = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":f"data:{mime};base64,{image_b64}"}},
                {"type":"text","text":soru}
            ]}],
            max_tokens=1024, temperature=0.5,
        )
        return jsonify({"description": r.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/title", methods=["POST"])
def generate_title():
    data  = request.json or {}
    msgs  = data.get("messages", [])
    if len(msgs) < 2:
        return jsonify({"title": "Yeni Sohbet"})
    metin = "\n".join(
        f"{'Kullanıcı' if m['role']=='user' else 'Asistan'}: {m['content'][:120]}"
        for m in msgs[:3]
    )
    try:
        r = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role":"system","content":"Sohbet için 3-6 kelimelik Türkçe, öz başlık üret. Sadece başlığı yaz. Tırnak kullanma."},
                {"role":"user","content":metin}
            ],
            max_tokens=30, temperature=0.5,
        )
        title = r.choices[0].message.content.strip().strip('"\'')
        return jsonify({"title": title[:48] + ("…" if len(title)>48 else "")})
    except:
        return jsonify({"title": msgs[0]["content"][:32] if msgs else "Sohbet"})

@app.route("/admin/data", methods=["GET"])
def admin_data():
    if session.get("user") != "admin":
        return jsonify({"error": "Yetkisiz"}), 403
    users_list = [
        {"ip": ip, "messages": d["messages"], "last_active": d["last_active"]}
        for ip, d in list(analytics["users"].items())[:20]
    ]
    return jsonify({
        "total_messages": analytics["total_messages"],
        "model_usage":    dict(analytics["model_usage"]),
        "chat_log":       analytics["chat_log"],
        "users":          users_list,
        "total_users":    len(analytics["users"]),
    })

@app.route("/admin/clear", methods=["POST"])
def admin_clear():
    if session.get("user") != "admin":
        return jsonify({"error": "Yetkisiz"}), 403
    action = (request.json or {}).get("action")
    if action == "logs":
        analytics["chat_log"].clear()
    elif action == "all":
        analytics["chat_log"].clear()
        analytics["total_messages"] = 0
        analytics["model_usage"].clear()
        analytics["users"].clear()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
