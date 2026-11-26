const API = '';

export async function apiJson(path, options = {}) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    let detail = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      if (data && (data.detail || data.message || data.error)) {
        detail = typeof (data.detail || data.message || data.error) === 'string'
          ? (data.detail || data.message || data.error)
          : JSON.stringify(data.detail || data.error);
      }
    } catch { /* ignore */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export function getHealth() {
  return apiJson('/health');
}

export function createCase(photoFile) {
  const fd = new FormData();
  if (photoFile) fd.append('photo', photoFile);
  return apiJson('/cases', { method: 'POST', body: fd });
}

export function getCase(id) {
  return apiJson(`/cases/${encodeURIComponent(id)}`);
}

export function confirmCase(id, items) {
  return apiJson(`/cases/${encodeURIComponent(id)}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items })
  });
}

export function updateStep(id, n, payload) {
  return apiJson(`/cases/${encodeURIComponent(id)}/steps/${n}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export function openEventStream({ id, onEvent, onVerdict, onOpen, onError, onDone }) {
  const es = new EventSource(`/cases/${encodeURIComponent(id)}/events`);
  let closed = false;
  const close = () => { if (!closed) { closed = true; try { es.close(); } catch { /* ignore */ } } };
  es.addEventListener('open', () => onOpen && onOpen());
  es.addEventListener('agent_speak', (e) => {
    try { onEvent(JSON.parse(e.data)); } catch { /* ignore */ }
  });
  es.addEventListener('verdict', (e) => {
    try { onVerdict(JSON.parse(e.data)); } catch { /* ignore */ }
    close();
    onDone && onDone();
  });
  es.addEventListener('error', () => {
    onError && onError();
    // 服务端在 verdict 后关闭连接；此处仅报告，交由上层判定是否恢复
  });
  return close;
}
