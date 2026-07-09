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
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch { /* yut */ }
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
  const cls = v < 0.6 ? "low" : v < 0.8 ? "mid" : "high";
  const src = result.kaynak === "llm+hakem" ? "hakem" : result.kaynak === "cache" ? "önbellek" : "";
  return `<span class="conf ${cls}">${v.toFixed(2)}</span>` +
         (src ? `<span class="src-tag">${src}</span>` : "");
}

// ============ Sekmeler ============
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-panel").forEach((p) =>
      p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab));
  });
});

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
  const fd = new FormData();
  fd.append("file", file);
  toast("Dosya yükleniyor…");
  try {
    const data = await (await api("/api/upload", { method: "POST", body: fd })).json();
    state.rows = data.rows;
    state.results = new Array(data.rows.length).fill(null);
    state.page = 1;
    state.fileName = file.name;
    $("fileInfo").textContent = `${file.name} — ${data.count.toLocaleString("tr")} satır`;
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
    if (r.guven < 0.6) lowConf++;
    if (r.ana_kategori) counts[r.ana_kategori] = (counts[r.ana_kategori] || 0) + 1;
  });
  if (!classified && !errors) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const chips = [
    `<span class="stat-chip">Sınıflandırılan: <b>${classified}</b> / ${state.rows.length}</span>`,
    ...Object.entries(state.categories)
      .filter(([id]) => counts[id])
      .map(([id, name]) => `<span class="stat-chip" title="Ana kategori sayısı"><b>${counts[id]}</b> ${esc(name)}</span>`),
    `<span class="stat-chip">Kategorisiz: <b>${none}</b></span>`,
    `<span class="stat-chip">Düşük güven: <b>${lowConf}</b></span>`,
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
    if (status === "lowconf" && !(res && res.kaynak !== "hata" && res.guven < 0.6)) return false;
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
    return `<tr>
      <td class="dim">${i + 1}</td>
      <td class="dim">${esc(r.sema)}</td>
      <td>${esc(r.tablo)}</td>
      <td class="mono">${esc(r.kolon)}</td>
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
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Sınıflandırılıyor…';
  try {
    // Kural analizi ve LLM sınıflandırmasını paralel çalıştır
    const jsonOpts = (body) => ({
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const [analysisResp, classifyResp] = await Promise.all([
      api("/api/analyze", jsonOpts(row)),
      api("/api/classify", jsonOpts({ rows: [row], use_judge: true })),
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
