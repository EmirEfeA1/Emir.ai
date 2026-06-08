/* ═══════════════════════════════════════
   Emir.ai — script.js
   Wave · State · Profile · Chat · TTS · Theme
═══════════════════════════════════════ */

/* ── Wave ─────────────────────────────── */
(function initWave() {
  const cv = document.getElementById('waveCanvas');
  if (!cv) return;
  const cx = cv.getContext('2d');
  let W, H, t = 0;
  const resize = () => { W = cv.width = innerWidth; H = cv.height = innerHeight; };
  resize(); addEventListener('resize', resize);
  const L = [
    { a: 85, f: 0.0035, s: 0.000771, y: .36, o: .46, r: 160, g: 148, b: 210 },
    { a: 58, f: 0.0055, s: 0.000515, y: .52, o: .32, r: 128, g: 116, b: 190 },
    { a: 40, f: 0.0080, s: 0.000945, y: .66, o: .22, r: 108, g: 96,  b: 168 },
    { a: 24, f: 0.0110, s: 0.000645, y: .79, o: .14, r: 88,  g: 76,  b: 145 },
    { a: 12, f: 0.0155, s: 0.001202, y: .90, o: .08, r: 218, g: 213, b: 255 },
  ];
  let last = 0;
  const draw = ts => {
    if (ts - last < 34) { requestAnimationFrame(draw); return; }
    last = ts;
    cx.clearRect(0, 0, W, H);
    L.forEach(l => {
      const by = H * l.y;
      cx.beginPath(); cx.moveTo(0, H);
      for (let x = 0; x <= W; x += 6) {
        const y = by
          + Math.sin(x * l.f + t * l.s * 60) * l.a
          + Math.sin(x * l.f * 2.4 + t * l.s * 40 + 1.3) * l.a * .26
          + Math.sin(x * l.f * .5 + t * l.s * 22) * l.a * .15;
        cx.lineTo(x, y);
      }
      cx.lineTo(W, H); cx.closePath();
      const g = cx.createLinearGradient(0, by - l.a * 1.3, 0, by + l.a * 2.2);
      g.addColorStop(0,   `rgba(${l.r},${l.g},${l.b},${l.o})`);
      g.addColorStop(.55, `rgba(${l.r},${l.g},${l.b},${l.o * .4})`);
      g.addColorStop(1,   `rgba(${l.r},${l.g},${l.b},0)`);
      cx.fillStyle = g; cx.fill();
    });
    t++; requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
})();

/* ── State ────────────────────────────── */
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
let profile = { name: 'Kullanıcı', avatar: '', customPrompt: '' };
let chats = {}, currentId = null, messages = [], tempAv = '';
let ttsEnabled = false, currentTier = 'balanced';
let currentTheme = 'dark';

try { profile  = { ...profile, ...JSON.parse(localStorage.getItem('ep') || '{}') }; } catch (e) {}
try { chats    = JSON.parse(localStorage.getItem('ec') || '{}'); } catch (e) {}
try { currentTheme = localStorage.getItem('theme') || 'dark'; } catch (e) {}

const save = {
  p: () => localStorage.setItem('ep', JSON.stringify(profile)),
  c: () => localStorage.setItem('ec', JSON.stringify(chats)),
};

/* ── Markdown parser (lightweight) ───── */
function parseMarkdown(text) {
  return text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="lang-${lang}">${escHtml(code.trim())}</code></pre>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^### (.+)$/gm, '<h4 style="font-size:14px;font-weight:600;margin:8px 0 4px;color:var(--t0)">$1</h4>')
    .replace(/^## (.+)$/gm,  '<h3 style="font-size:15px;font-weight:700;margin:10px 0 5px;color:var(--t0)">$1</h3>')
    .replace(/^# (.+)$/gm,   '<h2 style="font-size:17px;font-weight:700;margin:12px 0 6px;color:var(--t0)">$1</h2>')
    .replace(/^\|(.+)\|$/gm, row => {
      const cells = row.slice(1,-1).split('|').map(c => c.trim());
      return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
    })
    .replace(/(<tr>.*<\/tr>\n?)+/gs, match => `<table>${match}</table>`)
    .replace(/^- (.+)$/gm,   '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`)
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/^---$/gm, '<hr>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
}

function escHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ── Theme ────────────────────────────── */
function applyTheme(name) {
  document.body.classList.remove('theme-purple', 'theme-blackhole');
  if (name === 'purple')    document.body.classList.add('theme-purple');
  if (name === 'blackhole') document.body.classList.add('theme-blackhole');
  currentTheme = name;
  localStorage.setItem('theme', name);
  document.querySelectorAll('.theme-dot').forEach(d => {
    d.classList.toggle('active', d.dataset.theme === name);
  });
}
applyTheme(currentTheme);

/* ── TTS ──────────────────────────────── */
function toggleTts() {
  ttsEnabled = !ttsEnabled;
  document.getElementById('btnTts').classList.toggle('active', ttsEnabled);
  showToast(ttsEnabled ? '🔊 Sesli okuma açık' : '🔇 Sesli okuma kapalı');
}
function speak(text) {
  if (!ttsEnabled || !speechSynthesis) return;
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text.replace(/<[^>]*>/g, ''));
  utt.lang = 'tr-TR'; utt.rate = 1.05;
  const voices = speechSynthesis.getVoices();
  const tr = voices.find(v => v.lang.startsWith('tr'));
  if (tr) utt.voice = tr;
  speechSynthesis.speak(utt);
}

/* ── Toast ────────────────────────────── */
function showToast(msg, dur = 2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), dur);
}

/* ── Profile ──────────────────────────── */
function renderProfile() {
  const n = profile.name || 'Kullanıcı';
  const el = document.getElementById('sbAv');
  el.innerHTML = profile.avatar ? `<img src="${profile.avatar}" alt="">` : n[0].toUpperCase();
  document.getElementById('sbName').textContent = n;
}
function openModal() {
  document.getElementById('inName').value = profile.name || '';
  document.getElementById('inPrompt').value = profile.customPrompt || '';
  tempAv = profile.avatar || '';
  const p = document.getElementById('avPrev');
  p.innerHTML = tempAv
    ? `<img src="${tempAv}" alt="">`
    : `<span>${(profile.name || '?')[0].toUpperCase()}</span>`;
  document.getElementById('profileModal').classList.add('open');
}
function closeModal() { document.getElementById('profileModal').classList.remove('open'); }
function onAvPick(e) {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = ev => {
    tempAv = ev.target.result;
    document.getElementById('avPrev').innerHTML = `<img src="${tempAv}" alt="">`;
  };
  r.readAsDataURL(f);
}
function saveProfile() {
  profile.name         = document.getElementById('inName').value.trim() || 'Kullanıcı';
  profile.customPrompt = document.getElementById('inPrompt').value.trim();
  profile.avatar       = tempAv;
  save.p(); renderProfile(); closeModal();
  showToast('✅ Profil kaydedildi');
}

/* ── Chat History ─────────────────────── */
function newChat() {
  currentId = Date.now().toString(); messages = [];
  chats[currentId] = { title: 'Yeni Sohbet', messages: [], ts: Date.now() };
  save.c(); renderList(); renderChatUI(); closeSidebar();
}
function loadChat(id) {
  currentId = id; messages = chats[id].messages || [];
  renderChatUI(true);
  document.getElementById('topTitle').textContent = chats[id].title || 'Emir.ai';
  renderList(); closeSidebar();
  setTimeout(() => { document.getElementById('chat').scrollTop = 9e9; }, 80);
}
function deleteChat(id, e) {
  e.stopPropagation();
  const el = e.target.closest('.chat-item');
  if (el) {
    el.style.transition = 'all 0.2s ease';
    el.style.opacity = '0'; el.style.transform = 'translateX(-8px) scale(0.97)';
    setTimeout(() => {
      delete chats[id]; save.c();
      if (currentId === id) { currentId = null; messages = []; renderChatUI(); document.getElementById('topTitle').textContent = 'Emir.ai'; }
      renderList();
    }, 200);
  }
}

function startRename(id, titleEl) {
  titleEl.contentEditable = 'true';
  titleEl.focus();
  const sel = window.getSelection();
  sel.selectAllChildren(titleEl);
  titleEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); titleEl.blur(); }
  }, { once: true });
  titleEl.addEventListener('blur', () => {
    titleEl.contentEditable = 'false';
    const newTitle = titleEl.textContent.trim().slice(0, 40) || 'Sohbet';
    chats[id].title = newTitle; save.c();
    if (currentId === id) document.getElementById('topTitle').textContent = newTitle;
  }, { once: true });
}

function renderList() {
  const el = document.getElementById('chatList');
  const ids = Object.keys(chats).sort((a, b) => b - a);
  if (!ids.length) {
    el.innerHTML = '<div style="padding:16px 8px;text-align:center;font-size:12px;color:var(--t3)">Henüz sohbet yok</div>';
    return;
  }
  const today = new Date().toDateString();
  let html = '', tIds = [], pIds = [];
  ids.forEach(id => (new Date(+id).toDateString() === today ? tIds : pIds).push(id));
  const mkItems = arr => arr.map((id, i) => {
    const t = (chats[id].title || 'Sohbet').slice(0, 30);
    const a = id === currentId ? 'active' : '';
    return `<div class="chat-item ${a}" onclick="loadChat('${id}')" style="animation:wIn 0.22s var(--ease) ${i * 25}ms both">
      <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span class="ci-title" ondblclick="startRename('${id}', this)">${t}</span>
      <button class="ci-del" onclick="deleteChat('${id}',event)">×</button>
    </div>`;
  }).join('');
  if (tIds.length) html += '<div class="sb-label">Bugün</div>' + mkItems(tIds);
  if (pIds.length) html += '<div class="sb-label">Önceki</div>' + mkItems(pIds);
  el.innerHTML = html;
}

function renderChatUI(restore = false) {
  const chatEl = document.getElementById('chat');
  if (!restore || !messages.length) {
    const name = profile.name && profile.name !== 'Kullanıcı' ? `, ${profile.name}` : '';
    chatEl.innerHTML = `
      <div class="welcome" id="welcome">
        <div class="w-badge"><div class="w-bdot"></div>Emir.ai · Hazır</div>
        <h1 class="w-title">Merhaba${name}!<br>Nasıl yardımcı olabilirim?</h1>
        <p class="w-sub">Soru sor, araştır, yaz, analiz et — her şeye hazırım.</p>
        <div class="chip-grid">
          <div class="chip" onclick="quickSend(this)">🌤 Ankara hava durumu</div>
          <div class="chip" onclick="quickSend(this)">📰 Bugünkü haberler</div>
          <div class="chip" onclick="quickSend(this)">🤖 Kendini tanıt</div>
          <div class="chip" onclick="quickSend(this)">😄 Komik bir şaka yap</div>
          <div class="chip" onclick="quickSend(this)">💡 Python'da for döngüsü</div>
          <div class="chip" onclick="quickSend(this)">🎵 Müzik öner</div>
        </div>
      </div>`;
    return;
  }
  chatEl.innerHTML = '';
  messages.forEach(m => appendMsg(m.content, m.role === 'user' ? 'user' : 'bot', false));
}

/* ── Sidebar ──────────────────────────── */
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('mobOverlay').classList.toggle('open');
}
function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('mobOverlay').classList.remove('open');
}

/* ── Model tier ───────────────────────── */
function setTier(tier) {
  currentTier = tier;
  document.querySelectorAll('.model-btn').forEach(b => b.classList.toggle('active', b.dataset.tier === tier));
}

/* ── Input ────────────────────────────── */
const inputEl = document.getElementById('msgInput');
const btnSend = document.getElementById('btnSend');
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 150) + 'px';
});
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
function quickSend(el) {
  inputEl.value = el.textContent.replace(/^\S+\s*/, '').trim();
  sendMessage();
}

/* ── Image attach ─────────────────────── */
function handleAttach() {
  document.getElementById('imgFile').click();
}
document.getElementById('imgFile')?.addEventListener('change', async e => {
  const file = e.target.files[0]; if (!file) return;
  e.target.value = '';
  const reader = new FileReader();
  reader.onload = async ev => {
    const dataUrl = ev.target.result;
    const base64 = dataUrl.split(',')[1];
    const mime   = file.type;
    // Show preview in chat
    appendMsg(`<img src="${dataUrl}" style="max-width:220px;border-radius:8px;margin-bottom:4px"><br>📎 Görsel analiz isteniyor…`, 'user', true);
    appendTyping();
    try {
      const res  = await fetch('/vision', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: base64, mimeType: mime }),
      });
      const data = await res.json();
      removeTyping();
      const reply = data.description || data.error || 'Görsel analiz edilemedi.';
      messages.push({ role: 'user', content: '[Görsel gönderildi]' });
      messages.push({ role: 'assistant', content: reply });
      if (currentId) { chats[currentId].messages = messages; save.c(); }
      appendMsg(reply, 'bot', true);
      speak(reply);
    } catch {
      removeTyping();
      appendMsg('Görsel yüklenirken bir hata oluştu.', 'bot', true);
    }
  };
  reader.readAsDataURL(file);
});

/* ── Send message ─────────────────────── */
let abortController = null;

async function sendMessage() {
  const text = inputEl.value.trim(); if (!text) return;

  if (!currentId) {
    currentId = Date.now().toString();
    chats[currentId] = { title: text.slice(0, 32), messages: [], ts: Date.now() };
    save.c(); renderList();
  }
  if (!messages.length) {
    chats[currentId].title = text.slice(0, 32);
    document.getElementById('topTitle').textContent = chats[currentId].title;
  }

  inputEl.value = ''; inputEl.style.height = 'auto'; btnSend.disabled = true;
  document.getElementById('welcome')?.remove();

  messages.push({ role: 'user', content: text });
  chats[currentId].messages = messages; save.c();
  appendMsg(text, 'user', true);
  appendTyping();

  abortController = new AbortController();
  let fullReply = '';
  let botEl = null;
  let searchActive = false;

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: abortController.signal,
      body: JSON.stringify({
        messages,
        customPrompt: profile.customPrompt || '',
        userName:     profile.name !== 'Kullanıcı' ? profile.name : '',
        modelTier:    currentTier,
      }),
    });

    const reader = res.body.getReader();
    const dec    = new TextDecoder();
    let buf      = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim(); if (!raw) continue;
        let evt;
        try { evt = JSON.parse(raw); } catch { continue; }

        if (evt.type === 'search') {
          // Show search indicator
          searchActive = true;
          removeTyping();
          botEl = appendStreamBubble();
          const badge = document.createElement('div');
          badge.className = 'search-badge';
          badge.innerHTML = '<div class="search-spin"></div> İnternette aranıyor…';
          botEl.querySelector('.bubble').prepend(badge);
        } else if (evt.type === 'token') {
          if (!botEl) { removeTyping(); botEl = appendStreamBubble(); }
          fullReply += evt.text;
          const bubble = botEl.querySelector('.bubble');
          // Remove search badge when first token arrives
          bubble.querySelector('.search-badge')?.remove();
          bubble.innerHTML = parseMarkdown(fullReply) + '<span class="cursor"></span>';
          document.getElementById('chat').scrollTop = 9e9;
        } else if (evt.type === 'done') {
          if (botEl) {
            const bubble = botEl.querySelector('.bubble');
            bubble.querySelector('.cursor')?.remove();
            bubble.innerHTML = parseMarkdown(fullReply);
            addImgClickHandlers(bubble);
          }
          messages.push({ role: 'assistant', content: fullReply });
          chats[currentId].messages = messages; save.c();
          speak(fullReply);
          renderList();
          autoTitle();
        } else if (evt.type === 'error') {
          removeTyping();
          appendMsg(evt.message || 'Bir hata oluştu.', 'bot', true);
        }
      }
    }
  } catch (err) {
    if (err.name !== 'AbortError') {
      removeTyping();
      appendMsg('Bağlantı hatası. Flask çalışıyor mu?', 'bot', true);
    }
  }

  btnSend.disabled = false; inputEl.focus();
}

/* ── Auto title (after 2 msgs) ────────── */
let titleGenerated = false;
async function autoTitle() {
  if (titleGenerated || messages.length < 4) return;
  titleGenerated = true;
  try {
    const res  = await fetch('/title', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: messages.slice(0, 4) }),
    });
    const data = await res.json();
    if (data.title && currentId) {
      chats[currentId].title = data.title; save.c();
      document.getElementById('topTitle').textContent = data.title;
      renderList();
    }
  } catch {}
}

/* ── Message DOM helpers ──────────────── */
function userAvHTML() {
  if (profile.avatar) return `<img src="${profile.avatar}" alt="">`;
  return (profile.name || 'K')[0].toUpperCase();
}

function appendMsg(html, role, animate) {
  const chatEl = document.getElementById('chat');
  const isUser = role === 'user';
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  if (!animate || REDUCED) el.style.animation = 'none';
  el.innerHTML = `<div class="msg-av">${isUser ? userAvHTML() : 'E'}</div><div class="bubble">${isUser ? escHtml(html).replace(/\n/g,'<br>') : parseMarkdown(html)}</div>`;
  chatEl.appendChild(el);
  chatEl.scrollTop = chatEl.scrollHeight;
  addImgClickHandlers(el.querySelector('.bubble'));
  return el;
}

function appendStreamBubble() {
  const chatEl = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = 'msg bot'; el.id = 'streamMsg';
  el.innerHTML = `<div class="msg-av">E</div><div class="bubble"></div>`;
  chatEl.appendChild(el);
  chatEl.scrollTop = chatEl.scrollHeight;
  return el;
}

function appendTyping() {
  const chatEl = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = 'typing-wrap'; el.id = 'typing';
  el.innerHTML = `<div class="typing-av">E</div><div class="typing-bubble"><span></span><span></span><span></span></div>`;
  chatEl.appendChild(el); chatEl.scrollTop = chatEl.scrollHeight;
}
function removeTyping() { document.getElementById('typing')?.remove(); }

/* ── Image fullscreen ─────────────────── */
function addImgClickHandlers(el) {
  if (!el) return;
  el.querySelectorAll('img').forEach(img => {
    img.style.cursor = 'zoom-in';
    img.onclick = () => openViewer(img.src);
  });
}
function openViewer(src) {
  const v = document.getElementById('viewer');
  v.querySelector('img').src = src;
  v.classList.add('open');
}
function closeViewer() { document.getElementById('viewer').classList.remove('open'); }

/* ── Login ────────────────────────────── */
async function doLogin() {
  const u = document.getElementById('loginUser').value.trim();
  const p = document.getElementById('loginPass').value;
  const remember = document.getElementById('rememberMe')?.checked || false;
  const errEl = document.getElementById('loginErr');
  try {
    const res  = await fetch('/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p, remember }),
    });
    const data = await res.json();
    if (data.ok) {
      document.getElementById('loginScreen').remove();
      profile.name = data.username !== 'demo' ? data.username : profile.name;
      renderProfile(); renderChatUI();
      if (data.isAdmin) showToast('👑 Admin olarak giriş yapıldı');
    } else {
      errEl.textContent = data.error || 'Hatalı giriş';
      errEl.classList.add('show');
    }
  } catch {
    errEl.textContent = 'Sunucuya bağlanılamadı';
    errEl.classList.add('show');
  }
}
document.getElementById('loginPass')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});

/* ── Init ─────────────────────────────── */
renderProfile();
renderList();
renderChatUI();
setTier('balanced');
