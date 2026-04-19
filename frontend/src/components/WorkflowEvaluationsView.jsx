// Copyright 2026 Ivan Grosny
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { useCallback, useEffect, useMemo, useState } from 'react';

const PAGE_SIZE = 20;

const btnGhost = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 6, height: 26, padding: '0 10px',
  borderRadius: 6, border: '0.4px solid rgba(31,30,29,0.22)',
  background: 'transparent', color: '#3d3d3a',
  fontSize: 12, fontWeight: 500, fontFamily: 'var(--font-ui)',
  cursor: 'pointer', whiteSpace: 'nowrap',
  transition: 'background-color 0.15s ease',
};

// ── Helpers ───────────────────────────────────────────────────────────────

function formatDuration(ms) {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

function relativeTime(iso) {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function formatFullTime(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ── Status pill ───────────────────────────────────────────────────────────

function StatusPill({ status, size = 'sm' }) {
  const s = (status || '').toUpperCase();
  const map = {
    COMPLETED: { bg: '#e7f1da', fg: '#2f7613', dot: '#2f7613' },
    ERROR:     { bg: '#ffe8e8', fg: '#8c1e1e', dot: '#b33232' },
    RUNNING:   { bg: '#d3e5f8', fg: '#1b67b2', dot: '#2c84db' },
    SKIPPED:   { bg: '#f0eee6', fg: '#73726c', dot: '#9c9a92' },
  };
  const c = map[s] || { bg: '#f0eee6', fg: '#3d3d3a', dot: '#9c9a92' };
  const h = size === 'xs' ? 18 : 20;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      height: h, padding: '0 7px', borderRadius: 5,
      background: c.bg, color: c.fg,
      fontSize: size === 'xs' ? 10 : 11, fontWeight: 500,
      fontFamily: 'var(--font-ui)', letterSpacing: 0.2,
      textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: 5, background: c.dot,
      }} />
      {s || '—'}
    </span>
  );
}

// ── JSON tree viewer (lazy, collapsible) ──────────────────────────────────

function JsonValue({ value, depth = 0, initialOpen = false, keyName = null }) {
  const [open, setOpen] = useState(initialOpen || depth === 0);

  if (value === null) return <Primitive value="null" color="#9c9a92" italic />;
  if (value === undefined) return <Primitive value="undefined" color="#9c9a92" italic />;

  const t = typeof value;
  if (t === 'string') return <Primitive value={JSON.stringify(value)} color="#2f7613" wrap />;
  if (t === 'number' || t === 'bigint') return <Primitive value={String(value)} color="#1b67b2" />;
  if (t === 'boolean') return <Primitive value={String(value)} color="#875a08" />;

  const isArr = Array.isArray(value);
  const entries = isArr ? value : Object.entries(value);
  const count = isArr ? entries.length : entries.length;

  if (count === 0) {
    return (
      <span style={{ color: '#73726c', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
        {isArr ? '[]' : '{}'}
      </span>
    );
  }

  return (
    <span style={{ display: 'inline-block', verticalAlign: 'top' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          background: 'transparent', border: 'none',
          color: '#73726c', cursor: 'pointer', padding: 0,
          fontFamily: 'var(--font-mono)', fontSize: 12,
        }}
      >
        <span style={{
          display: 'inline-block', width: 10,
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform 0.12s ease',
        }}>▸</span>
        <span>
          {isArr ? `[${count}]` : `{${count}}`}
        </span>
      </button>
      {open && (
        <div style={{
          marginLeft: 14, paddingLeft: 10,
          borderLeft: '0.8px dashed rgba(31,30,29,0.12)',
        }}>
          {isArr
            ? value.map((item, i) => (
                <div key={i} style={{ padding: '1px 0', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  <span style={{ color: '#9c9a92', marginRight: 6 }}>{i}:</span>
                  <JsonValue value={item} depth={depth + 1} />
                </div>
              ))
            : entries.map(([k, v]) => (
                <div key={k} style={{ padding: '1px 0', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                  <span style={{ color: '#433872', marginRight: 6 }}>
                    {JSON.stringify(k)}:
                  </span>
                  <JsonValue value={v} depth={depth + 1} />
                </div>
              ))}
        </div>
      )}
    </span>
  );
}

function Primitive({ value, color, italic = false, wrap = false }) {
  return (
    <span style={{
      color: color || '#141413',
      fontStyle: italic ? 'italic' : 'normal',
      fontFamily: 'var(--font-mono)', fontSize: 12,
      wordBreak: wrap ? 'break-word' : 'normal',
      whiteSpace: wrap ? 'pre-wrap' : 'nowrap',
    }}>
      {value}
    </span>
  );
}

// ── Collapsible section ───────────────────────────────────────────────────

function Section({ title, count, defaultOpen = true, accent, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{
      border: '0.8px solid rgba(31,30,29,0.1)',
      borderRadius: 8,
      background: '#ffffff',
      overflow: 'hidden',
      marginBottom: 10,
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, width: '100%',
          padding: '8px 12px',
          background: accent || '#faf9f5',
          border: 'none', borderBottom: open ? '0.8px solid rgba(31,30,29,0.08)' : 'none',
          color: '#141413',
          fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 600,
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span style={{
          display: 'inline-block', width: 10,
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform 0.12s ease',
          color: '#73726c',
        }}>▸</span>
        <span style={{ flex: 1 }}>{title}</span>
        {count != null && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 8,
            background: '#e8e6dc', color: '#3d3d3a', fontWeight: 500,
          }}>
            {count}
          </span>
        )}
      </button>
      {open && (
        <div style={{ padding: '10px 12px' }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ── Error block ───────────────────────────────────────────────────────────

function ErrorBlock({ text }) {
  if (!text) return null;
  return (
    <pre style={{
      margin: 0, padding: '10px 12px',
      background: '#ffe8e8', color: '#8c1e1e',
      border: '0.8px solid rgba(140,30,30,0.25)', borderRadius: 6,
      fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.5,
      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      maxHeight: 320, overflow: 'auto',
    }}>
      {text}
    </pre>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────

export default function WorkflowEvaluationsView({ workflowName }) {
  const [page, setPage] = useState(1);
  const [listData, setListData] = useState(null);
  const [listLoading, setListLoading] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  // Reset when workflow changes
  useEffect(() => {
    setPage(1);
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
  }, [workflowName]);

  const fetchList = useCallback(() => {
    setListLoading(true);
    fetch(`/api/workflows/${workflowName}/evaluations?page=${page}&page_size=${PAGE_SIZE}`)
      .then(r => r.json())
      .then(data => {
        setListData(data);
        // Auto-select first row if nothing selected
        if (!selectedId && data.evaluations && data.evaluations.length > 0) {
          setSelectedId(data.evaluations[0].run_id);
        }
      })
      .catch(() => setListData({ evaluations: [], total: 0 }))
      .finally(() => setListLoading(false));
  }, [workflowName, page, selectedId]);

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchDetail = useCallback(() => {
    if (!selectedId) return;
    setDetailLoading(true);
    setDetailError(null);
    fetch(`/api/workflows/${workflowName}/evaluations/${selectedId}`)
      .then(async r => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.error || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(setDetail)
      .catch(e => { setDetailError(String(e.message || e)); setDetail(null); })
      .finally(() => setDetailLoading(false));
  }, [workflowName, selectedId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  const total = listData?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const evaluations = listData?.evaluations || [];

  const downloadJson = useCallback(() => {
    if (!detail) return;
    const blob = new Blob([JSON.stringify(detail, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${detail.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [detail]);

  const copyJson = useCallback(() => {
    if (!detail) return;
    navigator.clipboard?.writeText(JSON.stringify(detail, null, 2));
  }, [detail]);

  return (
    <div style={{
      display: 'flex', width: '100%', height: '100%',
      background: '#faf9f5', fontFamily: 'var(--font-ui)',
    }}>

      {/* ── Left: run list ── */}
      <aside style={{
        width: 320, flexShrink: 0,
        background: '#ffffff',
        borderRight: '0.8px solid rgba(31,30,29,0.1)',
        display: 'flex', flexDirection: 'column',
        minHeight: 0,
      }}>
        <div style={{
          display: 'flex', alignItems: 'center',
          padding: '10px 14px',
          borderBottom: '0.8px solid rgba(31,30,29,0.08)',
          flexShrink: 0,
        }}>
          <span style={{
            fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
            letterSpacing: '0.04em', color: '#73726c', flex: 1,
          }}>
            Runs ({total})
          </span>
          <button
            onClick={fetchList}
            title="Refresh"
            style={{ ...btnGhost, width: 24, height: 24, padding: 0 }}
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <path d="M13.5 3.5 A6 6 0 1 0 14 8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
              <path d="M13.5 1.5 L13.5 3.5 L11.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {listLoading && evaluations.length === 0 && (
            <div style={{ padding: 16, fontSize: 12, color: '#9c9a92' }}>Loading…</div>
          )}
          {!listLoading && evaluations.length === 0 && (
            <div style={{ padding: 16, fontSize: 12, color: '#73726c', lineHeight: 1.5 }}>
              No evaluations yet. Run the workflow to create one —
              each run saves to <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>workflows/{workflowName}/evaluations/</code>.
            </div>
          )}
          {evaluations.map(e => {
            const isSel = e.run_id === selectedId;
            return (
              <button
                key={e.run_id}
                onClick={() => setSelectedId(e.run_id)}
                style={{
                  display: 'block', width: '100%',
                  padding: '10px 14px',
                  border: 'none',
                  borderLeft: isSel ? '2px solid #141413' : '2px solid transparent',
                  borderBottom: '0.4px solid rgba(31,30,29,0.06)',
                  background: isSel ? '#f5f4ed' : 'transparent',
                  textAlign: 'left', cursor: 'pointer',
                  fontFamily: 'var(--font-ui)',
                  transition: 'background-color 0.12s ease',
                }}
                onMouseEnter={ev => { if (!isSel) ev.currentTarget.style.background = '#faf9f5'; }}
                onMouseLeave={ev => { if (!isSel) ev.currentTarget.style.background = 'transparent'; }}
              >
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  marginBottom: 5,
                }}>
                  <StatusPill status={e.status} size="xs" />
                  <span style={{
                    fontSize: 11, color: '#73726c',
                    fontFamily: 'var(--font-mono)', flex: 1,
                    overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {e.run_id}
                  </span>
                </div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  fontSize: 11, color: '#73726c',
                }}>
                  <span title={formatFullTime(e.started_at)}>{relativeTime(e.started_at)}</span>
                  <span style={{ color: '#c2c0b6' }}>·</span>
                  <span>{formatDuration(e.duration_ms)}</span>
                  {e.node_count > 0 && (
                    <>
                      <span style={{ color: '#c2c0b6' }}>·</span>
                      <span>{e.node_count} node{e.node_count === 1 ? '' : 's'}</span>
                    </>
                  )}
                  {e.total_tokens > 0 && (
                    <>
                      <span style={{ color: '#c2c0b6' }}>·</span>
                      <span>{e.total_tokens.toLocaleString()} tok</span>
                    </>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {totalPages > 1 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 14px',
            borderTop: '0.8px solid rgba(31,30,29,0.08)',
            background: '#faf9f5',
            flexShrink: 0,
          }}>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              style={{
                ...btnGhost,
                opacity: page <= 1 ? 0.4 : 1,
                cursor: page <= 1 ? 'default' : 'pointer',
              }}
            >
              ← Prev
            </button>
            <span style={{ fontSize: 11, color: '#73726c', flex: 1, textAlign: 'center' }}>
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              style={{
                ...btnGhost,
                opacity: page >= totalPages ? 0.4 : 1,
                cursor: page >= totalPages ? 'default' : 'pointer',
              }}
            >
              Next →
            </button>
          </div>
        )}
      </aside>

      {/* ── Right: detail ── */}
      <section style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        minWidth: 0, minHeight: 0,
      }}>
        {!selectedId && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#9c9a92', fontSize: 13,
          }}>
            Select a run on the left to inspect it.
          </div>
        )}

        {selectedId && detailLoading && !detail && (
          <div style={{ padding: 20, fontSize: 12, color: '#9c9a92' }}>Loading…</div>
        )}

        {selectedId && detailError && (
          <div style={{ padding: 20 }}>
            <ErrorBlock text={detailError} />
          </div>
        )}

        {detail && (
          <>
            {/* Header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 16px',
              background: '#ffffff',
              borderBottom: '0.8px solid rgba(31,30,29,0.1)',
              flexShrink: 0,
            }}>
              <StatusPill status={detail.status} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 12, color: '#141413',
                  fontWeight: 500,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {detail.run_id}
                </div>
                <div style={{
                  display: 'flex', gap: 10, fontSize: 11, color: '#73726c',
                  marginTop: 3,
                }}>
                  <span title={formatFullTime(detail.started_at)}>
                    {relativeTime(detail.started_at)}
                  </span>
                  <span style={{ color: '#c2c0b6' }}>·</span>
                  <span>{formatDuration(detail.duration_ms)}</span>
                  {detail.tokens?.total_tokens > 0 && (
                    <>
                      <span style={{ color: '#c2c0b6' }}>·</span>
                      <span>{detail.tokens.total_tokens.toLocaleString()} tokens</span>
                    </>
                  )}
                </div>
              </div>
              <button onClick={copyJson} style={btnGhost} title="Copy JSON to clipboard">
                Copy
              </button>
              <button onClick={downloadJson} style={btnGhost} title="Download JSON">
                Download
              </button>
            </div>

            {/* Body */}
            <div style={{ flex: 1, overflow: 'auto', padding: 14, minHeight: 0 }}>
              {detail.error && (
                <Section title="Run error" accent="#ffe8e8" defaultOpen>
                  <ErrorBlock text={detail.error} />
                </Section>
              )}

              <Section title="Initial payload" defaultOpen>
                <JsonValue value={detail.initial_payload || {}} initialOpen />
              </Section>

              {(detail.nodes || []).map((node, i) => (
                <NodeSection key={`${node.node_id}-${i}`} node={node} />
              ))}

              {detail.final_payload != null && (
                <Section title="Final payload" defaultOpen={false}>
                  <JsonValue value={detail.final_payload} initialOpen />
                </Section>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function NodeSection({ node }) {
  const status = (node.status || '').toUpperCase();
  const accent = status === 'ERROR' ? '#ffe8e8'
    : status === 'COMPLETED' ? '#f5faef'
    : status === 'SKIPPED' ? '#f5f4ed'
    : '#faf9f5';

  const title = (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <StatusPill status={node.status} size="xs" />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#141413' }}>
        {node.node_id}
      </span>
      <span style={{ fontSize: 11, color: '#73726c', fontWeight: 400 }}>
        {formatDuration(node.duration_ms)}
      </span>
      {node.tokens?.total_tokens > 0 && (
        <span style={{ fontSize: 11, color: '#73726c', fontWeight: 400 }}>
          · {node.tokens.total_tokens.toLocaleString()} tok
        </span>
      )}
    </span>
  );

  return (
    <Section title={title} accent={accent} defaultOpen={status === 'ERROR'}>
      <div style={{ display: 'grid', gap: 10 }}>
        <SubBlock label="Input">
          <JsonValue value={node.input ?? {}} initialOpen={false} />
        </SubBlock>
        {node.error ? (
          <SubBlock label="Error">
            <ErrorBlock text={node.error} />
          </SubBlock>
        ) : (
          <SubBlock label="Output">
            <JsonValue value={node.output ?? {}} initialOpen={false} />
          </SubBlock>
        )}
      </div>
    </Section>
  );
}

function SubBlock({ label, children }) {
  return (
    <div>
      <div style={{
        fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
        letterSpacing: '0.04em', color: '#73726c',
        marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{
        padding: '8px 10px',
        background: '#faf9f5',
        border: '0.4px solid rgba(31,30,29,0.08)',
        borderRadius: 6,
        overflow: 'auto',
        maxHeight: 360,
      }}>
        {children}
      </div>
    </div>
  );
}
