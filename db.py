"""
db.py — Emir.ai Veritabanı Katmanı
====================================
Bu dosya app.py'den bağımsız tutulur.
İleride:  psycopg2 → asyncpg / SQLAlchemy ORM
          DATABASE_URL → Supabase / PlanetScale
değişimi yapılırken sadece bu dosya değişir.

Fonksiyonlar:
  get_db()              → Bağlantı döner (veya None)
  init_db()             → Tabloları oluşturur, admin seed
  _hash_pw(plain)       → bcrypt hash (fallback: SHA-256)
  _check_pw(plain,hash) → Şifre doğrulama
  get_current_user()    → Session'dan DB kullanıcısı
  reset_daily_if_needed → Günlük sayaç sıfırlama
"""

import os
import hashlib
from datetime import date
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("sql7.freesqldatabase.com", "")

# ── psycopg2 ────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False
    print("[DB] psycopg2 yüklü değil — veritabanı devre dışı.")

# ── bcrypt ──────────────────────────────────────────
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    print("[DB] bcrypt yüklü değil — SHA-256 fallback kullanılıyor. "
          "Production için: pip install bcrypt")


# ═══════════════════════════════════════════════════
# BAĞLANTI
# ═══════════════════════════════════════════════════
def get_db():
    """
    Yeni bir psycopg2 bağlantısı açar ve döner.

    Neden yeni bağlantı her seferinde:
      - Flask thread-safe değil; connection pooling
        için pgbouncer veya SQLAlchemy kullanılabilir.
      - Şimdilik basit tut: aç → kullan → kapat.

    Dönüş: psycopg2 connection (autocommit=False) | None
    """
    if not PG_AVAILABLE or not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"[DB] get_db bağlantı hatası: {e}")
        return None


# ═══════════════════════════════════════════════════
# TABLO OLUŞTURMA
# ═══════════════════════════════════════════════════
def init_db():
    """
    Uygulama başlarken çağrılır.
    IF NOT EXISTS → tekrar çalıştırılsa sorun olmaz.

    Tablo tasarımı notu:
      - message_limit  : kullanıcı bazlı günlük kota
      - messages_today : bugün kullanılan mesaj sayısı
      - last_reset     : son sıfırlama tarihi (DATE)
      → Gün değişince messages_today sıfırlanır.

    Gelecek göç için:
      - is_premium → subscription_tier (free/pro/team)
      - last_login → login_history tablosu
    """
    conn = get_db()
    if not conn:
        print("[DB] Bağlantı yok — tablo oluşturma atlandı.")
        return

    try:
        cur = conn.cursor()

        # ── Kullanıcı tablosu ──────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id             SERIAL       PRIMARY KEY,
                username       VARCHAR(32)  UNIQUE NOT NULL,
                email          VARCHAR(120) UNIQUE NOT NULL,
                password_hash  VARCHAR(256) NOT NULL,
                role           VARCHAR(16)  NOT NULL DEFAULT 'user',
                is_premium     BOOLEAN      NOT NULL DEFAULT FALSE,
                message_limit  INT          NOT NULL DEFAULT 10,
                messages_today INT          NOT NULL DEFAULT 0,
                last_reset     DATE         NOT NULL DEFAULT CURRENT_DATE,
                created_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
                last_login     TIMESTAMP
            );
        """)

        # ── Admin seed ──────────────────────────────
        # Önce placeholder ile ekle, sonra gerçek hash ile güncelle.
        # ON CONFLICT → zaten varsa dokunma.
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, message_limit)
            VALUES (
                'admin',
                'admin@emir.ai',
                '__PLACEHOLDER__',
                'admin',
                999999
            )
            ON CONFLICT (username) DO NOTHING;
        """)

        admin_hash = _hash_pw("admin1234")
        cur.execute("""
            UPDATE users
            SET password_hash = %s
            WHERE username = 'admin'
              AND password_hash = '__PLACEHOLDER__'
        """, (admin_hash,))

        conn.commit()
        print("[DB] Tablolar hazır ✓")

    except Exception as e:
        conn.rollback()
        print(f"[DB] init_db hatası: {e}")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════
# ŞİFRE YARDIMCILARI
# ═══════════════════════════════════════════════════
def _hash_pw(plain: str) -> str:
    """
    Şifreyi hashler.
    bcrypt varsa: bcrypt (cost=12) — güvenli, yavaş (kasıtlı).
    yoksa: SHA-256 — sadece geliştirme ortamı için!
    """
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(
            plain.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
    # Fallback (production'da kullanma!)
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _check_pw(plain: str, hashed: str) -> bool:
    """
    Şifre doğrulama.
    bcrypt hash'i "$2b$" veya "$2a$" ile başlar.
    Değilse SHA-256 karşılaştırır (eski/mock hesaplar için).
    """
    if BCRYPT_AVAILABLE and hashed.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
    # SHA-256 fallback
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == hashed


# ═══════════════════════════════════════════════════
# KULLANICI SORGULARI
# ═══════════════════════════════════════════════════
def get_user_by_id(user_id: int) -> dict | None:
    """
    ID ile kullanıcı çek.
    Dönüş: dict | None
    """
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, role, is_premium,
                   message_limit, messages_today, last_reset,
                   last_login, created_at
            FROM users WHERE id = %s
        """, (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB] get_user_by_id hatası: {e}")
        return None
    finally:
        conn.close()


def get_user_by_username_or_email(identifier: str) -> dict | None:
    """
    Username veya email ile kullanıcı çek.
    Login endpoint'i her ikisini de destekler.
    """
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, password_hash, role,
                   is_premium, message_limit, messages_today, last_reset
            FROM users
            WHERE username = %s OR email = %s
        """, (identifier, identifier))
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB] get_user hatası: {e}")
        return None
    finally:
        conn.close()


def create_user(username: str, email: str, password: str,
                role: str = "user", message_limit: int = 10) -> dict | None:
    """
    Yeni kullanıcı oluştur.
    Dönüş: oluşturulan kullanıcı dict | None (hata veya çakışma)
    Raises: ValueError → username/email çakışması
    """
    conn = get_db()
    if not conn:
        return None
    try:
        pw_hash = _hash_pw(password)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, message_limit)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, username, email, role, is_premium, message_limit
        """, (username, email, pw_hash, role, message_limit))
        user = dict(cur.fetchone())
        conn.commit()
        return user
    except psycopg2.errors.UniqueViolation as e:
        conn.rollback()
        err = str(e).lower()
        if "username" in err:
            raise ValueError("Bu kullanıcı adı alınmış")
        if "email" in err:
            raise ValueError("Bu e-posta zaten kayıtlı")
        raise ValueError("Kayıt çakışması")
    except Exception as e:
        conn.rollback()
        print(f"[DB] create_user hatası: {e}")
        return None
    finally:
        conn.close()


def update_last_login(user_id: int):
    """Son giriş zamanını güncelle. Hata sessizce yututur."""
    conn = get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[DB] update_last_login hatası: {e}")
    finally:
        conn.close()


def reset_daily_if_needed(conn, user_id: int):
    """
    Gün değiştiyse messages_today = 0 yap.
    Neden ayrı fonksiyon: chat, /me ve register sırasında
    aynı mantığa ihtiyaç var; DRY prensibi.

    Önemli: Dışarıdan alınan conn kullanır (commit çağıranın sorumluluğunda).
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT last_reset FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row and row["last_reset"] < date.today():
            cur.execute(
                "UPDATE users SET messages_today = 0, last_reset = CURRENT_DATE WHERE id = %s",
                (user_id,)
            )
    except Exception as e:
        print(f"[DB] reset_daily_if_needed hatası: {e}")


def get_all_users_for_admin() -> list[dict]:
    """
    Admin paneli için tüm kullanıcıları çek.
    datetime alanları isoformat string'e çevrilir (JSON serializable).
    """
    conn = get_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, email, role, is_premium,
                   message_limit, messages_today, created_at, last_login
            FROM users
            ORDER BY created_at DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k in ("created_at", "last_login"):
                if r[k]:
                    r[k] = r[k].isoformat()
        return rows
    except Exception as e:
        print(f"[DB] get_all_users hatası: {e}")
        return []
    finally:
        conn.close()


def patch_user(user_id: int, updates: dict) -> dict | None:
    """
    Kullanıcı alanlarını güncelle.
    updates: { is_premium, message_limit, role } (herhangi biri)
    Dönüş: güncellenmiş satır | None
    """
    ALLOWED = {"is_premium", "message_limit", "role"}
    safe = {k: v for k, v in updates.items() if k in ALLOWED}
    if not safe:
        return None

    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        set_parts = [f"{k} = %s" for k in safe]
        vals = list(safe.values()) + [user_id]
        cur.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id = %s RETURNING id, username",
            vals
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        print(f"[DB] patch_user hatası: {e}")
        return None
    finally:
        conn.close()


def delete_user(user_id: int) -> dict | None:
    """
    Kullanıcıyı sil.
    Dönüş: silinen kullanıcı { id, username } | None
    """
    conn = get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM users WHERE id = %s RETURNING id, username",
            (user_id,)
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        print(f"[DB] delete_user hatası: {e}")
        return None
    finally:
        conn.close()


def get_stats() -> dict:
    """
    Admin dashboard özet istatistikleri.
    Dönüş: { total_users, premium_users, admin_users, messages_today }
    """
    conn = get_db()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM users")
        total = cur.fetchone()["n"]

        cur.execute("SELECT COUNT(*) AS n FROM users WHERE is_premium = TRUE")
        premium = cur.fetchone()["n"]

        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
        admins = cur.fetchone()["n"]

        cur.execute("SELECT COALESCE(SUM(messages_today), 0) AS n FROM users")
        today_msgs = cur.fetchone()["n"]

        return {
            "total_users":    int(total),
            "premium_users":  int(premium),
            "admin_users":    int(admins),
            "messages_today": int(today_msgs),
        }
    except Exception as e:
        print(f"[DB] get_stats hatası: {e}")
        return {}
    finally:
        conn.close()
