// MediNet — Distribuit · Frontend logic (vanilla JS)

const API = {
  network:    () => fetch('/api/network').then(r => r.json()),
  pacienti:   (node = '') => fetch('/api/global/pacienti' + (node ? `?node=${node}` : '')).then(r => r.json()),
  programari: () => fetch('/api/global/programari').then(r => r.json()),
  facturi:    () => fetch('/api/global/facturi').then(r => r.json()),
  medici:     () => fetch('/api/global/medici').then(r => r.json()),
  catalog:    (t) => fetch(`/api/catalog/${t}`).then(r => r.json()),
  log:        (limit = 60) => fetch(`/api/log?limit=${limit}`).then(r => r.json()),
  clearLog:   () => fetch('/api/log/clear', { method: 'POST' }).then(r => r.json()),

  postPacient:    (b) => post('/api/pacient', b),
  postProgramare: (b) => post('/api/programare', b),
  postFactura:    (b) => post('/api/factura', b),
  postProgDiag:   (b) => post('/api/prog_diag', b),
  postMedic:      (b) => post('/api/medic', b),
  postSalariu:    (id, b) => post(`/api/medic/${id}/salariu`, b),
  postDiagnostic: (b) => post('/api/diagnostic', b),
  putDiagnostic:  (id, b) => fetch(`/api/diagnostic/${id}`, { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b) }).then(r => r.json()),
  delDiagnostic:  (id) => fetch(`/api/diagnostic/${id}`, { method: 'DELETE' }).then(r => r.json()),
  reset:          () => post('/api/reset', {}),
  raport:         (b) => post('/api/report/diabet', b),
};

function post(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then(async r => {
    const j = await r.json().catch(() => ({}));
    return { status: r.status, ...j };
  });
}

// ---- Toast ----
const toastEl = document.getElementById('toast');
let toastTimer;
function toast(msg, kind = 'ok') {
  toastEl.textContent = msg;
  toastEl.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.className = 'toast', 2800);
}

function feedback(el, msg, kind = 'ok') {
  el.textContent = msg;
  el.className = `form-feedback ${kind}`;
}

// ---- Tabs ----
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.querySelector(`[data-panel="${tab.dataset.tab}"]`).classList.add('active');
    if (tab.dataset.tab === 'log') refreshLog();
  });
});

// ---- Topology ----
function renderTopology() {
  const wrap = document.getElementById('topology');
  wrap.innerHTML = `
    <div class="node global">
      <h4>S1 · GLOBAL_DB</h4>
      <small>Sediu Central</small>
      <div class="pill">MEDIC_HR · vederi globale · catalog</div>
    </div>
    <div class="node">
      <h4>S2 · LOCAL_SUD</h4>
      <small>Filiala Sud</small>
      <div class="pill">PACIENT₁ · PROGRAMARE₁ · FACTURA₁</div>
    </div>
    <div class="node">
      <h4>S3 · LOCAL_VEST</h4>
      <small>Filiala Vest</small>
      <div class="pill">PACIENT₂ · PROGRAMARE₂ · FACTURA₂</div>
    </div>
    <div class="node">
      <h4>S4 · LOCAL_EST</h4>
      <small>Filiala Est</small>
      <div class="pill">PACIENT₃ · PROGRAMARE₃ · FACTURA₃</div>
    </div>
  `;
}

// ---- Network status ----
async function refreshNetwork() {
  const data = await API.network();
  const grid = document.getElementById('networkStatus');
  grid.innerHTML = data.nodes.map(n => `
    <div class="net-node">
      <h4>${n.code} <span class="muted small">(${n.user})</span></h4>
      ${Object.entries(n.tables).map(([t, c]) =>
        `<div class="nm"><span>${t}</span><code>${c == null ? '—' : c}</code></div>`
      ).join('')}
    </div>
  `).join('');
}

// ---- KPIs ----
async function refreshKPIs() {
  const [pac, prog, fact] = await Promise.all([API.pacienti(), API.programari(), API.facturi()]);
  document.getElementById('kpiPacienti').textContent = pac.rows.length;
  document.getElementById('kpiProgramari').textContent = prog.rows.length;
  const total = fact.rows.reduce((s, f) => s + (f.suma || 0), 0);
  document.getElementById('kpiFacturat').textContent = total.toLocaleString('ro-RO', { style: 'currency', currency: 'RON' });
}

// ---- Pacienti ----
async function refreshPacienti(node = '') {
  const data = await API.pacienti(node);
  const tbody = document.querySelector('#tablePacienti tbody');
  tbody.innerHTML = data.rows.map(p => `
    <tr>
      <td>${p.id_pacient}</td>
      <td>${p.nume} ${p.prenume}</td>
      <td>${p.cnp}</td>
      <td>${p.regiune}</td>
      <td><code>${p._node}</code></td>
    </tr>
  `).join('') || '<tr><td colspan="5" class="muted" style="text-align:center;padding:1.2rem;">Nu există pacienți.</td></tr>';

  const sel = document.getElementById('selectPacient');
  if (sel) sel.innerHTML = data.rows.map(p =>
    `<option value="${p.id_pacient}">#${p.id_pacient} · ${p.nume} ${p.prenume} (${p.regiune})</option>`).join('');
}

document.getElementById('filterPacientNod').addEventListener('change', e => refreshPacienti(e.target.value));

// ---- Programari ----
async function refreshProgramari() {
  const data = await API.programari();
  const tbody = document.querySelector('#tableProgramari tbody');
  tbody.innerHTML = data.rows.map(p => `
    <tr>
      <td>${p.id_programare}</td>
      <td>#${p.id_pacient}</td>
      <td>#${p.id_medic}</td>
      <td>${p.id_tratament || '—'}</td>
      <td>${p.data_ora}</td>
      <td>${p.status}</td>
      <td><code>${p._node}</code></td>
    </tr>
  `).join('') || '<tr><td colspan="7" class="muted" style="text-align:center;padding:1.2rem;">Nu există programări.</td></tr>';
}

async function refreshFacturi() {
  const data = await API.facturi();
  const tbody = document.querySelector('#tableFacturi tbody');
  tbody.innerHTML = data.rows.map(f => `
    <tr>
      <td>${f.id_factura}</td>
      <td>#${f.id_programare}</td>
      <td>${f.data_emitere || '—'}</td>
      <td>${(f.suma || 0).toLocaleString('ro-RO', { style: 'currency', currency: 'RON' })}</td>
      <td>${f.status_plata}</td>
      <td><code>${f._node}</code></td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="muted" style="text-align:center;padding:1.2rem;">Nu există facturi.</td></tr>';
}

// ---- Medici ----
async function refreshMedici() {
  const data = await API.medici();
  const tbody = document.querySelector('#tableMedici tbody');
  tbody.innerHTML = data.rows.map(m => `
    <tr>
      <td>${m.id_medic}</td>
      <td>${m.nume} ${m.prenume}</td>
      <td>${m.cod_parafa}</td>
      <td>${m.data_angajarii || '—'}</td>
      <td>${(m.salariu || 0).toLocaleString('ro-RO', { style: 'currency', currency: 'RON' })}</td>
      <td>
        <button class="btn small salariu-btn" data-id="${m.id_medic}" data-curr="${m.salariu || 0}">Modifică salariu</button>
      </td>
    </tr>
  `).join('') || '<tr><td colspan="6" class="muted" style="text-align:center;padding:1.2rem;">Nu există medici.</td></tr>';

  document.querySelectorAll('.salariu-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const curr = btn.dataset.curr;
      const v = prompt(`Noul salariu pentru medicul #${id} (curent: ${curr} RON):`, curr);
      if (!v) return;
      const r = await API.postSalariu(id, { salariu: parseFloat(v) });
      if (r.ok) {
        toast(`Salariul medicului #${id} actualizat la ${v} RON`, 'ok');
        refreshMedici();
      } else {
        toast(r.error || 'Eroare', 'err');
      }
    });
  });

  const sel = document.getElementById('selectMedic');
  if (sel) sel.innerHTML = data.rows.map(m =>
    `<option value="${m.id_medic}">#${m.id_medic} · Dr. ${m.nume} ${m.prenume}</option>`).join('');
}

// ---- Catalog -----
async function refreshCataloage() {
  const [diag, trat, spec] = await Promise.all([
    API.catalog('DIAGNOSTIC'), API.catalog('TRATAMENT'), API.catalog('SPECIALIZARE'),
  ]);

  await Promise.all(['S1', 'S2', 'S3', 'S4'].map(async (n) => {
    const ul = document.getElementById(`diagList${n}`);
    if (!ul) return;
    try {
      const resp = await fetch(`/api/node/${n}/DIAGNOSTIC`).then(r => r.json());
      ul.innerHTML = (resp.rows || []).map(d =>
        `<li><span><strong>${d.cod_boala}</strong> · ${d.nume}</span><span class="sev ${d.severitate}">${d.severitate}</span></li>`
      ).join('') || '<li class="muted">— gol —</li>';
    } catch (e) {
      ul.innerHTML = '<li class="muted">eroare</li>';
    }
  }));

  const sel = document.getElementById('selectDiagnostic');
  if (sel) sel.innerHTML = diag.rows.map(d => `<option value="${d.id_diagnostic}">${d.cod_boala} · ${d.nume}</option>`).join('');

  const selT = document.getElementById('selectTratament');
  if (selT) {
    const cur = selT.querySelector('option[value=""]')?.outerHTML || '';
    selT.innerHTML = cur + trat.rows.map(t => `<option value="${t.id_tratament}">${t.denumire}</option>`).join('');
  }

  document.querySelector('#tableTratament tbody').innerHTML = trat.rows.map(t =>
    `<tr><td>${t.id_tratament}</td><td>${t.denumire}</td><td>${t.tip || ''}</td><td>${(t.cost_referinta || 0).toLocaleString('ro-RO', { style: 'currency', currency: 'RON' })}</td></tr>`
  ).join('');
  document.querySelector('#tableSpecializare tbody').innerHTML = spec.rows.map(s =>
    `<tr><td>${s.id_specializare}</td><td>${s.denumire}</td><td>${s.descriere || ''}</td></tr>`
  ).join('');
}

// ---- Log ----
async function refreshLog() {
  const data = await API.log(80);
  const list = document.getElementById('logList');
  list.innerHTML = data.entries.map(e => `
    <div class="log-entry" title="${escapeHtml(e.sql)}">
      <span class="ts">${e.ts}</span>
      <span class="node ${e.node}">${e.node}</span>
      <span class="sql">${escapeHtml(e.sql)}</span>
      <span class="rows">${e.rows == null ? '' : `${e.rows} rows`}</span>
      <span class="ms">${e.elapsed_ms != null ? e.elapsed_ms + ' ms' : ''}</span>
    </div>
  `).join('') || '<div class="muted" style="padding:1rem;">Nu sunt interogări înregistrate.</div>';
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---- Forms ----
function bindForm(formId, feedbackId, fn, after) {
  const form = document.getElementById(formId);
  const fb = document.getElementById(feedbackId);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const obj = {};
    fd.forEach((v, k) => {
      if (form.elements[k]?.type === 'checkbox') obj[k] = form.elements[k].checked ? 1 : 0;
      else obj[k] = v;
    });
    const r = await fn(obj);
    if (r.ok) {
      feedback(fb, `Operație reușită (${JSON.stringify(r).slice(0, 120)})`, 'ok');
      toast('Operație reușită', 'ok');
      form.reset();
      if (after) await after(r);
    } else {
      feedback(fb, r.error || 'Eroare necunoscută', 'err');
      toast(r.error || 'Eroare', 'err');
    }
    refreshLog(); refreshNetwork();
  });
}

bindForm('formPacient', 'pacientFeedback', API.postPacient, async () => {
  await refreshPacienti(document.getElementById('filterPacientNod').value);
  await refreshKPIs();
});

bindForm('formProgramare', 'programareFeedback', API.postProgramare, async () => {
  await refreshProgramari(); await refreshKPIs();
});

bindForm('formFactura', 'facturaFeedback', API.postFactura, async () => {
  await refreshFacturi(); await refreshKPIs();
});

bindForm('formProgDiag', 'progDiagFeedback', API.postProgDiag);

bindForm('formMedic', 'medicFeedback', API.postMedic, async () => {
  await refreshMedici();
});

bindForm('formDiagnostic', 'diagnosticFeedback', API.postDiagnostic, async () => {
  await refreshCataloage();
});

document.getElementById('formRaport').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = { strategy: 'all' };
  fd.forEach((v, k) => { if (v) body[k] = v; });
  document.querySelectorAll('.report-card').forEach(c => {
    c.querySelector('tbody').innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">Se calculează…</td></tr>';
    c.querySelector('.report-meta').innerHTML = '';
  });
  const r = await API.raport(body);
  if (!r.ok) { toast(r.error || 'Eroare', 'err'); return; }

  Object.entries(r.results).forEach(([key, res]) => {
    const card = document.querySelector(`.report-card[data-strategy="${key}"]`);
    if (!card) return;
    card.querySelector('.report-meta').innerHTML = `
      <span class="ms">${res.elapsed_ms} ms</span>
      <span>${res.network_payload_rows} rânduri prin rețea</span>
      <span>${res.rows.length} medici</span>
    `;
    const tbody = card.querySelector('tbody');
    tbody.innerHTML = res.rows.map(row => `
      <tr>
        <td>Dr. ${row.nume || '?'} ${row.prenume || ''}</td>
        <td>${(row.salariu || 0).toLocaleString('ro-RO', { style: 'currency', currency: 'RON' })}</td>
        <td>${row.nr_pacienti}</td>
        <td>${(row.total_facturat || 0).toLocaleString('ro-RO', { style: 'currency', currency: 'RON' })}</td>
      </tr>
    `).join('') || '<tr><td colspan="4" class="muted" style="text-align:center;">Niciun rezultat.</td></tr>';
  });
  refreshLog(); refreshNetwork();
});

// Buttons
document.getElementById('btnRefresh').addEventListener('click', refreshAll);
document.getElementById('btnReset').addEventListener('click', async () => {
  if (!confirm('Reset complet al rețelei distribuite (toate datele revin la setul demo)?')) return;
  await API.reset();
  toast('Sistem resetat', 'ok');
  await refreshAll();
});
document.getElementById('btnClearLog').addEventListener('click', async () => {
  await API.clearLog(); refreshLog();
});

async function refreshAll() {
  renderTopology();
  await Promise.all([
    refreshNetwork(),
    refreshKPIs(),
    refreshPacienti(document.getElementById('filterPacientNod').value),
    refreshProgramari(),
    refreshFacturi(),
    refreshMedici(),
    refreshCataloage(),
    refreshLog(),
  ]);
}

refreshAll();
