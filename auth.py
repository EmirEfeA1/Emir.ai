"""
auth.py — Emir.ai Kimlik Doğrulama Katmanı
===========================================
Bu dosya yalnızca Flask Blueprint ve auth
fonksiyonlarını içerir. app.py'ye blueprint
olarak register edilir.

Neden Blueprint:
  - Auth route'ları app.py'yi şişirmesin
  - Test etmesi kolay (ayrı import edilebilir)
  - İleride FastAPI'a geçişte sadece bu dosya değişir

Endpoints:
  POST /register   → Yeni kayıt
  POST /login      → Giriş
  POST /logout     → Çıkış
  GET  /me         → Mevcut kullanıcı bilgisi

Middleware:
  login_required   → Decorator
  admin_required   → Decorator
  get_current_user → Yardımcı fonksiyon
"""

import functools
import hashlib
from flask import Blueprint, request, jsonify, session

# db.py'den fonksiyonları al
from db import (
    get_db,
    _hash_pw,
    _check_pw,
    get_user_by_id,
    get_user_by_username_or_email,
    create_user,
    update_last_login,
    reset_daily_if_needed,
    PG_AVAILABLE,
)

# ── Blueprint ──────────────────────────────────────
auth_bp = Blueprint("auth", __name__)


# ═══════════════════════════════════════════════════
# MOCK KULLANICI TABLOSU (DB yokken fallback)
# Neden: Geliştirme ortamında PostgreSQL olmayabilir.
#        SHA-256 hash, production'da bcrypt olur.
# İleride kaldırılacak; PostgreSQL geçince silinir.
# ═══════════════════════════════════════════════════
MOCK_USERS = {
    "demo": {
        "id":             2,
        "username":       "demo",
        "email":          "demo@emir.ai",
        "password_hash":  hashlib.sha256("demo123".encode()).hexdigest(),
        "role":           "user",
        "is_premium":     False,
        "message_limit":  10,
        "messages_today": 0,
    },
    "admin": {
        "id":             1,
        "username":       "admin",
        "email":          "admin@emir.ai",
        "password_hash":  hashlib.sha256("admin1234".encode()).hexdigest(),
        "role":           "admin",
        "is_premium":     True,
        "message_limit":  999999,
        "messages_today": 0,
    },
}


# ═══════════════════════════════════════════════════
# MİDDLEWARE
# ═══════════════════════════════════════════════════
def login_required(f):
    """
    Decorator: Session'da user_id yoksa 401 döner.

    Kullanım:
        @app.route("/chat", methods=["POST"])
        @login_required
        def chat(): ...
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({
                "error": "Giriş yapman gerekiyor",
                "code":  "UNAUTHORIZED",
            }), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """
    Decorator: Sadece role='admin' kullanıcılara izin verir.
    login_required'dan SONRA zincire eklenir.

    Kullanım:
        @app.route("/admin/users")
        @login_required
        @admin_required
        def admin_users(): ...
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({
                "error": "Yetkisiz erişim",
                "code":  "FORBIDDEN",
            }), 403
        return f(*args, **kwargs)
    return wrapper


def get_current_user() -> dict | None:
    """
    Session'daki user_id ile veritabanından güncel kullanıcı çeker.
    DB yoksa session bilgisini dict olarak döner (offline fallback).

    Neden her seferinde DB sorgusu:
      - Kullanıcı rol/limit değişmişse anında yansısın.
      - Session cache → tutarsızlık yaratır.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = get_user_by_id(user_id)
    if user:
        return user

    # DB yoksa session'dan bilgi al
    return {
        "id":             user_id,
        "username":       session.get("username", ""),
        "email":          session.get("email", ""),
        "role":           session.get("role", "user"),
        "is_premium":     session.get("is_premium", False),
        "message_limit":  session.get("message_limit", 10),
        "messages_today": session.get("messages_today", 0),
    }


def _set_session(user: dict, remember: bool = False):
    """
    Session'a kullanıcı bilgilerini yaz.
    Tek noktada yönetim → tutarsızlık önlenir.
    """
    session.permanent          = remember
    session["user_id"]         = user["id"]
    session["username"]        = user["username"]
    session["email"]           = user.get("email", "")
    session["role"]            = user.get("role", "user")
    session["is_premium"]      = user.get("is_premium", False)
    session["message_limit"]   = user.get("message_limit", 10)
    session["messages_today"]  = user.get("messages_today", 0)


# ═══════════════════════════════════════════════════
# ROUTE'LAR
# ═══════════════════════════════════════════════════

@auth_bp.route("/register", methods=["POST"])
def register():
    """
    Yeni kullanıcı kaydı.

    Request body: { username, email, password }

    Validasyon:
      - username: 3-32 karakter, [a-z0-9_]
      - email:    @ içermeli
      - password: min 6 karakter

    Response: { ok, username, role } | { ok, error }
    """
    data     = request.json or {}
    username = data.get("username", "").strip().lower()
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")

    # ── Validasyon ──────────────────────────────
    import re
    if not username or len(username) < 3:
        return jsonify({"ok": False, "error": "Kullanıcı adı en az 3 karakter olmalı"}), 400
    if len(username) > 32:
        return jsonify({"ok": False, "error": "Kullanıcı adı en fazla 32 karakter olabilir"}), 400
    if not re.match(r"^[a-z0-9_]+$", username):
        return jsonify({"ok": False, "error": "Kullanıcı adında sadece harf, rakam ve _ kullanabilirsin"}), 400
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Geçerli bir e-posta gir"}), 400
    if not password or len(password) < 6:
        return jsonify({"ok": False, "error": "Şifre en az 6 karakter olmalı"}), 400

    # ── DB yoksa mock kayıt ──────────────────────
    if not PG_AVAILABLE or not get_db():
        mock_user = {
            "id":             999,
            "username":       username,
            "email":          email,
            "role":           "user",
            "is_premium":     False,
            "message_limit":  10,
            "messages_today": 0,
        }
        _set_session(mock_user, remember=False)
        return jsonify({"ok": True, "username": username, "role": "user"})

    # ── DB kaydı ────────────────────────────────
    try:
        user = create_user(username, email, password)
        if not user:
            return jsonify({"ok": False, "error": "Kayıt başarısız, tekrar dene"}), 500
        user["messages_today"] = 0
        _set_session(user, remember=False)
        return jsonify({"ok": True, "username": user["username"], "role": user["role"]})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    except Exception as e:
        print(f"[Auth] register hatası: {e}")
        return jsonify({"ok": False, "error": "Kayıt başarısız, tekrar dene"}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Kullanıcı girişi.

    Request body: { username (veya email), password, remember? }
    remember: true → session 30 gün kalıcı

    Response: { ok, username, role, isAdmin, isPremium, limit, used } | { ok, error }

    Not: username ve email ile login destekler.
    Admin girişi: isAdmin: true döner → admin panelini aç.
    """
    data     = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    remember = bool(data.get("remember", False))

    if not username or not password:
        return jsonify({"ok": False, "error": "Kullanıcı adı ve şifre gerekli"}), 400

    conn = get_db()

    # ── DB yoksa mock sistemi ────────────────────
    if not conn:
        mock = MOCK_USERS.get(username)
        if mock and _check_pw(password, mock["password_hash"]):
            _set_session(mock, remember=remember)
            return jsonify({
                "ok":       True,
                "username": mock["username"],
                "role":     mock["role"],
                "isAdmin":  mock["role"] == "admin",
                "isPremium":mock["is_premium"],
                "limit":    mock["message_limit"],
                "used":     0,
            })
        return jsonify({"ok": False, "error": "Kullanıcı adı veya şifre yanlış"}), 401

    # ── DB ile doğrulama ─────────────────────────
    try:
        user = get_user_by_username_or_email(username)

        if not user or not _check_pw(password, user["password_hash"]):
            return jsonify({"ok": False, "error": "Kullanıcı adı veya şifre yanlış"}), 401

        # Son giriş güncelle (arka planda, hata önemsiz)
        update_last_login(user["id"])

        # Günlük sıfırlama
        try:
            reset_daily_if_needed(conn, user["id"])
            conn.commit()
        except Exception:
            pass

        _set_session(user, remember=remember)

        return jsonify({
            "ok":        True,
            "username":  user["username"],
            "role":      user["role"],
            "isAdmin":   user["role"] == "admin",
            "isPremium": user["is_premium"],
            "limit":     user["message_limit"],
            "used":      user.get("messages_today", 0),
        })

    except Exception as e:
        print(f"[Auth] login hatası: {e}")
        return jsonify({"ok": False, "error": "Giriş başarısız, tekrar dene"}), 500
    finally:
        if not conn.closed:
            conn.close()


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Oturumu kapat. Session'ı temizler.
    Cookie httpOnly olduğu için JS bu cookie'yi temizleyemez;
    sunucu tarafında session.clear() şart.
    """
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    """
    Mevcut kullanıcı bilgisi.

    Frontend sayfa yenilendiğinde bu endpoint'i çağırır:
      - 200 → kullanıcı giriş yapmış, bilgilerini ver
      - 401 → session yok, login ekranını göster

    Ayrıca günlük sayacı sıfırlar (gün değiştiyse).
    """
    user = get_current_user()
    if not user:
        session.clear()
        return jsonify({"ok": False, "error": "Kullanıcı bulunamadı"}), 401

    # Günlük sıfırlama
    conn = get_db()
    if conn:
        try:
            reset_daily_if_needed(conn, user["id"])
            conn.commit()
            # Güncel sayacı al
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor()
            cur.execute(
                "SELECT messages_today, message_limit FROM users WHERE id = %s",
                (user["id"],)
            )
            fresh = cur.fetchone()
            if fresh:
                user["messages_today"] = fresh["messages_today"]
                user["message_limit"]  = fresh["message_limit"]
        except Exception:
            pass
        finally:
            if not conn.closed:
                conn.close()

    remaining = max(0, user["message_limit"] - user["messages_today"])

    return jsonify({
        "ok":        True,
        "id":        user["id"],
        "username":  user["username"],
        "email":     user.get("email", ""),
        "role":      user["role"],
        "isAdmin":   user["role"] == "admin",
        "isPremium": user["is_premium"],
        "limit":     user["message_limit"],
        "used":      user["messages_today"],
        "remaining": remaining,
    })
