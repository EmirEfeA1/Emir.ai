"""
config.py — Emir.ai Merkezi Konfigürasyon
==========================================
app.py bu dosyadan Config sınıfını import eder.

Kullanım (app.py içinde):
    from config import get_config
    app.config.from_object(get_config())

Ortama göre otomatik sınıf seçimi:
    FLASK_ENV=development → DevelopmentConfig
    FLASK_ENV=production  → ProductionConfig
    diğer / boş          → DevelopmentConfig (güvenli default)
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    # ── Flask ──────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("SECRET_KEY", "emirai-super-secret-2025-CHANGE-ME")
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # ── Cookie ─────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE   = False    # Alt sınıfta override edilir
    SESSION_COOKIE_NAME     = "emirai_session"

    # ── Groq ───────────────────────────────────────────────────────
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

    # ── Veritabanı ─────────────────────────────────────────────────
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # ── Rate limiting ──────────────────────────────────────────────
    RATE_WINDOW  = 60     # saniye
    RATE_MAX     = 20     # pencere başına max istek

    # ── Model varsayılanları ───────────────────────────────────────
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

    # ── Mesaj limitleri ────────────────────────────────────────────
    DEFAULT_MESSAGE_LIMIT = 10
    ADMIN_MESSAGE_LIMIT   = 999999

    # ── Dosya yükleme ──────────────────────────────────────────────
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False      # HTTP üzerinde çalışır


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True       # HTTPS zorunlu

    # Production'da SECRET_KEY mutlaka set edilmeli
    @classmethod
    def validate(cls):
        key = cls.SECRET_KEY
        if "CHANGE-ME" in key or len(key) < 32:
            raise RuntimeError(
                "Production için güvenli SECRET_KEY gerekli!\n"
                "Üretmek: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not cls.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY ortam değişkeni set edilmemiş!")
        if not cls.DATABASE_URL:
            raise RuntimeError("DATABASE_URL ortam değişkeni set edilmemiş!")


class TestingConfig(BaseConfig):
    DEBUG   = True
    TESTING = True
    DATABASE_URL          = ""          # Test için DB kullanma
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED      = False


# ─── Fabrika fonksiyonu ────────────────────────────────────────────────────
_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}

def get_config():
    """
    FLASK_ENV'e göre doğru config sınıfını döner.
    Production'da validate() çağırarak eksik env var'ı yakalar.
    """
    env = os.getenv("FLASK_ENV", "development").lower()
    cfg = _CONFIG_MAP.get(env, DevelopmentConfig)
    if env == "production" and hasattr(cfg, "validate"):
        cfg.validate()
    return cfg
