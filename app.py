"""
Emir.ai — Production Backend
Auth: PostgreSQL + bcrypt + httpOnly session cookie
Endpoints: /register /login /logout /me
           /chat /vision /title
           /admin /admin/users /admin/user/<id>
"""

# ═══════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════
from flask import (Flask, request, jsonify, send_from_directory,
                   Response, stream_with_context, session, render_template)
from groq import Groq
from duckduckgo_search import DDGS
import os, json, re, time
from datetime import timedelta
from dotenv import load_dotenv
from collections import defaultdict

# db.py ve auth.py ayrı dosyalarda — temiz mimari
from db   import (get_db, init_db, _hash_pw, _check_pw,
                  reset_daily_if_needed, get_all_users_for_admin,
                  patch_user, delete_user, get_stats, PG_AVAILABLE)
from auth import (auth_bp, login_required, admin_required, get_current_user)

load_dotenv()

# ═══════════════════════════════════════════════
# APP KURULUM
# ═══════════════════════════════════════════════
# FİX: template_folder="templates" açıkça belirtildi.
#      Flask varsayılan olarak templates/ klasörüne bakar
#      ama Render'da çalışma dizini farklı olabileceğinden
#      os.path.abspath ile mutlak yol kullanıyoruz.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    template_folder=os.path.join(BASE_DIR, "templates"),
)

app.secret_key                 = os.getenv("SECRET_KEY", "emirai-super-secret-2025-change-me")
app.permanent_session_lifetime = timedelta(days=30)

# Cookie güvenlik ayarları
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = os.getenv("FLASK_ENV") == "production"

# Auth Blueprint kayıt et
app.register_blueprint(auth_bp)

# FİX: GROQ_API_KEY yoksa uygulama yine de başlasın,
#      sadece chat endpoint'i hata versin.
_groq_key = os.getenv("GROQ_API_KEY", "")
client    = Groq(api_key=_groq_key) if _groq_key else None

# ═══════════════════════════════════════════════
# MODELLERİ & SYSTEM PROMPT
# ═══════════════════════════════════════════════
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
• Uydurma; bilmiyorsan dürüstçe söyle
• İnternet araması sonucu verilmişse onu kullan ve kaynakları belirt
• Şakalar doğal ve kaliteli olsun; kötü şaka yapmaktansa yapma"""

# ═══════════════════════════════════════════════
# SPAM KORUMA
# ═══════════════════════════════════════════════
rate_limits = defaultdict(list)
RATE_WINDOW = 60
RATE_MAX    = 20

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    rate_limits[ip] = [t for t in rate_limits[ip] if now - t < RATE_WINDOW]
    if len(rate_limits[ip]) >= RATE_MAX:
        return True
    rate_limits[ip].append(now)
    return False

# ═══════════════════════════════════════════════
# İNTERNET ARAMA
# ═══════════════════════════════════════════════
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

# ═══════════════════════════════════════════════
# SAYFA ROUTE'LARI
# ═══════════════════════════════════════════════

@app.route("/")
def index():
    # FİX: send_from_directory("static",...) → render_template()
    # HTML'ler templates/ klasöründe, Flask doğrudan oradan okur.
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    """Admin paneli — sadece admin rolündekiler görebilir."""
    if not session.get("user_id"):
        # Giriş yapılmamış → ana sayfaya yönlendir
        return render_template("index.html")
    if session.get("role") != "admin":
        return "<h2 style='font-family:sans-serif;text-align:center;margin-top:80px'>403 — Yetkisiz Erişim</h2>", 403
    # FİX: aynı şekilde render_template kullan
    return render_template("admin.html")


# FİX: favicon 404 hatasını önle
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(BASE_DIR, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon"
    )


@app.route("/admin/stats", methods=["GET"])
@login_required
@admin_required
def admin_stats():
    """Admin dashboard istatistikleri. (db.py → get_stats)"""
    if not get_db():
        return jsonify({"ok": False, "error": "DB bağlantısı yok"}), 503
    stats = get_stats()
    if not stats:
        return jsonify({"ok": False, "error": "İstatistik alınamadı"}), 500
    return jsonify({"ok": True, **stats})

# ═══════════════════════════════════════════════
# CHAT
# ═══════════════════════════════════════════════
@app.route("/chat", methods=["POST"])
def chat():
    # FİX: Groq client yoksa (API key set edilmemişse) anlamlı hata ver
    if not client:
        def no_key():
            yield f"data: {json.dumps({'type':'error','message':'GROQ_API_KEY ayarlanmamış. Render ortam değişkenlerini kontrol et.'})}" + "\n\n"
        return Response(stream_with_context(no_key()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    ip = request.remote_addr

    if is_rate_limited(ip):
        def fallback():
            yield f"data: {json.dumps({'type':'token','text':'⚠️ Çok fazla istek gönderiyorsun, biraz bekle.'})}" + "\n\n"
            yield f"data: {json.dumps({'type':'done'})}" + "\n\n"
        return Response(stream_with_context(fallback()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    data     = request.json or {}
    mesajlar = data.get("messages", [])
    custom   = data.get("customPrompt", "").strip()
    username = data.get("userName", "").strip()
    tier     = data.get("modelTier", "balanced")
    if tier not in MODEL_TIERS:
        tier = "balanced"

    if not mesajlar:
        return jsonify({"error": "Mesaj yok"}), 400

    son_mesaj = mesajlar[-1].get("content", "")

    # ── Mesaj limiti kontrolü ──────────────────
    user_id = session.get("user_id")
    if user_id:
        conn = get_db()
        if conn:
            try:
                reset_daily_if_needed(conn, user_id)
                cur = conn.cursor()
                cur.execute("SELECT messages_today, message_limit, role FROM users WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if row and row["role"] != "admin":
                    if row["messages_today"] >= row["message_limit"]:
                        conn.commit()
                        conn.close()
                        def limit_msg():
                            msg = json.dumps({
                                "type":  "limit_reached",
                                "used":  row["messages_today"],
                                "limit": row["message_limit"],
                            })
                            yield f"data: {msg}" + "\n\n"
                        return Response(stream_with_context(limit_msg()), mimetype="text/event-stream",
                                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
                    cur.execute("UPDATE users SET messages_today=messages_today+1 WHERE id=%s", (user_id,))
                    conn.commit()
            except Exception as e:
                print(f"[Chat limit] hata: {e}")
            finally:
                if not conn.closed:
                    conn.close()

    # ── System prompt ──────────────────────────
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

    def generate():
        try:
            if arama_yapildi:
                yield f"data: {json.dumps({'type':'search','active':True})}" + "\n\n"
            stream = client.chat.completions.create(
                model=MODEL_TIERS[tier],
                messages=[{"role": "system", "content": sistem}] + hazir,
                max_tokens=MODEL_PARAMS[tier]["max_tokens"],
                temperature=MODEL_PARAMS[tier]["temperature"],
                stream=True,
            )
            for chunk in stream:
                d = chunk.choices[0].delta
                if d.content:
                    yield f"data: {json.dumps({'type':'token','text':d.content})}" + "\n\n"
            yield f"data: {json.dumps({'type':'done'})}" + "\n\n"
        except Exception as e:
            print(f"[Chat] generate hatası: {e}")
            yield f"data: {json.dumps({'type':'error','message':'Bir hata oluştu, tekrar dene.'})}" + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/vision", methods=["POST"])
def vision():
    if not client:
        return jsonify({"error": "GROQ_API_KEY ayarlanmamış"}), 503
    data      = request.json or {}
    image_b64 = data.get("image")
    mime      = data.get("mimeType", "image/jpeg")
    soru      = data.get("question", "Bu görseli Türkçe detaylıca açıkla.")
    if not image_b64:
        return jsonify({"error": "Görsel yok"}), 400
    try:
        r = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text",      "text": soru}
            ]}],
            max_tokens=1024, temperature=0.5,
        )
        return jsonify({"description": r.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/title", methods=["POST"])
def generate_title():
    if not client:
        return jsonify({"title": "Yeni Sohbet"})
    data = request.json or {}
    msgs = data.get("messages", [])
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
                {"role": "system", "content": "Sohbet için 3-6 kelimelik Türkçe, öz başlık üret. Sadece başlığı yaz. Tırnak kullanma."},
                {"role": "user",   "content": metin}
            ],
            max_tokens=30, temperature=0.5,
        )
        title = r.choices[0].message.content.strip().strip('"\'')
        return jsonify({"title": title[:48] + ("…" if len(title) > 48 else "")})
    except Exception:
        return jsonify({"title": msgs[0]["content"][:32] if msgs else "Sohbet"})

# ═══════════════════════════════════════════════
# ADMIN API
# ═══════════════════════════════════════════════

@app.route("/admin/users", methods=["GET"])
@login_required
@admin_required
def admin_list_users():
    if not get_db():
        return jsonify({"ok": False, "error": "DB bağlantısı yok"}), 503
    rows = get_all_users_for_admin()
    return jsonify({"ok": True, "users": rows})


@app.route("/admin/user/<int:user_id>", methods=["PATCH"])
@login_required
@admin_required
def admin_update_user(user_id):
    data = request.json or {}
    if not data:
        return jsonify({"ok": False, "error": "Güncellenecek alan yok"}), 400
    if not get_db():
        return jsonify({"ok": False, "error": "DB bağlantısı yok"}), 503
    row = patch_user(user_id, data)
    if row is None:
        return jsonify({"ok": False, "error": "Kullanıcı bulunamadı veya geçersiz alan"}), 404
    return jsonify({"ok": True, "updated": row})


@app.route("/admin/user/<int:user_id>", methods=["DELETE"])
@login_required
@admin_required
def admin_delete_user(user_id):
    if user_id == session.get("user_id"):
        return jsonify({"ok": False, "error": "Kendini silemezsin"}), 400
    if not get_db():
        return jsonify({"ok": False, "error": "DB bağlantısı yok"}), 503
    row = delete_user(user_id)
    if not row:
        return jsonify({"ok": False, "error": "Kullanıcı bulunamadı"}), 404
    return jsonify({"ok": True, "deleted": row})

# ═══════════════════════════════════════════════
# BAŞLATMA
# ═══════════════════════════════════════════════
# FİX: init_db() hatası uygulamayı çökertmesin.
#      DATABASE_URL yoksa mock mod devreye girer,
#      uygulama yine de açılır ve çalışır.
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"[Başlangıç] init_db atlandı: {e}")
        print("[Başlangıç] Mock mod aktif — DB olmadan çalışıyor.")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
