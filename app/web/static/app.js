const $ = (id) => document.getElementById(id);

function get(obj, path, fallback) {
  let cur = obj;
  for (const key of path.split('.')) {
    if (cur === undefined || cur === null) return fallback;
    cur = cur[key];
  }
  return cur === undefined || cur === null || cur === '' ? fallback : cur;
}

async function api(path, options = {}) {
  const timeoutMs = options.timeoutMs || 15000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = { ...(options.headers || {}), ...(options.body ? { 'Content-Type': 'application/json' } : {}) };
  try {
    const res = await fetch(path, { ...options, headers, signal: controller.signal });
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
      const msg = data.detail || data.error || text || `HTTP ${res.status}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  } catch (err) {
    if (err && err.name === 'AbortError') throw new Error(`Request quá lâu: ${path}`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function toast(msg) {
  const el = $('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.add('hidden'), 4200);
}

async function withButton(btn, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Đang xử lý...';
  try { return await fn(); }
  catch (err) { toast(err.message || String(err)); throw err; }
  finally { btn.disabled = false; btn.textContent = old; }
}

function badge(el, text, cls = 'muted') {
  if (!el) return;
  el.className = `badge ${cls}`;
  el.textContent = text;
}

function value(v, fallback = '-') {
  return v === undefined || v === null || v === '' ? fallback : v;
}

function tokenGroupsText(groups) {
  groups = groups || [];
  if (!groups.length) return '-';
  return groups.map(g => `Account ${g.slot}: ${g.logged_in_workers}/${g.workers}`).join(' · ');
}

function renderOverview(data) {
  const count = Number(data.worker_count || 8);
  const minReady = Number(data.min_ready_workers || count);
  const tokensRequired = Number(data.tokens_required || (count >= 16 ? 2 : 1));
  if ($('modeSelect')) $('modeSelect').value = String(count);
  if ($('workerMode')) $('workerMode').textContent = `${count} worker`;
  if ($('workerModeDetail')) $('workerModeDetail').textContent = `Tối thiểu ${minReady} READY · ${tokensRequired} account`;
  badge($('modeBadge'), `${count} worker · min ${minReady} READY`, 'muted');
  const tokenTwo = $('tokenInput2');
  if (tokenTwo) tokenTwo.classList.toggle('hidden', tokensRequired < 2 && count < 16);
}

function renderNodes(nodes) {
  const box = $('nodesBox');
  if (!box) return;
  nodes = nodes || [];
  if (!nodes.length) {
    box.textContent = 'Không có worker.';
    return;
  }
  box.innerHTML = '';
  nodes.forEach(n => {
    const card = document.createElement('div');
    card.className = 'node-card';
    const active = n.active !== false;
    const cls = !active ? 'muted' : n.ready ? 'ok' : n.connected ? 'warn' : 'bad';
    const state = !active ? 'INACTIVE' : n.ready ? 'READY' : n.connected ? 'CONNECTED / NOT READY' : 'DOWN / OFFLINE';
    const last = get(n, 'last_recovery.reason', '') || get(n, 'last_recovery.final_error', '');
    card.innerHTML = `
      <span class="badge ${cls}">${state}</span>
      <strong>${value(n.id)} · ${value(n.current_ip)}</strong>
      <small>account ${value(n.token_slot, 1)} · ${value(n.country || n.country_hint)} · ${value(n.actual_server || n.hostname || n.server)}</small>
      <small>gateway: ${n.gateway_enabled === false ? 'disabled' : 'enabled'} · ${value(n.latency_ms)} ms</small>
      <small>fail: ${value(n.fail_count, 0)} · recover: ${value(n.recovery_count, 0)} · ${value(last, '')}</small>
    `;
    box.appendChild(card);
  });
}

function renderStatus(s) {
  const auth = s.auth || {};
  const groups = auth.groups || [];
  const connected = !!s.connected;
  const logged = !!(get(s, 'pia.logged_in', false) || auth.all_logged_in);
  const readyValue = get(s, 'gateway.ready_workers', null);
  const totalValue = get(s, 'gateway.total_workers', null);
  const ready = readyValue !== null ? readyValue : (s.nodes || []).filter(n => n.ready).length;
  const total = totalValue !== null ? totalValue : (s.nodes || []).filter(n => n.active !== false).length;
  const tokensRequired = auth.tokens_required || get(s, 'worker_mode.tokens_required', 1);
  const minReady = get(s, 'worker_mode.min_ready_workers', get(s, 'gateway.min_ready_workers', total || 8));

  badge($('mainBadge'), connected ? `${ready}/${total} READY` : logged ? 'Logged in' : 'Not connected', connected ? 'ok' : logged ? 'warn' : 'bad');
  $('mainTitle').textContent = connected ? `Gateway đang ra IP ${value(s.current_ip)}` : logged ? 'Đã login, đang recover worker' : 'Chưa login PIA';
  $('mainSub').innerHTML = `SOCKS5 gateway cố định: <code>${value(get(s, 'proxies.socks5', s.proxy))}</code>`;
  $('currentIp').textContent = value(s.current_ip);
  $('serverInfo').textContent = `${value(s.country || get(s, 'pia.country', ''))} · ${value(s.actual_server || get(s, 'pia.server', '') || get(s, 'pia.hostname', ''))}`;
  $('vpnState').textContent = connected ? `${ready}/${total} READY` : logged ? 'Logged in' : 'Offline';
  $('vpnDetail').textContent = tokenGroupsText(groups);
  $('proxyUrl').textContent = value(get(s, 'proxies.socks5', s.proxy));
  $('workerMode').textContent = `${get(s, 'worker_mode.worker_count', total || 8)} worker`;
  $('workerModeDetail').textContent = `Tối thiểu ${minReady} READY · ${tokensRequired} account · ${tokenGroupsText(groups)}`;
  badge($('authBadge'), logged ? tokenGroupsText(groups) : `${tokensRequired} account cần login`, logged ? 'ok' : 'bad');
  if ($('modeSelect')) $('modeSelect').value = String(get(s, 'worker_mode.worker_count', total || 8));
  badge($('modeBadge'), `${get(s, 'worker_mode.worker_count', total || 8)} worker · min ${minReady} READY`, get(s, 'worker_mode.ready_policy_ok', false) ? 'ok' : 'warn');
  const tokenTwo = $('tokenInput2');
  if (tokenTwo) tokenTwo.classList.toggle('hidden', tokensRequired < 2 && Number($('modeSelect').value || 8) < 16);
  renderNodes(s.nodes || []);
}

async function refreshOverview() {
  const data = await api('/api/mode', { timeoutMs: 5000 });
  renderOverview(data);
  return data;
}

async function refreshStatus() {
  const s = await api('/api/status', { timeoutMs: 12000 });
  renderStatus(s);
  return s;
}

async function applyMode() {
  const workerCount = Number($('modeSelect').value || 8);
  const data = await api('/api/mode', {
    method: 'POST',
    body: JSON.stringify({ worker_count: workerCount }),
    timeoutMs: 8000,
  });
  renderOverview(data.overview || data);
  toast(`Đã chuyển sang chế độ ${workerCount} worker.`);
  refreshStatus().catch(err => toast(err.message));
}

async function updateTokens() {
  const code = $('tokenInput').value.trim();
  const token2 = $('tokenInput2') && !$('tokenInput2').classList.contains('hidden') ? $('tokenInput2').value.trim() : '';
  if (!code && !token2) throw new Error('Bạn chưa nhập account cần cập nhật.');
  const data = await api('/api/tokens', {
    method: 'POST',
    body: JSON.stringify({ token_1: code || null, token_2: token2 || null, persist: $('persistToken').checked, apply: true }),
    timeoutMs: 90000,
  });
  $('tokenInput').value = '';
  if ($('tokenInput2')) $('tokenInput2').value = '';
  toast(data.ok ? 'Đã cập nhật account và áp dụng lên worker.' : 'Account đã lưu; một số worker đang recover.');
  await refreshStatus();
}

async function logout() {
  await api('/api/logout', { method: 'POST', timeoutMs: 90000 });
  toast('Đã logout và xóa account đã lưu.');
  await refreshStatus();
}

async function randomIp() {
  const data = await api('/api/random-ip', { method: 'POST', timeoutMs: 45000 });
  renderStatus(data);
  const selected = get(data, 'country_pool.selected_country', data.country);
  toast(selected ? `Đã rotate worker qua ${selected}` : 'Đã rotate một worker phía sau gateway.');
}

async function recoverWorkers() {
  const data = await api('/api/recover', {
    method: 'POST',
    body: JSON.stringify({ force: false }),
    timeoutMs: 45000,
  });
  toast(`Recover: ${data.ready_count}/${data.total_workers} worker READY.`);
  await refreshStatus();
}

function renderTest(data) {
  const ok = !!(data.socks5_ok && data.ip_check_ok);
  $('testResult').className = `result ${ok ? 'ok' : 'bad'}`;
  $('testResult').innerHTML = `
    <div class="kv">
      <b>Trạng thái</b><span>${ok ? 'OK' : 'FAIL'}</span>
      <b>IP</b><span>${value(data.current_ip)}</span>
      <b>Latency</b><span>${value(data.latency_ms)} ms</span>
      <b>Server</b><span>${value(data.actual_server)}</span>
      <b>Lỗi</b><span>${value(data.error)}</span>
    </div>`;
}

async function loadLogs() {
  const data = await api('/api/logs?tail=160', { timeoutMs: 20000 });
  $('logsBox').textContent = [
    '--- pia status ---',
    data.pia_status || '',
    '',
    '--- docker logs ---',
    data.docker_logs || '',
  ].join('\n');
}

function wire() {
  $('refreshBtn').onclick = () => withButton($('refreshBtn'), refreshStatus);
  if ($('recoverBtn')) $('recoverBtn').onclick = () => withButton($('recoverBtn'), recoverWorkers);
  if ($('modeBtn')) $('modeBtn').onclick = () => withButton($('modeBtn'), applyMode);
  if ($('modeSelect')) $('modeSelect').onchange = () => {
    const tokenTwo = $('tokenInput2');
    if (tokenTwo) tokenTwo.classList.toggle('hidden', Number($('modeSelect').value || 8) < 16);
  };
  $('loginBtn').onclick = () => withButton($('loginBtn'), updateTokens);
  $('logoutBtn').onclick = () => withButton($('logoutBtn'), logout);
  $('randomBtn').onclick = () => withButton($('randomBtn'), randomIp);
  $('testBtn').onclick = () => withButton($('testBtn'), async () => renderTest(await api('/api/test-proxy', { timeoutMs: 20000 })));
  $('logsBtn').onclick = () => withButton($('logsBtn'), loadLogs);
}

async function init() {
  wire();
  try { await refreshOverview(); } catch (e) { toast(e.message); }
  refreshStatus().catch(e => {
    $('nodesBox').textContent = 'Status đang tải chậm do worker đang restart/recover. Bấm Refresh sau vài giây.';
    toast(e.message);
  });
}

init();
