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

import { useCallback, useEffect, useState } from 'react';

const btnPrimary = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 6, height: 30, padding: '0 12px',
  borderRadius: 7, border: 'none',
  background: '#141413', color: '#ffffff',
  fontSize: 12, fontWeight: 500, fontFamily: 'var(--font-ui)',
  cursor: 'pointer', whiteSpace: 'nowrap',
  transition: 'opacity 0.15s ease',
};

const btnGhost = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 6, height: 28, padding: '0 10px',
  borderRadius: 7, border: '0.4px solid rgba(31,30,29,0.22)',
  background: 'transparent', color: '#3d3d3a',
  fontSize: 12, fontWeight: 500, fontFamily: 'var(--font-ui)',
  cursor: 'pointer', whiteSpace: 'nowrap',
  transition: 'background-color 0.15s ease',
};

function CollectionIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <ellipse cx="8" cy="4" rx="5.5" ry="2" stroke="currentColor" strokeWidth="1.2" />
      <path d="M2.5 4 V8 C2.5 9.1 4.96 10 8 10 C11.04 10 13.5 9.1 13.5 8 V4"
            stroke="currentColor" strokeWidth="1.2" fill="none" />
      <path d="M2.5 8 V12 C2.5 13.1 4.96 14 8 14 C11.04 14 13.5 13.1 13.5 12 V8"
            stroke="currentColor" strokeWidth="1.2" fill="none" />
    </svg>
  );
}

// Distance → background intensity (closer = stronger brand tint).
function distanceStyle(distance) {
  // ChromaDB default (l2) distances can be > 1. Clamp to [0, 2] and map.
  const clamped = Math.max(0, Math.min(distance, 2));
  const strength = 1 - clamped / 2;
  // mild coral tint for top hits, fading to plain surface
  const alpha = (strength * 0.14).toFixed(3);
  return {
    background: `rgba(217, 119, 87, ${alpha})`,
  };
}

export default function WorkflowVectorDbView({ workflowName, schema, onRefresh }) {
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [nResults, setNResults] = useState(10);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);

  const collections = schema?.collections || [];

  // Reset state when workflow changes
  useEffect(() => {
    setSelected(null);
    setQuery('');
    setResult(null);
    setError(null);
  }, [workflowName]);

  // Default-select the first collection when available
  useEffect(() => {
    if (!selected && collections.length > 0) {
      setSelected(collections[0].name);
    }
    if (selected && !collections.find(c => c.name === selected)) {
      setSelected(collections[0]?.name || null);
    }
  }, [collections, selected]);

  const runQuery = useCallback(async () => {
    if (!query.trim() || !selected) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(`/api/workflows/${workflowName}/vectordb/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          collection: selected,
          query,
          n_results: nResults,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.error || `HTTP ${r.status}`);
      } else {
        setResult(data);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }, [query, selected, nResults, workflowName]);

  const onQueryKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      runQuery();
    }
  }, [runQuery]);

  return (
    <div style={{
      display: 'flex', width: '100%', height: '100%',
      background: '#faf9f5',
      fontFamily: 'var(--font-ui)',
    }}>

      {/* ── Collections list ── */}
      <aside style={{
        width: 260, flexShrink: 0,
        background: '#ffffff',
        borderRight: '0.8px solid rgba(31,30,29,0.1)',
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto',
      }}>
        <div style={{
          padding: '10px 14px',
          fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
          color: '#73726c',
          borderBottom: '0.8px solid rgba(31,30,29,0.08)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>Collections ({collections.length})</span>
          <button
            onClick={onRefresh}
            title="Refresh collections"
            style={{
              ...btnGhost, height: 22, width: 22, padding: 0,
              fontSize: 12, borderRadius: 6,
            }}
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <path d="M13.5 3.5 A6 6 0 1 0 14 8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
              <path d="M13.5 1.5 L13.5 3.5 L11.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </button>
        </div>
        {collections.length === 0 ? (
          <div style={{ padding: '14px', fontSize: 12, color: '#73726c', lineHeight: 1.5 }}>
            No collections yet. Add a <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>VectorDB</code> node
            to the workflow with your collection names, then run the workflow to provision it.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {collections.map(c => {
              const isSelected = selected === c.name;
              return (
                <div
                  key={c.name}
                  onClick={() => setSelected(c.name)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '6px 14px',
                    fontSize: 13,
                    color: isSelected ? '#141413' : '#3d3d3a',
                    background: isSelected ? '#f0eee6' : 'transparent',
                    borderLeft: `2px solid ${isSelected ? '#d97757' : 'transparent'}`,
                    cursor: 'pointer', userSelect: 'none',
                  }}
                  onMouseEnter={e => {
                    if (!isSelected) e.currentTarget.style.background = '#f5f4ed';
                  }}
                  onMouseLeave={e => {
                    if (!isSelected) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <CollectionIcon />
                  <span style={{
                    flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {c.name}
                  </span>
                  <span style={{ fontSize: 11, color: '#9c9a92' }}>
                    {c.count == null ? '—' : c.count}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </aside>

      {/* ── Search + Results ── */}
      <section style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>

        {/* Search bar */}
        <div style={{
          display: 'flex', flexDirection: 'column',
          borderBottom: '0.8px solid rgba(31,30,29,0.1)',
          background: '#ffffff',
          flexShrink: 0,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 14px',
            borderBottom: '0.8px solid rgba(31,30,29,0.06)',
          }}>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
              color: '#73726c', flex: 1,
            }}>
              Search{selected ? ` · ${selected}` : ''}
            </span>
            <label style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 11, color: '#73726c',
            }}>
              Top
              <input
                type="number"
                min={1}
                max={100}
                value={nResults}
                onChange={e => setNResults(Math.max(1, Math.min(100, parseInt(e.target.value) || 10)))}
                style={{
                  width: 48, height: 24, padding: '0 6px',
                  borderRadius: 5, border: '0.8px solid rgba(31,30,29,0.15)',
                  background: '#ffffff', color: '#141413',
                  fontFamily: 'var(--font-mono)', fontSize: 12,
                  outline: 'none', textAlign: 'center',
                }}
              />
            </label>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '10px 14px',
          }}>
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={onQueryKeyDown}
              placeholder={selected ? `Semantic search in "${selected}"…` : 'Select a collection first'}
              disabled={!selected}
              spellCheck={false}
              style={{
                flex: 1, height: 34,
                padding: '0 12px',
                borderRadius: 8,
                border: '0.8px solid rgba(31,30,29,0.15)',
                background: '#ffffff',
                color: '#141413',
                fontSize: 13, fontFamily: 'var(--font-ui)',
                outline: 'none',
              }}
              onFocus={e => e.currentTarget.style.outline = '2px solid #2c84db'}
              onBlur={e => e.currentTarget.style.outline = 'none'}
            />
            <button
              onClick={runQuery}
              disabled={running || !query.trim() || !selected}
              style={{
                ...btnPrimary,
                height: 34,
                opacity: running || !query.trim() || !selected ? 0.5 : 1,
                cursor: running || !query.trim() || !selected ? 'default' : 'pointer',
              }}
            >
              {running ? 'Searching…' : 'Search'}
            </button>
          </div>
        </div>

        {/* Results */}
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          overflow: 'hidden', minHeight: 0,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 14px',
            borderBottom: '0.8px solid rgba(31,30,29,0.08)',
            background: '#f5f4ed',
            flexShrink: 0,
          }}>
            <span style={{
              fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
              color: '#73726c', flex: 1,
            }}>
              Results
            </span>
            {result && (
              <span style={{ fontSize: 11, color: '#73726c' }}>
                {result.hits.length} hit{result.hits.length === 1 ? '' : 's'}
                {' · '}{result.duration_ms} ms
              </span>
            )}
          </div>

          <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
            {error && (
              <div style={{
                margin: 14, padding: '10px 12px',
                background: '#ffe8e8', color: '#8c1e1e',
                border: '0.8px solid rgba(140,30,30,0.25)',
                borderRadius: 7, fontSize: 13, lineHeight: 1.5,
                fontFamily: 'var(--font-mono)',
                whiteSpace: 'pre-wrap',
              }}>
                {error}
              </div>
            )}
            {!error && result && result.hits.length > 0 && (
              <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {result.hits.map((hit, i) => (
                  <div
                    key={`${hit.id}-${i}`}
                    style={{
                      display: 'flex', flexDirection: 'column', gap: 6,
                      padding: '10px 12px',
                      borderRadius: 8,
                      border: '0.8px solid rgba(31,30,29,0.08)',
                      ...distanceStyle(hit.distance),
                      minWidth: 0,
                    }}
                  >
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      fontSize: 11, color: '#73726c',
                      minWidth: 0,
                    }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 20, height: 20, borderRadius: 5,
                        background: '#141413', color: '#ffffff',
                        fontSize: 11, fontWeight: 600, flexShrink: 0,
                      }}>
                        {i + 1}
                      </span>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 11,
                        color: '#3d3d3a',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        minWidth: 0, flex: 1,
                      }}>
                        id: {hit.id}
                      </span>
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontSize: 11,
                        color: '#c6613f', fontWeight: 600,
                        flexShrink: 0,
                      }}>
                        dist {Number(hit.distance).toFixed(4)}
                      </span>
                    </div>
                    <div style={{
                      fontSize: 13, color: '#141413', lineHeight: 1.5,
                      fontFamily: 'var(--font-ui)',
                      display: '-webkit-box',
                      WebkitLineClamp: 4,
                      WebkitBoxOrient: 'vertical',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      wordBreak: 'break-word',
                    }}>
                      {hit.document == null || hit.document === ''
                        ? <span style={{ color: '#9c9a92', fontStyle: 'italic' }}>(no document)</span>
                        : hit.document}
                    </div>
                    {hit.metadata && Object.keys(hit.metadata).length > 0 && (
                      <div style={{
                        display: 'flex', flexWrap: 'wrap', gap: 4,
                        marginTop: 2,
                      }}>
                        {Object.entries(hit.metadata).map(([k, v]) => (
                          <span
                            key={k}
                            style={{
                              fontSize: 11, fontFamily: 'var(--font-mono)',
                              padding: '2px 6px', borderRadius: 4,
                              background: 'rgba(255,255,255,0.7)',
                              color: '#3d3d3a',
                              border: '0.4px solid rgba(31,30,29,0.08)',
                              maxWidth: 280,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={`${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`}
                          >
                            {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!error && result && result.hits.length === 0 && (
              <div style={{ padding: 14, fontSize: 13, color: '#73726c' }}>
                No results for <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{result.query}</code> in <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{result.collection}</code>.
              </div>
            )}
            {!error && !result && (
              <div style={{ padding: 14, fontSize: 13, color: '#9c9a92' }}>
                {collections.length === 0
                  ? 'Provision a collection by adding and running a VectorDB node.'
                  : 'Type a query above and hit Enter to search.'}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
