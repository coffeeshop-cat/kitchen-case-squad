import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createCase, getCase, confirmCase, updateStep, openEventStream, getHealth } from './api.js';

const AGENT_LABEL = {
  planner: '食材侦探',
  chef: '主厨顾问',
  buyer: '采购员',
  timekeeper: '计时员'
};
const AGENT_LIST = ['planner', 'chef', 'buyer', 'timekeeper'];

function unitQty(item) {
  return `${item.qty}${item.unit}`;
}

function ItemForm({ item, onChange, onRemove, onStateChange }) {
  return (
    <li className={`item-card ${item.state === 'discard' ? 'item-discard' : ''}`}>
      <div className="item-row">
        <div className="field field-name">
          <label htmlFor={`name-${item.id}`}>食材名称</label>
          <input id={`name-${item.id}`} value={item.name}
            onChange={(e) => onChange(item.id, { name: e.target.value })} />
        </div>
        <div className="field field-qty">
          <label htmlFor={`qty-${item.id}`}>数量</label>
          <input id={`qty-${item.id}`} type="number" min="0" step="0.1" value={item.qty}
            onChange={(e) => onChange(item.id, { qty: e.target.value === '' ? '' : Number(e.target.value) })} />
        </div>
        <div className="field field-unit">
          <label htmlFor={`unit-${item.id}`}>单位</label>
          <input id={`unit-${item.id}`} value={item.unit}
            onChange={(e) => onChange(item.id, { unit: e.target.value })} />
        </div>
        <div className="field field-expiry">
          <label htmlFor={`expiry-${item.id}`}>保质日期（可选）</label>
          <input id={`expiry-${item.id}`} type="date" value={item.expiry || ''}
            onChange={(e) => onChange(item.id, { expiry: e.target.value || null })} />
        </div>
      </div>
      <div className="item-actions">
        <div className="state-toggle" role="radiogroup" aria-label={`「${item.name}」的处置状态`}>
          <button type="button" className={item.state === 'usable' ? 'active' : ''} onClick={() => onStateChange(item.id, 'usable')}>可用</button>
          <button type="button" className={item.state === 'discard' ? 'active' : ''} onClick={() => onStateChange(item.id, 'discard')}>弃用</button>
        </div>
        <button type="button" className="btn-ghost" onClick={() => onRemove(item.id)}>移除</button>
      </div>
    </li>
  );
}

export default function App() {
  const [mode, setMode] = useState('start'); // start | review | planned | insufficient | error
  const [health, setHealth] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [file, setFile] = useState(null);
  const [items, setItems] = useState([]);
  const [caseData, setCaseData] = useState(null);
  const [events, setEvents] = useState([]);
  const [verdict, setVerdict] = useState(null);
  const [streamState, setStreamState] = useState('idle'); // idle | connecting | open | done | lost
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [recoveredSteps, setRecoveredSteps] = useState([]);
  const [ticking, setTicking] = useState([]);
  const closeRef = useRef(null);
  const logRef = useRef(null);
  const previewBlob = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  // 重进 ?case=<id> 恢复
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const cid = params.get('case');
    if (!cid) return;
    setLoading(true);
    getCase(cid).then((c) => {
      setCaseData(c);
      setItems(c.items || []);
      setEvents(c.events || []);
      setVerdict(c.verdict);
      setRecoveredSteps(c.completed_steps || []);
      setPreviewUrl(null);
      setMode(c.status === 'review' ? 'review' : (c.verdict && c.verdict.status === 'insufficient' ? 'insufficient' : (c.verdict ? 'planned' : 'review')));
      if (c.status === 'planned' && !c.verdict) {
        startStream(c);
      }
    }).catch((e) => {
      setError(`恢复案例失败：${e.message}`);
      setMode('error');
    }).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => { if (closeRef.current) closeRef.current(); }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const usableCount = useMemo(() => items.filter((i) => i.state === 'usable').length, [items]);
  const needReview = useMemo(() => items.some((i) => i.state === 'review'), [items]);
  const anyEmpty = useMemo(() => items.some((i) => !i.name.trim() || !Number(i.qty) || Number(i.qty) <= 0 || !i.unit.trim()), [items]);

  function updateItem(id, patch) {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }
  function removeItem(id) {
    setItems((prev) => prev.filter((i) => i.id !== id));
  }
  function setState(id, state) {
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, state } : i)));
  }
  function addItem() {
    const id = 'local-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);
    setItems((prev) => [...prev, { id, name: '', qty: 1, unit: '', state: 'usable', expiry: null }]);
  }

  function pickFile(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    setFile(f);
    if (previewBlob.current) URL.revokeObjectURL(previewBlob.current);
    previewBlob.current = URL.createObjectURL(f);
    setPreviewUrl(previewBlob.current);
  }

  async function start(photo) {
    setLoading(true);
    setError(null);
    setEvents([]);
    setVerdict(null);
    try {
      const c = await createCase(photo || null);
      setCaseData(c);
      setItems(c.items || []);
      setMode(c.status === 'review' ? 'review' : (c.verdict ? (c.verdict.status === 'insufficient' ? 'insufficient' : 'planned') : 'review'));
      if (c.status === 'planned' && !c.verdict) startStream(c);
    } catch (e) {
      setError(`创建案例失败：${e.message}`);
      setMode('error');
    } finally {
      setLoading(false);
    }
  }

  function startStream(c) {
    setStreamState('connecting');
    setTicking([]);
    if (closeRef.current) closeRef.current();
    closeRef.current = openEventStream({
      id: c.id,
      onOpen: () => setStreamState('open'),
      onEvent: (s) => setEvents((prev) => {
        // 重连/恢复场景 SSE 会重放全量发言，按事件标识（或 round+agent 兜底）去重
        const keyOf = (e) => e.id != null ? `id:${e.id}` : `${e.round}:${e.agent}`;
        const key = keyOf(s);
        if (prev.some((e) => keyOf(e) === key)) return prev;
        return [...prev, s];
      }),
      onVerdict: (v) => {
        setVerdict(v);
        setCaseData((prev) => (prev ? { ...prev, verdict: v } : prev));
        setMode(v.status === 'insufficient' ? 'insufficient' : 'planned');
      },
      onError: () => setStreamState((prev) => (prev === 'done' ? prev : 'lost')),
      onDone: () => setStreamState('done')
    });
  }

  async function confirm() {
    if (!caseData) return;
    setLoading(true);
    setError(null);
    try {
      const c = await confirmCase(caseData.id, items);
      setCaseData(c);
      setItems(c.items || []);
      if (c.status === 'insufficient') {
        setMode('insufficient');
        setVerdict(null);
      } else {
        setMode('planned');
        // 快照与 SSE 会重放全量发言：流会带回完整 events，不预填同一数组，避免重复渲染
        setEvents([]);
        startStream(c);
        window.history.replaceState(null, '', `?case=${encodeURIComponent(c.id)}`);
      }
    } catch (e) {
      setError(`确认失败：${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function toggleStep(n, currentlyDone) {
    if (!caseData) return;
    if (currentlyDone) return; // 首轮：不撤销（后端契约只记录 done_at）
    try {
      const c = await updateStep(caseData.id, n, { done_at: new Date().toISOString() });
      setRecoveredSteps(c.completed_steps || []);
    } catch (e) {
      setError(`更新时序失败：${e.message}`);
    }
  }

  function reset() {
    if (closeRef.current) closeRef.current();
    closeRef.current = null;
    setCaseData(null);
    setItems([]);
    setEvents([]);
    setVerdict(null);
    setRecoveredSteps([]);
    setStreamState('idle');
    setMode('start');
    setError(null);
    setFile(null);
    if (previewBlob.current) { URL.revokeObjectURL(previewBlob.current); previewBlob.current = null; }
    setPreviewUrl(null);
    window.history.replaceState(null, '', window.location.pathname);
  }

  const groupedEvents = useMemo(() => {
    const byRound = new Map();
    for (const ev of events) {
      if (!byRound.has(ev.round)) byRound.set(ev.round, []);
      byRound.get(ev.round).push(ev);
    }
    return [...byRound.entries()].sort((a, b) => a[0] - b[0]);
  }, [events]);

  const provider = caseData?.mode ?? health?.mode;
  const modeLabel = provider === 'agentarts' ? 'AgentArts 会诊' : provider === 'demo' ? '本地演示' : '';
  const header = (
    <header className="header">
      <span className="brand-name">料理劫案现场</span>
      {modeLabel && <span className="header-sub">{modeLabel}</span>}
    </header>
  );

  if (mode === 'start') {
    return (
      <div className="shell">
        {header}
        <main className="start-main">
          <section className="start-operate">
            <h1>冰箱里还剩什么？</h1>
            <p className="start-lede">拍一张食材照，照着照片填好清单。</p>
            <div className="start-actions">
              <label className="btn-primary photo-action">
                拍照或选图
                <input className="photo-file" type="file" accept="image/jpeg,image/png,image/webp" onChange={pickFile} />
              </label>
            </div>
            {previewUrl && (
              <figure className="preview">
                <img src={previewUrl} alt="已选食材照片" />
                <figcaption>照片在本机预览。</figcaption>
              </figure>
            )}
            {file && <button type="button" className="btn-primary" disabled={loading} onClick={() => start(file)}>核对这张照片</button>}
            {loading && <p className="status" role="status">正在打开食材清单…</p>}
            {error && <p className="error" role="alert">{error}</p>}
          </section>
          <section className="start-sample" aria-label="示例清单">
            <h2>示例清单</h2>
            <dl className="sample-items">
              <div><dt>鸡蛋</dt><dd>3 个</dd></div>
              <div><dt>番茄</dt><dd>2 个</dd></div>
              <div><dt>米饭</dt><dd>300 克</dd></div>
            </dl>
            <button type="button" className="btn-secondary" disabled={loading} onClick={() => start(null)}>用示例试试</button>
          </section>
        </main>
      </div>
    );
  }

  if (mode === 'error') {
    return (
      <div className="shell">
        {header}
        <main className="start-main">
          <section className="start-operate">
            <h1>清单没打开</h1>
            <p className="error" role="alert">{error}</p>
            <button type="button" className="btn-primary" onClick={reset}>重新开始</button>
          </section>
        </main>
      </div>
    );
  }

  const inReview = mode === 'review';
  const streamBadge = { connecting: '连接会诊中……', open: '会诊进行中', done: '会诊结束', lost: '连接中断', idle: '' }[streamState];

  return (
    <div className="shell">
      {header}
      {error && <p className="error banner" role="alert">{error} <button type="button" className="btn-ghost" onClick={() => setError(null)}>关闭</button></p>}
      {loading && <p className="status banner">请求中……</p>}

      <main className="layout">
        <section className="pane pane-left" aria-label="食材与做饭计划">
          {inReview && (
            <>
              <h1 className="pane-title">核对食材</h1>
              {previewUrl && (
                <figure className="preview small">
                  <img src={previewUrl} alt="食材照片预览" />
                </figure>
              )}
              {caseData?.source === 'photo' && <p className="muted">照着照片添加食材，再选可用或弃用。</p>}
              <ul className="item-list">
                {items.map((item) => (
                  <ItemForm key={item.id} item={item} onChange={updateItem} onRemove={removeItem} onStateChange={setState} />
                ))}
              </ul>
              <div className="item-footer">
                <button type="button" className="btn-secondary" onClick={addItem}>添加食材</button>
                {items.length > 0 && <span className="muted small">{items.length} 项，{usableCount} 项可用</span>}
              </div>
              <div className="confirm-block">
                {needReview && <p className="muted small">给每项食材选「可用」或「弃用」。</p>}
                {anyEmpty && <p className="muted small">请补齐名称、数量和单位。</p>}
                {provider === 'agentarts' && <p className="muted small">只将确认可用的食材清单发给 AgentArts。</p>}
                <button type="button" className="btn-primary" disabled={needReview || anyEmpty || items.length === 0 || loading} onClick={confirm}>
                  {loading ? '正在安排做法…' : '生成做饭计划'}
                </button>
              </div>
            </>
          )}

          {verdict && verdict.status === 'insufficient' && (
            <div className="insufficient">
              <h3>食材不足</h3>
              <p>{verdict.note || '现有食材拼不出一道菜。'}</p>
                          </div>
          )}

          {verdict && verdict.status === 'ready' && (
            <div className="verdict-plan">
              <h1 className="dish-title">{verdict.title}</h1>
              <p className="muted small">
                {verdict.duration_min != null && <>用时约 {verdict.duration_min} 分钟 · </>}
                {verdict.servings != null && <>约 {verdict.servings} 人份 · </>}
                {verdict.purchase_count != null && <>{verdict.purchase_count === 0 ? '无需补购' : `补购 ${verdict.purchase_count} 项`}</>}
              </p>
              {verdict.used_items.length > 0 && (
                <ul className="used-items">
                  {verdict.used_items.map((u) => (
                    <li key={u.id}>{u.name} · {u.qty}{u.unit}</li>
                  ))}
                </ul>
              )}
              <h2>做法</h2>
              <ol className="steps">
                {verdict.steps.map((s) => {
                  const done = recoveredSteps.includes(s.n);
                  return (
                    <li key={s.n} className={done ? 'step done' : 'step'}>
                      <label>
                        <input type="checkbox" checked={done} onChange={() => toggleStep(s.n, done)} />
                        <span className="step-title">第 {s.n} 步 · {s.title}（{s.minutes} 分钟）</span>
                      </label>
                      <p className="step-detail">{s.detail}</p>
                    </li>
                  );
                })}
              </ol>
              {verdict.note && <p className="muted small">{verdict.note}</p>}
            </div>
          )}

          <button type="button" className="btn-ghost reset" onClick={reset}>换一组食材</button>
        </section>

        <section className="pane pane-right" aria-label="会诊记录">
          <h2 className="pane-title">会诊记录</h2>
          {streamBadge && <p className="stream-state">{streamBadge}</p>}
          {groupedEvents.length === 0 && (
            <p className="muted">{inReview ? '生成计划后可查看。' : (streamState === 'connecting' ? '正在整理记录…' : '暂无记录。')}</p>
          )}
          <div className="log" ref={logRef}>
            {groupedEvents.map(([round, evs]) => (
              <div key={round} className="round">
                <p className="round-label">第 {round} 轮</p>
                {evs.map((ev, i) => (
                  <blockquote key={i} className={`speak agent-${ev.agent}`}>
                    <cite>{AGENT_LABEL[ev.agent] || ev.agent}</cite>
                    <p>{ev.text}</p>
                  </blockquote>
                ))}
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
