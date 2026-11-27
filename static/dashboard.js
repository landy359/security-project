'use strict';
const $ = id => document.getElementById(id);
const labels = {
  total: '전체',
  code: '코드',
  heap: '힙',
  stack: '스택',
  anon: '익명',
  other: '기타'
};
const phases = {
  idle: '대기',
  starting: '대상 준비 중',
  ready: '대상 실행 중',
  calibrating: '정상 측정 중',
  review: '기준값 검토',
  watching: '감시 중',
  frozen: '동결'
};
const levels = {
  ok: '정상',
  warning: '주의',
  danger: '위험',
  unknown: '미확인',
  info: '정보'
};
const hashNames = {
  match: '일치',
  mismatch: '불일치',
  unknown: '미확인'
};
const confirmations = {
  calibrate:
      '선택한 대상을 여러 번 실행해 기준을 측정합니다. 실행 중인 대상은 닫힙니다. 각 실행에서 평소 작업을 직접 수행하세요.',
  calibrate_manual: '새 프로세스로 기준을 측정합니다. 저장할 작업이 있으면 먼저 저장하세요. 각 실행에서 평소 작업을 마친 후 직접 완료 버튼을 누르세요.',
  save: '측정한 값과 코드 해시를 이 프로필의 정상 기준으로 저장할까요?',
  close: '현재 대상을 종료할까요? 대상의 저장하지 않은 작업과 진행 중인 측정은 사라질 수 있습니다.',
  resume: '대상을 일반 재개할까요?',
  freeze: '현재 대상 프로세스를 동결할까요?'
};
let state, busy = false, refreshing = false, loadId = 0, olderThan = 0, browsing = false;
let activeQuery = '', activeLevel = '', eventKey = '', eventBusy = false, eventGeneration = 0;
const fmt = v => v == null ? '—' : (v / 1024).toFixed(2);
const clock = ts => ts ? new Date(ts * 1000).toLocaleTimeString('ko-KR', {hour12: false}) : '—';
const date = ts => ts ? new Date(ts * 1000).toLocaleString('ko-KR', {hour12: false}) : '—';
function element(tag, text, cls) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}
function badge(text, style = 'info') {
  return element('span', text, 'badge ' + style);
}
function notice(msg) {
  $('notice').textContent = msg;
  $('notice').hidden = !msg;
}
for (const [key, label] of Object.entries(labels)) $('region').add(new Option(label, key));
function render(s) {
  if (state?.pid !== s.pid) {
    $('map-view').open = false;
    $('map-rows').textContent = '';
  }
  if (state?.profile !== s.profile) {
    eventGeneration++;
    browsing = false;
    eventKey = '';
    olderThan = 0;
    $('event-list').replaceChildren();
    $('more').hidden = true;
  }
  state = s;
  const select = $('target-select');
  const catalogKey = JSON.stringify(s.targets);
  if (select.dataset.catalog !== catalogKey) {
    select.dataset.catalog = catalogKey;
    select.replaceChildren();
    for (const target of s.targets) select.add(new Option(target.label, target.id));
  }
  select.value = s.target.id;
  select.disabled = busy || s.phase !== 'idle';
  $('target-hint').textContent = s.target.exercise;
  $('target-type').textContent = s.demo ? 'Linux · 시연 모드' : 'Linux';
  $('export').href = '/api/report.csv?' + new URLSearchParams({
    target: s.target.id, q: activeQuery, level: activeLevel
  });
  const phaseStyle = s.phase === 'frozen' ? 'danger' : s.phase === 'watching' ? 'ok' : 'info';
  $('phase').className = 'badge ' + phaseStyle;
  $('phase').textContent = phases[s.phase];
  $('updated').textContent = '수신 ' + clock(Date.now() / 1000);
  $('target').textContent = s.pid ? 'PID ' + s.pid + ' · Linux 상태 ' + (s.kernel ?? '…') +
          (s.started ? ' · 감시 시작 ' + clock(s.started) : '') :
                                    '대상을 실행하거나 정상 기준 측정을 시작하세요.';
  const phase = s.phase, live = phase === 'watching', frozen = phase === 'frozen';
  const show = {
    launch: phase === 'idle',
    close: !!s.pid,
    start: phase === 'ready' && !!s.bounds,
    stop: live,
    approve: live && !!Object.keys(s.issues).length && Object.values(s.issues).every(issue => issue.level === 'warning') && !s.allowed && !s.rss_error,
    freeze: live,
    resume: frozen,
    force_resume: frozen,
    hash: live || frozen,
    calibrate: ['idle', 'ready', 'review'].includes(phase),
    calibrate_manual: ['idle', 'ready', 'review'].includes(phase),
    finish_run: !!s.calibration?.manual && s.calibration.n >= s.settings.samples_per_run,
    save: phase === 'review'
  };
  document.querySelectorAll('[data-act]').forEach(b => {
    b.hidden = !show[b.dataset.act];
    b.disabled = busy;
  });
  $('total').textContent = fmt(s.rss?.total);
  const count = Object.keys(s.issues).length;
  $('issue-count').textContent = (live || frozen) && s.rss ? count : '—';
  $('risk-note').textContent = s.rss_error ? 'RSS 측정 실패' :
      s.allowed                            ? '이번 경고 허용' :
      count                                ? '기준 초과' :
                                             '기준 초과 없음';
  if (!live && !frozen) $('risk-note').textContent = '감시 대기';
  const h = s.hash;
  const hashStatus = h?.retry ? '재검사 예정' :
      h?.result === 'unknown' && h.consecutive_unverified >= 3 ? '검증 불가' :
      hashNames[h?.result] ?? '대기';
  confirmations.force_resume = '현재 코드 검사 결과는 ' + hashStatus +
      '입니다. 강제 재개하면 확인되지 않은 코드가 실행될 수 있습니다. ' +
      (s.demo ? '시연 대상은 최대 10초 뒤 재검사합니다. ' : '재개 직후 다시 검사합니다. ') +
      '계속할까요?';
  $('hash-status').textContent = hashStatus;
  $('hash-time').textContent = h ?
      '파일 기반 실행 코드 · ' + (h.checked ? '검사 제외 ' + h.excluded.length + '개' : '범위 확인 불가') :
      '파일 기반 실행 코드 · SHA-256';
  $('interval').textContent =
      'RSS ' + s.settings.rss_seconds + '초 · 코드 검사 ' + s.settings.hash_seconds + '초';
  const body = $('memory-rows');
  body.replaceChildren();
  for (const [key, label] of Object.entries(labels)) {
    const tr = element('tr'), limit = s.bounds?.[key];
    [label, fmt(s.rss?.[key]), fmt(limit?.limit), fmt(limit?.danger)].forEach(
        v => tr.append(element('td', v)));
    const status = element('td'), l = s.issues[key]?.level ?? 'ok';
    status.append(
        live || frozen ? (s.rss_error ? badge('미확인', 'unknown') : badge(levels[l], l)) :
                         element('span', '—'));
    tr.append(status);
    body.append(tr);
  }
  $('warning-text').textContent = frozen ?
      (s.freeze_reason === '코드 해시 불일치' ?
        '코드 해시 불일치로 동결했습니다. 일반 재개는 코드 일치가 확인되어야 합니다.' :
        '대상이 정지했습니다. 검사 결과를 확인하고 재개할 수 있습니다.') :
      s.rss_error ? 'RSS 미확인 · ' + s.rss_error :
      s.allowed   ? '사용자가 이번 경고를 허용했습니다. 기준값과 위험 표시는 유지됩니다.' :
      Object.values(s.issues).some(i => i.level === 'danger') ? '위험 경계를 초과했습니다. 코드 검사 결과를 확인하세요.' :
      count       ? '기준을 초과했습니다. 임시 허용 시 코드를 즉시 검사합니다.' :
      live        ? '현재 RSS 경고가 없습니다.' :
                    '감시를 시작하면 경고가 표시됩니다.';
  $('warnings')
      .replaceChildren(...Object.entries(s.issues).map(
          ([k, v]) => element(
              'li',
              labels[k] + ' · ' + levels[v.level] + ' · Limit보다 ' + fmt(v.excess) + ' MiB 초과 (' +
                  v.percent + '%)')));
  $('hash-summary').textContent = h ?
      '파일 기반 실행 매핑 ' + h.checked + '개 검사 · ' + hashStatus + ' · ' + clock(h.ts) + ' · ' + h.reason :
      '기준값 저장 후 감시를 시작하세요.';
  $('hash-detail').textContent = h ?
      JSON.stringify(
          {불일치: h.changes, 추가: h.added, 누락: h.missing, 읽기오류: h.errors, 범위밖: h.excluded}, null,
          2) :
      '검사 이력이 없습니다.';
  $('base-meta').textContent = s.bounds ?
      '정상 실행 ' + s.base_runs + '회 · 표본 ' + s.base_samples + '개 · 저장 ' + date(s.base_time) + ' · 실행 매핑 ' + s.checked_regions + '개 · 작업 중 추가 로드 ' + s.optional_regions + '개' :
      '저장된 기준값이 없습니다.';
  const c = s.calibration;
  $('cal-progress').textContent = c ? '정상 실행 ' + c.run + ' / ' + s.settings.runs + '회 · 표본 ' + c.n +
          (c.manual ? '개 (최소 ' + s.settings.samples_per_run + '개). 평소 작업을 마치면 이번 실행을 완료하세요. ' : ' / ' + s.settings.samples_per_run + '개. ') + s.target.exercise :
      s.candidate ? '아래 결과를 확인한 뒤 측정값을 저장하세요.' :
                    '각 실행에서 ' + s.settings.samples_per_run + '개 표본을 수집하며 총 ' +
          s.settings.runs + '회 실행합니다.';
  $('candidate').replaceChildren();
  if (s.candidate) {
    const table = element('table'), head = element('tr');
    ['영역 (MiB)', '최소', '최대', 'Limit', '위험 경계'].forEach(v => head.append(element('th', v)));
    table.append(head);
    for (const [k, label] of Object.entries(labels)) {
      const row = element('tr'), b = s.candidate[k];
      [label, fmt(b.min), fmt(b.max), fmt(b.limit), fmt(b.danger)].forEach(
          v => row.append(element('td', v)));
      table.append(row);
    }
    $('candidate').append(table);
    if (s.candidate_optional.length) {
      const detail = element('details');
      detail.append(element('summary', '작업 중 추가로 로드된 실행 매핑 ' + s.candidate_optional.length + '개'),
                    element('pre', s.candidate_optional.join('\n')));
      $('candidate').append(detail);
    }
  }
  draw();
}
function draw() {
  if (!state) return;
  const cv = $('chart'), width = Math.max(180, cv.clientWidth), height = cv.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  cv.width = width * dpr;
  cv.height = height * dpr;
  const ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  const key = $('region').value || 'total', points = state.history, bounds = state.bounds?.[key];
  ctx.font = '12px system-ui';
  ctx.fillStyle = '#516660';
  if (!points.length) {
    ctx.textAlign = 'center';
    ctx.fillText('감시가 시작되면 RSS 추이가 표시됩니다.', width / 2, height / 2);
    return;
  }
  const left = 49, right = width - 14, top = 16, bottom = height - 26;
  const max = Math.max(1, bounds?.danger || 0, ...points.map(p => p.rss[key])) * 1.08;
  const last = points[points.length - 1], start = points[0].ts;
  const alerts = state.hash_alerts.filter(t => t >= start), end = Math.max(last.ts, ...alerts);
  const span = Math.max(state.settings.rss_seconds, end - start);
  const x = t => left + (right - left) * (t - start) / span, y = v => bottom - (bottom - top) * v / max;
  function line(yy, color, dash) {
    ctx.beginPath();
    ctx.setLineDash(dash);
    ctx.strokeStyle = color;
    ctx.moveTo(left, yy);
    ctx.lineTo(right, yy);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  for (let i = 0; i <= 3; i++) {
    const value = max * i / 3;
    line(y(value), '#dce4dc', []);
    ctx.textAlign = 'right';
    ctx.fillText(fmt(value), left - 5, y(value) + 4);
  }
  if (bounds) {
    line(y(bounds.limit), '#a16a10', [5, 4]);
    line(y(bounds.danger), '#ad4950', [3, 4]);
  }
  ctx.strokeStyle = '#087d58';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((p, i) => {
    if (i === 0)
      ctx.moveTo(x(p.ts), y(p.rss[key]));
    else
      ctx.lineTo(x(p.ts), y(p.rss[key]));
  });
  ctx.stroke();
  for (const p of points) {
    const v = p.rss[key];
    if (!bounds || v <= bounds.limit) continue;
    ctx.fillStyle = v > bounds.danger ? '#ad4950' : '#a16a10';
    ctx.beginPath();
    ctx.arc(x(p.ts), y(v), 3, 0, 2 * Math.PI);
    ctx.fill();
  }
  ctx.fillStyle = '#087d58';
  ctx.beginPath();
  ctx.arc(x(last.ts), y(last.rss[key]), 3, 0, 2 * Math.PI);
  ctx.fill();
  for (const t of alerts) {
    const xx = x(t);
    ctx.strokeStyle = '#9b3036';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(xx, top);
    ctx.lineTo(xx, bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#9b3036';
    ctx.beginPath();
    ctx.moveTo(xx - 4, top);
    ctx.lineTo(xx + 4, top);
    ctx.lineTo(xx, top + 6);
    ctx.fill();
  }
  ctx.fillStyle = '#516660';
  ctx.textAlign = 'left';
  ctx.fillText(clock(start), left, height - 6);
  ctx.textAlign = 'right';
  ctx.fillText(clock(end), right, height - 6);
}
async function fetchJSON(url, options) {
  const r = await fetch(url, options);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(data.error || '서버 응답 오류 (' + r.status + ')');
  return data;
}
async function refresh() {
  if (busy || refreshing) return;
  refreshing = true;
  const id = ++loadId;
  try {
    const s = await fetchJSON('/api/state');
    if (id !== loadId || busy) return;
    render(s);
    $('connection').textContent = '● 연결됨';
    if (!browsing) await events(false);
  } catch (e) {
    $('connection').textContent = '연결 확인 필요';
    notice(e.message);
  } finally {
    refreshing = false;
  }
}
async function action(name, extra = {}) {
  if (busy || !state) return;
  if (confirmations[name] && !window.confirm(confirmations[name])) return;
  const revision = state.revision;
  busy = true;
  loadId++;
  render(state);
  notice('');
  try {
    const s = await fetchJSON('/api/action/' + name, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Control-Token': document.querySelector('meta[name=control-token]').content
      },
      body: JSON.stringify({revision, ...extra})
    });
    render(s);
    if (!browsing) await events(false);
  } catch (e) {
    notice(e.message);
  } finally {
    busy = false;
    if (state) render(state);
    await refresh();
  }
}
function eventRow(row) {
  const d = element('details', null, 'event'), s = element('summary');
  s.append(
      element('time', date(row.ts)), badge(levels[row.level] ?? row.level, row.level),
      element('span', row.message));
  d.dataset.id = row.id;
  d.append(
      s,
      element(
          'pre',
          JSON.stringify(
              {ID: row.id, PID: row.pid, 프로필: row.profile, 유형: row.kind, ...row.detail}, null, 2)));
  return d;
}
async function events(append) {
  if (eventBusy) return;
  eventBusy = true;
  const generation = eventGeneration;
  try {
    const p = new URLSearchParams({target: state.target.id, q: activeQuery, level: activeLevel});
    $('export').href = '/api/report.csv?' + p;
    if (append) p.set('before', olderThan);
    const data = await fetchJSON('/api/events?' + p);
    if (generation !== eventGeneration) return;
    const key = activeQuery + '|' + activeLevel + '|' + (data.events[0]?.id ?? '');
    if (!append && eventKey === key) return;
    const list = $('event-list'),
          open = new Set(Array.from(list.querySelectorAll('details[open]'), d => d.dataset.id));
    if (!append) {
      eventKey = key;
      list.replaceChildren();
    }
    for (const row of data.events) {
      const d = eventRow(row);
      d.open = open.has(String(row.id));
      list.append(d);
    }
    if (!list.children.length) list.append(element('p', '조회된 이벤트가 없습니다.', 'empty'));
    if (data.events.length) olderThan = data.events[data.events.length - 1].id;
    $('more').hidden = !data.more;
  } catch (e) {
    notice(e.message);
  } finally {
    eventBusy = false;
    if (generation !== eventGeneration) events(false);
  }
}
document.querySelectorAll('[data-act]').forEach(b => {
  b.hidden = true;
  b.addEventListener('click', () => action(b.dataset.act));
});
$('target-select').addEventListener('change', e => action('select', {target: e.target.value}));
$('region').addEventListener('change', draw);
window.addEventListener('resize', draw);
$('map-view').addEventListener('toggle', async () => {
  if (!$('map-view').open) return;
  const pid = state?.pid;
  $('map-rows').textContent = '';
  $('map-note').textContent = '조회 중';
  try {
    const snap = await fetchJSON('/api/mappings');
    if (snap.pid !== pid || state?.pid !== pid) return;
    $('map-note').textContent = clock(snap.ts) + ' · 가상 주소 범위, 권한, 실제 RSS';
    $('map-rows').textContent = snap.mappings
                                    .map(
                                        r => labels[r.region] + '  ' + r.start + '–' + r.end + '  ' +
                                            r.perms + '  ' + r.rss + ' KiB  ' + r.path)
                                    .join('\n');
  } catch (e) {
    $('map-note').textContent = e.message;
  }
});
$('more').addEventListener('click', () => {
  browsing = true;
  events(true);
});
$('filter').addEventListener('submit', e => {
  e.preventDefault();
  activeQuery = $('query').value;
  activeLevel = $('level').value;
  browsing = false;
  eventKey = '';
  olderThan = 0;
  eventGeneration++;
  events(false);
});
refresh();
setInterval(refresh, 1000);
