"use strict";

// ============ Durum ============
const state = {
  rows: [],        // yüklenen satırlar
  results: [],     // rows ile aynı indeksli sonuçlar (null = bekliyor)
  categories: {},  // {1: "Kişisel Veri", ...}
  page: 1,
  pageSize: 50,
  running: false,
  stopRequested: false,
  fileName: "",
};

const CHUNK_SIZE = 100;   // /api/classify'a tek istekte gönderilen satır sayısı
const CONCURRENCY = 3;    // eşzamanlı istek sayısı

const $ = (id) => document.getElementById(id);

// ============ Tema (açık / koyu) ============
// Öncelik: URL ?theme=... (test/paylaşım) > localStorage > işletim sistemi tercihi.
(function initTheme() {
  const fromUrl = new URLSearchParams(location.search).get("theme");
  const saved = fromUrl === "dark" || fromUrl === "light"
    ? fromUrl : localStorage.getItem("ki-theme");
  if (saved === "dark" || saved === "light") {
    document.documentElement.dataset.theme = saved;
  }
})();

function effectiveTheme() {
  return document.documentElement.dataset.theme ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function syncThemeButton() {
  const btn = $("themeToggle");
  if (!btn) return;
  const dark = effectiveTheme() === "dark";
  btn.textContent = dark ? "☀" : "☾";
  btn.title = dark ? "Açık temaya geç" : "Koyu temaya geç";
}

document.addEventListener("DOMContentLoaded", () => {
  syncThemeButton();
  const btn = $("themeToggle");
  if (btn) btn.addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("ki-theme", next);
    syncThemeButton();
  });
});

// Güven eşikleri — backend ile hizalı (config.JUDGE_THRESHOLD=0.75):
// < CONF_LOW hakem bölgesi/insan incelemesi ister; >= CONF_HIGH net karar.
const CONF_LOW = 0.75, CONF_HIGH = 0.9;

// ============ Yardımcılar ============
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let toastTimer;
function toast(msg, isError = false) {
  let el = document.querySelector(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.appendChild(el); }
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

async function api(path, options = {}) {
  // Sunucu APP_API_TOKEN ile korunuyorsa token'ı bir kez sorup localStorage'da tut
  const headers = { ...(options.headers || {}) };
  const saved = localStorage.getItem("apiToken");
  if (saved) headers["X-API-Token"] = saved;
  let resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    const entered = prompt("Bu sunucu API token istiyor. Token'ı girin:");
    if (entered) {
      localStorage.setItem("apiToken", entered);
      headers["X-API-Token"] = entered;
      resp = await fetch(path, { ...options, headers });
    }
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch { /* yut */ }
    if (resp.status === 401) localStorage.removeItem("apiToken");
    throw new Error(detail);
  }
  return resp;
}

function badgeHtml(result) {
  if (!result) return '<span class="badge none">bekliyor</span>';
  if (result.kaynak === "hata") return '<span class="badge err">hata</span>';
  if (!result.kategoriler.length) return '<span class="badge none">kategorisiz</span>';
  const ana = result.ana_kategori;
  const parts = [];
  if (ana) parts.push(`<span class="badge c${ana}" title="Ana kategori">${ana}. ${esc(state.categories[ana] || "")}</span>`);
  result.kategoriler.filter((c) => c !== ana).forEach((c) =>
    parts.push(`<span class="badge sec c${c}" title="Olası kategori">${c}. ${esc(state.categories[c] || "")}</span>`));
  if (result.teknik) parts.push('<span class="badge tek" title="Teknik/işlemsel kolon">teknik</span>');
  return parts.join("");
}

function acilimHtml(result) {
  if (!result || result.kaynak === "hata") return "";
  return result.acilim ? esc(result.acilim)
    : '<span class="acilim-missing">açılım bulunamadı</span>';
}

function confHtml(result) {
  if (!result || result.kaynak === "hata") return "";
  const v = result.guven;
  const cls = v < CONF_LOW ? "low" : v < CONF_HIGH ? "mid" : "high";
  const src = { "llm+hakem": "hakem" }[result.kaynak] || "";
  return `<span class="conf ${cls}" title="Güven: kazanan kategorinin olasılığı">
      <i class="conf-bar"><b style="width:${Math.round(v * 100)}%"></b></i>${v.toFixed(2)}</span>` +
    (src ? `<span class="src-tag">${src}</span>` : "");
}

// Olasılık dağılımı (tekil sorgu için): tüm 7 kategori, her birine atanan olasılık,
// azalan sırada. Model olasılık döndürmediyse "olasılık bilgisi yok" uyarısı.
function probsHtml(result) {
  if (!result || result.kaynak === "hata") return "";
  const olas = result.olasiliklar || {};
  if (!Object.keys(olas).length) {
    return '<span class="prob-empty">Model olasılık dağılımı döndürmedi (eski format veya önbellek).</span>';
  }
  // 7 kategori tam listesi — verilmeyenlere 0 ata
  const all = [1, 2, 3, 4, 5, 6, 7].map((id) => ({
    id, p: olas[id] ?? 0,
  }));
  all.sort((a, b) => b.p - a.p);
  const ana = result.ana_kategori;
  const rows = all.map(({ id, p }) => {
    const pct = Math.round(p * 100);
    const cls = [];
    if (id === ana) cls.push("winner");
    else if (p > 0) cls.push("dim");
    else cls.push("zero");
    const name = state.categories[id] || "";
    // Satırın tamamı, olasılıkla orantılı yoğunlukta kategori rengine boyanır
    // (--pc: kategori rengi, --tint: olasılığa bağlı doluluk).
    return `<div class="prob-row ${cls.join(" ")}" style="--pc:var(--cat${id}); --tint:${Math.round(p * 16)}%">
      <span class="badge c${id}">${id}. ${esc(name)}</span>
      <span class="prob-track"><span class="prob-fill" style="width:${Math.max(pct, p > 0 ? 2 : 0)}%">${pct >= 15 ? pct + "%" : ""}</span></span>
      <span class="prob-val">${pct}%</span>
    </div>`;
  }).join("");
  // Marj göstergesi
  const marj = result.marj;
  let marginTag = "";
  if (marj != null) {
    const tight = marj < 0.25;
    marginTag = `<div class="margin-row">
      <span>Marj (en yüksek iki olasılık arası fark):</span>
      <span class="margin-chip ${tight ? "tight" : "sharp"}">${marj.toFixed(2)}</span>
      <span>${tight ? "— model gerçekten kararsız" : "— model net"}</span>
    </div>`;
  }
  return `<div class="prob-dist">${rows}</div>${marginTag}`;
}

// ============ Sekmeler ============
function activateTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) =>
    p.classList.toggle("active", p.id === "tab-" + name));
}
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});
// Derin bağlantı: ?tab=single | benchmark — sekmeyi doğrudan açar (paylaşım/test)
{
  const t = new URLSearchParams(location.search).get("tab");
  if (t && document.getElementById("tab-" + t)) activateTab(t);
}

// ============ Excel yükleme ============
const dropzone = $("dropzone");
$("browseBtn").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => e.target.files[0] && handleFile(e.target.files[0]));
["dragover", "dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.toggle("dragover", ev === "dragover");
    if (ev === "drop" && e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  })
);

async function handleFile(file) {
  const isRawData = document.querySelector('input[name="uploadKind"]:checked').value === "data";
  const fd = new FormData();
  fd.append("file", file);
  toast("Dosya yükleniyor…");
  try {
    const endpoint = isRawData ? "/api/upload-data" : "/api/upload";
    const data = await (await api(endpoint, { method: "POST", body: fd })).json();
    state.rows = data.rows;
    state.results = new Array(data.rows.length).fill(null);
    state.page = 1;
    state.fileName = file.name;
    const extra = [];
    if (data.tables) extra.push(`${data.tables} tablo`);
    if (data.with_samples) extra.push(`${data.with_samples} kolonda örnek değer`);
    $("fileInfo").textContent = `${file.name} — ${data.count.toLocaleString("tr")} satır`
      + (extra.length ? ` (${extra.join(", ")})` : "");
    dropzone.classList.add("hidden");
    $("workspace").classList.remove("hidden");
    $("exportBtn").disabled = true;
    updateStats();
    renderTable();
    toast(`${data.count.toLocaleString("tr")} satır yüklendi.`);
  } catch (err) {
    toast("Yükleme hatası: " + err.message, true);
  }
}

$("resetBtn").addEventListener("click", () => {
  if (state.running) { toast("Önce sınıflandırmayı durdurun.", true); return; }
  state.rows = []; state.results = [];
  $("workspace").classList.add("hidden");
  dropzone.classList.remove("hidden");
  $("fileInput").value = "";
  $("progressWrap").classList.add("hidden");
  $("liveFeed").classList.add("hidden");
  $("statsBar").classList.add("hidden");
});

// ============ Sınıflandırma ============
$("classifyBtn").addEventListener("click", runClassification);
$("stopBtn").addEventListener("click", () => {
  state.stopRequested = true;
  $("stopBtn").disabled = true;
  toast("Mevcut istekler bitince duracak…");
});

async function runClassification() {
  if (state.running || !state.rows.length) return;
  state.running = true;
  state.stopRequested = false;

  const useJudge = $("judgeToggle").checked;
  // Sadece sonuçsuz (veya hatalı) satırları gönder — kısmi çalıştırma devam ettirilebilir
  const pendingIdx = state.rows
    .map((_, i) => i)
    .filter((i) => !state.results[i] || state.results[i].kaynak === "hata");

  if (!pendingIdx.length) { toast("Tüm satırlar zaten sınıflandırılmış."); state.running = false; return; }

  // Tablo bütünlüğünü korumak için (şema|tablo) sırasına göre parçala
  pendingIdx.sort((a, b) => {
    const ka = state.rows[a].sema + "|" + state.rows[a].tablo;
    const kb = state.rows[b].sema + "|" + state.rows[b].tablo;
    return ka < kb ? -1 : ka > kb ? 1 : a - b;
  });
  const chunks = [];
  for (let i = 0; i < pendingIdx.length; i += CHUNK_SIZE) chunks.push(pendingIdx.slice(i, i + CHUNK_SIZE));

  $("classifyBtn").classList.add("hidden");
  $("stopBtn").classList.remove("hidden");
  $("stopBtn").disabled = false;
  $("progressWrap").classList.remove("hidden");
  $("liveFeed").innerHTML = "";
  $("liveFeed").classList.remove("hidden");
  let done = 0, failed = 0;
  const total = pendingIdx.length;
  setProgress(0, total);

  let cursor = 0;
  async function worker() {
    while (cursor < chunks.length && !state.stopRequested) {
      const chunk = chunks[cursor++];
      try {
        const body = JSON.stringify({
          rows: chunk.map((i) => state.rows[i]),
          use_judge: useJudge,
        });
        const data = await (await api("/api/classify", {
          method: "POST", headers: { "Content-Type": "application/json" }, body,
        })).json();
        chunk.forEach((rowIdx, j) => { state.results[rowIdx] = data.results[j] || null; });
        pushLiveFeed(chunk);
      } catch (err) {
        failed += chunk.length;
        chunk.forEach((rowIdx) => {
          state.results[rowIdx] = {
            kolon: state.rows[rowIdx].kolon, kategoriler: [], kategori_adlari: [],
            guven: 0, gerekce: "Hata: " + err.message, kaynak: "hata",
          };
        });
      }
      done += chunk.length;
      setProgress(done, total);
      updateStats();
      renderTable();
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));

  state.running = false;
  $("classifyBtn").classList.remove("hidden");
  $("stopBtn").classList.add("hidden");
  $("liveFeed").classList.add("hidden");  // koşu bitti; sonuçlar artık tabloda
  $("exportBtn").disabled = false;
  toast(state.stopRequested
    ? `Durduruldu — ${done}/${total} satır işlendi.`
    : failed
      ? `Bitti; ${failed} satır hata aldı. Tekrar 'Başlat' ile sadece hatalılar yeniden denenir.`
      : "Sınıflandırma tamamlandı.", failed > 0);
  updateStats();
  renderTable();
}

function setProgress(done, total) {
  $("progressFill").style.width = total ? (done / total) * 100 + "%" : "0%";
  $("progressText").textContent = `${done.toLocaleString("tr")} / ${total.toLocaleString("tr")} kolon`;
}

// Canlı akış: her parça sonuçlandıkça son kolon → kategori atamaları ilerleme
// çubuğunun altına düşer — kullanıcı uzun koşuda boş bir çubuğa değil, ilk
// saniyelerden itibaren gerçek sonuçlara bakar.
const LIVE_FEED_MAX = 14;
function pushLiveFeed(chunkIdxs) {
  const feed = $("liveFeed");
  const items = chunkIdxs
    .filter((i) => state.results[i] && state.results[i].kaynak !== "hata")
    .slice(-LIVE_FEED_MAX)
    .map((i) => {
      const res = state.results[i];
      const ana = res.ana_kategori;
      const cat = ana
        ? `<span class="badge c${ana}">${ana}. ${esc(state.categories[ana] || "")}</span>`
        : '<span class="badge none">kategorisiz</span>';
      return `<span class="live-item"><span class="live-col">${esc(state.rows[i].kolon)}</span>${cat}</span>`;
    })
    .reverse();
  if (!items.length) return;
  feed.insertAdjacentHTML("afterbegin", items.join(""));
  while (feed.children.length > LIVE_FEED_MAX) feed.removeChild(feed.lastChild);
}

// ============ İstatistikler ============
function updateStats() {
  const bar = $("statsBar");
  const counts = {};
  let classified = 0, none = 0, errors = 0, lowConf = 0;
  state.results.forEach((r) => {
    if (!r) return;
    if (r.kaynak === "hata") { errors++; return; }
    classified++;
    if (!r.kategoriler.length) none++;
    if (r.guven < CONF_LOW) lowConf++;
    if (r.ana_kategori) counts[r.ana_kategori] = (counts[r.ana_kategori] || 0) + 1;
  });
  if (!classified && !errors) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const chips = [
    `<span class="stat-chip">Sınıflandırılan: <b>${classified}</b> / ${state.rows.length}</span>`,
    ...Object.entries(state.categories)
      .filter(([id]) => counts[id])
      .map(([id, name]) => `<span class="stat-chip cat" style="--c:var(--cat${id})" title="Ana kategori sayısı"><b>${counts[id]}</b> ${esc(name)}</span>`),
    `<span class="stat-chip">Kategorisiz: <b>${none}</b></span>`,
    `<span class="stat-chip${lowConf ? " warn" : ""}">Düşük güven: <b>${lowConf}</b></span>`,
  ];
  if (errors) chips.push(`<span class="stat-chip">Hatalı: <b>${errors}</b></span>`);
  bar.innerHTML = chips.join("");
}

// ============ Tablo görünümü ============
["searchInput", "categoryFilter", "statusFilter"].forEach((id) =>
  $(id).addEventListener("input", () => { state.page = 1; renderTable(); }));
$("prevPage").addEventListener("click", () => { state.page--; renderTable(); });
$("nextPage").addEventListener("click", () => { state.page++; renderTable(); });

function filteredIndexes() {
  const q = $("searchInput").value.trim().toLowerCase();
  const cat = $("categoryFilter").value;
  const status = $("statusFilter").value;
  return state.rows.map((_, i) => i).filter((i) => {
    const row = state.rows[i], res = state.results[i];
    if (q && !(row.kolon.toLowerCase().includes(q) || row.tablo.toLowerCase().includes(q))) return false;
    if (cat && !(res && res.kategoriler.includes(Number(cat)))) return false;
    if (status === "classified" && !(res && res.kaynak !== "hata")) return false;
    if (status === "pending" && res) return false;
    if (status === "lowconf" && !(res && res.kaynak !== "hata" && res.guven < CONF_LOW)) return false;
    if (status === "none" && !(res && res.kaynak !== "hata" && !res.kategoriler.length)) return false;
    if (status === "error" && !(res && res.kaynak === "hata")) return false;
    return true;
  });
}

function renderTable() {
  const idxs = filteredIndexes();
  const pages = Math.max(1, Math.ceil(idxs.length / state.pageSize));
  state.page = Math.min(Math.max(1, state.page), pages);
  const start = (state.page - 1) * state.pageSize;
  const pageIdxs = idxs.slice(start, start + state.pageSize);

  $("gridBody").innerHTML = pageIdxs.map((i) => {
    const r = state.rows[i], res = state.results[i];
    // Satırın sol kenarına ana kategorinin renk şeridi — tabloda kategori dağılımı
    // kaydırmadan tek bakışta okunur.
    const stripe = res && res.ana_kategori ? `--rc:var(--cat${res.ana_kategori})` : "";
    return `<tr style="${stripe}">
      <td class="dim">${i + 1}</td>
      <td class="dim">${esc(r.sema)}</td>
      <td>${esc(r.tablo)}</td>
      <td class="mono">${esc(r.kolon)}${(r.ornek_degerler && r.ornek_degerler.length)
        ? ` <span class="badge tek" title="İçerik sinyali var: ${r.ornek_degerler.length} örnek değer (ham olarak gönderilir)">${r.ornek_degerler.length}⛁</span>` : ""}</td>
      <td class="dim">${acilimHtml(res)}</td>
      <td class="dim">${esc(r.veri_tipi)}${r.uzunluk ? "(" + esc(r.uzunluk) + ")" : ""}</td>
      <td class="dim">${r.pk === "1" ? "PK" : ""}</td>
      <td>${badgeHtml(res)}</td>
      <td>${confHtml(res)}</td>
      <td class="reason">${esc(res ? res.gerekce : "")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="10" class="dim" style="text-align:center;padding:24px">Eşleşen satır yok</td></tr>`;

  $("pageInfo").textContent = `Sayfa ${state.page} / ${pages} — ${idxs.length.toLocaleString("tr")} satır`;
  $("prevPage").disabled = state.page <= 1;
  $("nextPage").disabled = state.page >= pages;
}

// ============ Dışa aktarma ============
$("exportBtn").addEventListener("click", async () => {
  try {
    toast("Excel hazırlanıyor…");
    const body = JSON.stringify({
      items: state.rows.map((row, i) => ({ row, result: state.results[i] })),
    });
    const resp = await api("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" }, body,
    });
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "kolon_siniflandirma.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (err) {
    toast("Dışa aktarma hatası: " + err.message, true);
  }
});

// ============ Tekil sorgu ============
$("singleForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("singleSubmit");
  const row = Object.fromEntries(new FormData(e.target).entries());
  // Serbest metin örnek değerleri listeye çevir (backend list[str] bekler)
  row.ornek_degerler = (row.ornek_degerler_raw || "")
    .split(/[;|\n]+/).map((s) => s.trim()).filter(Boolean).slice(0, 10);
  delete row.ornek_degerler_raw;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Derin analiz yapılıyor…';
  try {
    // Kural analizi ve LLM sınıflandırmasını paralel çalıştır
    const jsonOpts = (body) => ({
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    // Tekil sorgu = DERİN ANALİZ modu: tek kolonda gecikme önemsiz, özen önemli.
    // deep: true → düşünme bütçesi yükselir (SINGLE_REASONING_EFFORT, vars. high);
    // hakem AÇIK → belirsiz kolonlara ikinci bağımsız görüş alınır. Toplu tablo
    // hızlı profilde kalır (REASONING_EFFORT=low + eşikli hakem).
    const [analysisResp, classifyResp] = await Promise.all([
      api("/api/analyze", jsonOpts(row)),
      api("/api/classify", jsonOpts({ rows: [row], use_judge: true, deep: true })),
    ]);
    const analysis = await analysisResp.json();
    const result = (await classifyResp.json()).results[0];
    renderSingleResult(row, result, analysis);
  } catch (err) {
    toast("Hata: " + err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Sınıflandır";
  }
});

function renderSingleResult(row, result, analysis) {
  const hints = Object.entries(analysis.hints || {});
  $("singleResultBody").innerHTML = `
    <div class="result-block">
      <h3>Kolon</h3>
      <span class="mono" style="font-family:Consolas,monospace">${esc(row.kolon)}</span>
      ${row.tablo ? `<span class="dim"> — ${esc(row.tablo)}</span>` : ""}
    </div>
    <div class="result-block"><h3>LLM'in Tahmin Ettiği Açılım</h3><div class="result-reason">${acilimHtml(result) || "-"}</div></div>
    <div class="result-block"><h3>Ana Kategori</h3>${
      result.ana_kategori
        ? `<span class="badge c${result.ana_kategori}">${result.ana_kategori}. ${esc(state.categories[result.ana_kategori] || "")}</span>`
        : "-"
    }</div>
    <div class="result-block"><h3>Tüm Olası Kategoriler</h3>${badgeHtml(result)}</div>
    <div class="result-block"><h3>Olasılık Dağılımı</h3>${probsHtml(result)}</div>
    <div class="result-block"><h3>Güven</h3>${confHtml(result) || "-"}</div>
    <div class="result-block"><h3>Gerekçe</h3><div class="result-reason">${esc(result.gerekce) || "-"}</div></div>
    ${analysis.note ? `<div class="result-block"><h3>Önek Çözümü</h3><div class="result-reason">${esc(analysis.note)}</div></div>` : ""}
    ${hints.length ? `<div class="result-block"><h3>Sözlük İpuçları</h3>
      <ul class="hint-list">${hints.map(([t, cats]) =>
        `<li><b>${esc(t)}</b> → ${cats.map((c) => esc(state.categories[c] || c)).join(", ")}</li>`).join("")}
      </ul></div>` : ""}
    ${result.ilk_deneme ? `<div class="result-block"><h3>Hakem Öncesi İlk Deneme</h3>
      <div class="result-reason dim">kategoriler: [${result.ilk_deneme.kategoriler.join(", ")}] — güven: ${result.ilk_deneme.guven}</div></div>` : ""}
  `;
  $("singleResult").classList.remove("hidden");
}

// ============ Benchmark ============
const BENCH_MODE_LABELS = { name_only: "Yalnız İsim", content_only: "Yalnız İçerik", name_content: "İsim + İçerik" };
const BENCH_BUCKETS = ["1", "2", "3", "4", "5", "6", "7", "teknik"];
const benchState = { detail: [] };
let benchPollTimer = null;

function modeLabel(m) { return BENCH_MODE_LABELS[m] || m; }
function bucketLabel(b) { return b === "teknik" ? "Teknik/İşlemsel" : `${b}. ${state.categories[b] || ""}`; }
function pct(v) { return v == null ? "-" : (v * 100).toFixed(1) + "%"; }
function catLabel(id) { return id ? `${id}. ${state.categories[id] || ""}` : "-"; }

function accuracyColor(v) {
  if (v == null) return "#9aa3b2";
  // Sabit durum paleti (kritik → uyarı → iyi) — dataviz palette.md, hiç temalanmaz
  const stops = [[0, [208, 59, 59]], [0.5, [250, 178, 25]], [1, [12, 163, 12]]];
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (v >= stops[i][0] && v <= stops[i + 1][0]) { lo = stops[i]; hi = stops[i + 1]; break; }
  }
  const t = (v - lo[0]) / ((hi[0] - lo[0]) || 1);
  const c = lo[1].map((ch, i) => Math.round(ch + (hi[1][i] - ch) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

async function loadBenchDatasetInfo() {
  try {
    const data = await (await api("/api/benchmark/dataset")).json();
    $("benchDatasetInfo").innerHTML = `
      <span class="stat-chip">Toplam satır: <b>${data.total_rows}</b></span>
      <span class="stat-chip">Kavram: <b>${data.concepts}</b></span>
      <span class="stat-chip">Kova başına: <b>${data.rows_per_bucket_per_group}</b> isimli + <b>${data.rows_per_bucket_per_group}</b> rastgele</span>
      <span class="stat-chip">Kova sayısı: <b>${data.buckets.length}</b> (7 kategori + teknik)</span>`;
  } catch { /* kritik değil, sessiz geç */ }
}

function renderBenchCards(perMode, modes) {
  $("benchCards").innerHTML = modes.map((m) => {
    const o = perMode[m]?.overall || {};
    return `<div class="bench-card">
      <h3>${esc(modeLabel(m))}</h3>
      <div class="bench-big"><span class="heatmap-cell" style="background:${accuracyColor(o.ana_accuracy)};font-size:22px;padding:3px 12px">${pct(o.ana_accuracy)}</span></div>
      <div class="bench-sub">
        <span>Küme F1: <b>${pct(o.set_f1)}</b></span>
        <span>Teknik doğruluk: <b>${pct(o.teknik_accuracy)}</b></span>
        <span>Ort. güven: <b>${o.avg_confidence != null ? o.avg_confidence.toFixed(2) : "-"}</b></span>
        <span>Hata oranı: <b>${pct(o.error_rate)}</b></span>
        <span>Hakem oranı: <b>${pct(o.judge_rate)}</b></span>
        <span>n=<b>${o.n ?? "-"}</b></span>
      </div>
    </div>`;
  }).join("");
}

function renderHeatmap(perMode, modes) {
  let html = "<thead><tr><th>Kova</th>" + modes.map((m) => `<th>${esc(modeLabel(m))}</th>`).join("") + "</tr></thead><tbody>";
  BENCH_BUCKETS.forEach((b) => {
    html += `<tr><td>${esc(bucketLabel(b))}</td>`;
    modes.forEach((m) => {
      const agg = perMode[m]?.by_bucket?.[b];
      if (!agg || !agg.n) { html += `<td><span class="heatmap-cell na">—</span></td>`; return; }
      html += `<td><span class="heatmap-cell" style="background:${accuracyColor(agg.ana_accuracy)}" title="n=${agg.n}">${(agg.ana_accuracy * 100).toFixed(0)}%</span></td>`;
    });
    html += "</tr>";
  });
  $("benchHeatmap").innerHTML = html + "</tbody>";
}

function renderChart(perMode, modes) {
  const w = 640, h = 220, padL = 40, padB = 30, padT = 10, padR = 10;
  const groupW = (w - padL - padR) / modes.length;
  const barW = Math.min(48, groupW * 0.28);
  const gap = 10;
  const namedColor = "#2a78d6", randomColor = "#1baf7a"; // dataviz kategorik paleti, slot 1+2 (doğrulandı)
  let bars = "";
  modes.forEach((m, i) => {
    const cx = padL + groupW * i + groupW / 2;
    const series = [
      ["İsimli", perMode[m]?.by_group?.named?.ana_accuracy ?? 0, namedColor, cx - gap / 2 - barW],
      ["Rastgele", perMode[m]?.by_group?.random?.ana_accuracy ?? 0, randomColor, cx + gap / 2],
    ];
    series.forEach(([label, v, color, x]) => {
      const barH = (h - padT - padB) * v;
      const y = h - padB - barH;
      bars += `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(barH, 1)}" rx="4" fill="${color}"><title>${label} — ${modeLabel(m)}: ${(v * 100).toFixed(1)}%</title></rect>`;
      bars += `<text x="${x + barW / 2}" y="${y - 6}" text-anchor="middle" font-size="11" fill="#1c2330" font-weight="600">${(v * 100).toFixed(0)}%</text>`;
    });
    bars += `<text x="${cx}" y="${h - padB + 18}" text-anchor="middle" font-size="12" fill="#6b7484">${esc(modeLabel(m))}</text>`;
  });
  let grid = "";
  [0, 0.25, 0.5, 0.75, 1].forEach((g) => {
    const y = h - padB - (h - padT - padB) * g;
    grid += `<line x1="${padL}" y1="${y}" x2="${w - padR}" y2="${y}" stroke="#e2e5ea" stroke-width="1"/>`;
    grid += `<text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="10" fill="#9aa3b2">${(g * 100).toFixed(0)}%</text>`;
  });
  $("benchChart").innerHTML = `
    <div class="bench-legend">
      <span><i style="background:${namedColor}"></i>İsimli</span>
      <span><i style="background:${randomColor}"></i>Rastgele</span>
    </div>
    <svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;height:auto">${grid}${bars}</svg>`;
}

function renderDependency(pairing, modes) {
  const chips = modes.map((m) => {
    const p = pairing[m];
    if (!p) return "";
    return `<span class="stat-chip" title="${p.n_concepts} kavramdan ${p.only_named_correct} tanesi yalnız isimle doğru">
      ${esc(modeLabel(m))}: <b>${p.name_dependency_rate != null ? (p.name_dependency_rate * 100).toFixed(1) + "%" : "-"}</b></span>`;
  }).join("");
  $("benchDependency").innerHTML = chips || '<span class="dim">Veri yok</span>';
}

function populateBenchFilters(modes) {
  $("benchFilterMode").innerHTML = '<option value="">Tüm modlar</option>'
    + modes.map((m) => `<option value="${m}">${esc(modeLabel(m))}</option>`).join("");
  $("benchFilterBucket").innerHTML = '<option value="">Tüm kategoriler</option>'
    + BENCH_BUCKETS.map((b) => `<option value="${b}">${esc(bucketLabel(b))}</option>`).join("");
}

function benchFilteredDetail() {
  const mode = $("benchFilterMode").value, group = $("benchFilterGroup").value;
  const bucket = $("benchFilterBucket").value, status = $("benchFilterStatus").value;
  return (benchState.detail || []).filter((d) => {
    if (mode && d.mode !== mode) return false;
    if (group && d.group !== group) return false;
    if (bucket && d.bucket !== bucket) return false;
    if (status === "correct" && !d.metrics.ana_match) return false;
    if (status === "wrong" && d.metrics.ana_match) return false;
    return true;
  });
}

function renderBenchDetailTable() {
  const rows = benchFilteredDetail().slice(0, 500);
  $("benchDetailBody").innerHTML = rows.map((d) => `
    <tr>
      <td class="dim">${esc(modeLabel(d.mode))}</td>
      <td class="dim">${d.group === "named" ? "İsimli" : "Rastgele"}</td>
      <td class="mono">${esc(d.concept)}</td>
      <td class="dim">${esc(bucketLabel(d.bucket))}</td>
      <td>${esc(catLabel(d.truth.ana_kategori))}</td>
      <td>${esc(catLabel(d.pred.ana_kategori))}</td>
      <td>${d.metrics.ana_match ? '<span class="conf high">✓</span>' : '<span class="conf low">✗</span>'}</td>
      <td>${confHtml(d.pred)}</td>
      <td class="dim">${esc(d.pred.kaynak || "")}</td>
    </tr>`).join("")
    || `<tr><td colspan="9" class="bench-empty">Eşleşen satır yok</td></tr>`;
}

["benchFilterMode", "benchFilterGroup", "benchFilterBucket", "benchFilterStatus"].forEach((id) =>
  $(id).addEventListener("change", renderBenchDetailTable));

function renderBenchRun(run) {
  const result = run.result;
  benchState.detail = result.detail;
  $("benchResults").classList.remove("hidden");
  renderBenchCards(result.per_mode, result.modes);
  renderHeatmap(result.per_mode, result.modes);
  renderChart(result.per_mode, result.modes);
  renderDependency(result.pairing, result.modes);
  populateBenchFilters(result.modes);
  renderBenchDetailTable();
}

async function loadBenchHistory() {
  try {
    const data = await (await api("/api/benchmark/runs")).json();
    const rows = data.runs || [];
    $("benchHistoryBody").innerHTML = rows.map((r) => {
      const nc = r.summary?.per_mode?.name_content?.ana_accuracy;
      return `<tr class="bench-history-row">
        <td class="dim">${esc(new Date(r.started_at).toLocaleString("tr"))}</td>
        <td class="dim">${(r.modes || []).map(modeLabel).join(", ")}</td>
        <td class="dim">${r.use_judge ? "Açık" : "Kapalı"}</td>
        <td class="mono dim">${esc(r.model || "")}</td>
        <td class="dim">${r.elapsed_seconds != null ? r.elapsed_seconds + "sn" : "-"}</td>
        <td>${nc != null ? (nc * 100).toFixed(1) + "%" : "-"}</td>
        <td>
          <button class="btn btn-ghost bench-view-btn" data-run="${esc(r.run_id)}">Görüntüle</button>
          <button class="btn btn-ghost bench-del-btn" data-run="${esc(r.run_id)}">Sil</button>
        </td>
      </tr>`;
    }).join("") || `<tr><td colspan="7" class="bench-empty">Henüz koşu yok</td></tr>`;

    document.querySelectorAll(".bench-view-btn").forEach((btn) => btn.addEventListener("click", async () => {
      try {
        const run = await (await api(`/api/benchmark/runs/${btn.dataset.run}`)).json();
        renderBenchRun(run);
        $("benchResults").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) { toast("Koşu yüklenemedi: " + err.message, true); }
    }));
    document.querySelectorAll(".bench-del-btn").forEach((btn) => btn.addEventListener("click", async () => {
      if (!confirm("Bu koşuyu silmek istediğinize emin misiniz?")) return;
      try {
        await api(`/api/benchmark/runs/${btn.dataset.run}`, { method: "DELETE" });
        await loadBenchHistory();
      } catch (err) { toast("Silinemedi: " + err.message, true); }
    }));
  } catch (err) {
    toast("Geçmiş yüklenemedi: " + err.message, true);
  }
}

let currentBenchJobId = null;

function benchResetControls() {
  $("benchRunBtn").disabled = false;
  $("benchRunBtn").classList.remove("hidden");
  $("benchStopBtn").classList.add("hidden");
  $("benchProgressWrap").classList.add("hidden");
  currentBenchJobId = null;
}

function pollBenchJob(jobId) {
  clearInterval(benchPollTimer);
  benchPollTimer = setInterval(async () => {
    try {
      const job = await (await api(`/api/benchmark/jobs/${jobId}`)).json();
      if (job.progress) {
        const { step, total, mode } = job.progress;
        $("benchProgressFill").style.width = total ? (step / total * 100) + "%" : "0%";
        $("benchProgressText").textContent = mode
          ? `Mod ${step}/${total}: ${modeLabel(mode)} tamamlandı…`
          : `Başlatılıyor… (0/${total})`;
      }
      if (job.status === "done") {
        clearInterval(benchPollTimer);
        $("benchProgressText").textContent = "Tamamlandı, sonuçlar yükleniyor…";
        const run = await (await api(`/api/benchmark/runs/${job.run_id}`)).json();
        renderBenchRun(run);
        await loadBenchHistory();
        benchResetControls();
        toast("Benchmark tamamlandı.");
      } else if (job.status === "error") {
        clearInterval(benchPollTimer);
        toast("Benchmark hatası: " + (job.error || "bilinmeyen hata"), true);
        benchResetControls();
      } else if (job.status === "cancelled") {
        clearInterval(benchPollTimer);
        toast("Benchmark durduruldu.");
        benchResetControls();
      }
    } catch (err) {
      clearInterval(benchPollTimer);
      toast("İş durumu alınamadı: " + err.message, true);
      benchResetControls();
    }
  }, 1500);
}

$("benchRunBtn").addEventListener("click", async () => {
  const modes = Array.from(document.querySelectorAll(".benchMode:checked")).map((el) => el.value);
  if (!modes.length) { toast("En az bir mod seçin.", true); return; }
  const useJudge = $("benchJudgeToggle").checked;
  $("benchRunBtn").classList.add("hidden");
  $("benchStopBtn").classList.remove("hidden");
  $("benchProgressWrap").classList.remove("hidden");
  $("benchProgressText").textContent = "Başlatılıyor…";
  $("benchProgressFill").style.width = "0%";
  try {
    const data = await (await api("/api/benchmark/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modes, use_judge: useJudge }),
    })).json();
    currentBenchJobId = data.job_id;
    pollBenchJob(data.job_id);
  } catch (err) {
    toast("Benchmark başlatılamadı: " + err.message, true);
    benchResetControls();
  }
});

$("benchStopBtn").addEventListener("click", async () => {
  if (!currentBenchJobId) return;
  $("benchStopBtn").disabled = true;
  try {
    await api(`/api/benchmark/jobs/${currentBenchJobId}`, { method: "DELETE" });
    $("benchProgressText").textContent = "Durduruluyor…";
  } catch (err) {
    toast("Durdurulamadı: " + err.message, true);
  } finally {
    $("benchStopBtn").disabled = false;
  }
});

let benchLoaded = false;
document.querySelector('.tab[data-tab="benchmark"]').addEventListener("click", () => {
  if (benchLoaded) return;
  benchLoaded = true;
  loadBenchDatasetInfo();
  loadBenchHistory();
});

// ============ Başlangıç ============
(async function init() {
  try {
    const data = await (await api("/api/categories")).json();
    state.categories = data.categories;
    const sel = $("categoryFilter");
    Object.entries(state.categories).forEach(([id, name]) => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `${id}. ${name}`;
      sel.appendChild(opt);
    });
  } catch {
    toast("Sunucuya bağlanılamadı. Backend çalışıyor mu?", true);
  }
})();
