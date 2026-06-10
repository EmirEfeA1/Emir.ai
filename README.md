# Emir.ai

Groq üzerinde çalışan, PostgreSQL destekli, Türkçe yapay zeka chat uygulaması.

---

## Klasör Yapısı

```
emirai/
├── app.py              # Flask ana uygulama, chat & admin route'ları
├── auth.py             # Kimlik doğrulama Blueprint (/register /login /logout /me)
├── db.py               # Veritabanı katmanı (psycopg2 + bcrypt)
├── config.py           # Merkezi konfigürasyon (Dev / Prod / Test)
│
├── static/
│   ├── index.html      # Ana chat arayüzü
│   ├── admin.html      # Admin paneli
│   ├── script.js       # Frontend JS
│   ├── style.css       # Stiller
│   └── logo.png        # (eklemen gerekirse)
│
├── requirements.txt    # Python bağımlılıkları
├── Procfile            # Render / Railway / Heroku deploy
├── .env.example        # Ortam değişkenleri şablonu
├── .env                # GERÇEK değerler (git'e ekleme!)
├── .gitignore
└── README.md
```

> `index.html`, `admin.html`, `script.js`, `style.css` → `static/` klasörüne gider.  
> `app.py` `static_folder="static"` ile serve eder.

---

## Kurulum (Yerel Geliştirme)

### 1. Gereksinimler
- Python 3.11+
- PostgreSQL 14+ (opsiyonel; yoksa mock kullanıcı sistemi devreye girer)

### 2. Repoyu klonla ve ortamı kur

```bash
git clone https://github.com/kullanici/emirai.git
cd emirai

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Ortam değişkenlerini ayarla

```bash
cp .env.example .env
```

`.env` dosyasını aç ve şu alanları doldur:

| Değişken | Açıklama | Zorunlu |
|---|---|---|
| `SECRET_KEY` | Flask session anahtarı (min 32 karakter) | ✅ |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys | ✅ |
| `DATABASE_URL` | PostgreSQL bağlantı URL'i | Opsiyonel |
| `FLASK_ENV` | `development` veya `production` | Opsiyonel |

SECRET_KEY üretmek için:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Veritabanı (opsiyonel)

```bash
# PostgreSQL kuruluysa:
createdb emirai

# .env'de DATABASE_URL'i ayarla:
# DATABASE_URL=postgresql://postgres:sifre@localhost:5432/emirai
```

Tablolar uygulama ilk açıldığında otomatik oluşturulur (`init_db()`).

Varsayılan admin hesabı: `admin` / `admin1234` → **ilk girişte şifreyi değiştir!**

### 5. Çalıştır

```bash
# Geliştirme
python app.py

# VEYA (önerilen)
flask run --host=0.0.0.0 --port=5000
```

Tarayıcıda aç: http://localhost:5000

---

## Production Deploy (Render)

1. [render.com](https://render.com) → New → Web Service
2. Repoyu bağla
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `gunicorn app:app --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:$PORT --timeout 120`
5. Environment Variables bölümünde `.env` değerlerini ekle
6. PostgreSQL: Render → New → PostgreSQL → `DATABASE_URL`'yi kopyala

---

## API Endpoint'leri

### Auth
| Method | URL | Açıklama |
|---|---|---|
| POST | `/register` | Yeni kayıt `{username, email, password}` |
| POST | `/login` | Giriş `{username, password, remember?}` |
| POST | `/logout` | Oturum kapat |
| GET | `/me` | Mevcut kullanıcı bilgisi |

### Chat
| Method | URL | Açıklama |
|---|---|---|
| POST | `/chat` | SSE stream `{messages, modelTier, customPrompt, userName}` |
| POST | `/vision` | Görsel analiz `{image (base64), mimeType, question}` |
| POST | `/title` | Sohbet başlığı üret `{messages}` |

### Admin *(login_required + admin_required)*
| Method | URL | Açıklama |
|---|---|---|
| GET | `/admin/stats` | Dashboard istatistikleri |
| GET | `/admin/users` | Tüm kullanıcılar |
| PATCH | `/admin/user/<id>` | Kullanıcı güncelle `{is_premium, message_limit, role}` |
| DELETE | `/admin/user/<id>` | Kullanıcı sil |

---

## Güvenlik Notları

- `SECRET_KEY` production'da mutlaka güçlü bir değer olmalı
- `SESSION_COOKIE_SECURE=True` → sadece HTTPS üzerinden çalışır (production otomatik)
- Admin şifresi ilk kurulumda `admin1234` — **değiştir**
- `bcrypt` kurulu değilse SHA-256 fallback devreye girer — production'da `bcrypt` şart
- `DATABASE_URL` boşsa mock sistem çalışır, veriler kalıcı değil

---

## Geliştirme Notları

- DB katmanı değişimi: sadece `db.py` → SQLAlchemy/asyncpg geçişi
- Auth değişimi: sadece `auth.py` → JWT/FastAPI geçişi
- Yeni model eklemek: `app.py → MODEL_TIERS` sözlüğü
