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

function Caret({ open }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 10 10"
      style={{
        transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
        transition: 'transform 0.12s ease',
        flexShrink: 0,
      }}
    >
      <path d="M3 2 L7 5 L3 8 Z" fill="currentColor" />
    </svg>
  );
}

function TableIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <line x1="1.5" y1="6" x2="14.5" y2="6" stroke="currentColor" strokeWidth="1.2" />
      <line x1="1.5" y1="10" x2="14.5" y2="10" stroke="currentColor" strokeWidth="1.2" />
      <line x1="6" y1="6" x2="6" y2="13.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function ColumnDot({ isPk }) {
  return (
    <span
      style={{
        display: 'inline-block', width: 6, height: 6, borderRadius: 2,
        background: isPk ? '#d97757' : '#9c9a92',
        marginRight: 8, flexShrink: 0,
      }}
    />
  );
}

export default function WorkflowDbView({ workflowName, schema, onRefresh }) {
  const [expanded, setExpanded] = useState(() => new Set());
  const [sql, setSql] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);

  // Reset query state when workflow changes
  useEffect(() => {
    setSql('');
    setResult(null);
    setError(null);
    setExpanded(new Set());
  }, [workflowName]);

  const toggle = useCallback((tableName) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(tableName)) next.delete(tableName);
      else next.add(tableName);
      return next;
    });
  }, []);

  const runQuery = useCallback(async () => {
    if (!sql.trim()) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(`/api/workflows/${workflowName}/db/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.error || `HTTP ${r.status}`);
      } else {
        setResult(data);
        // Schema may have changed if the user ran DDL/DML
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }, [sql, workflowName, onRefresh]);

  const onSqlKeyDown = useCallback((e) => {
    // Cmd/Ctrl+Enter runs the query
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      runQuery();
    }
  }, [runQuery]);

  const tables = schema?.tables || [];

  const selectTable = useCallback((tableName) => {
    setSql(`SELECT * FROM "${tableName}" LIMIT 100;`);
  }, []);

  return (
    <div style={{
      display: 'flex', width: '100%', height: '100%',
      background: '#faf9f5',
      fontFamily: 'var(--font-ui)',
    }}>

      {/* ── Tables tree ── */}
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
          <span>Tables ({tables.length})</span>
          <button
            onClick={onRefresh}
            title="Refresh schema"
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
        {tables.length === 0 ? (
          <div style={{ padding: '14px', fontSize: 12, color: '#73726c', lineHeight: 1.5 }}>
            No tables yet. Add a <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>DB</code> node
            to the workflow with your schema, then run the workflow to provision it.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {tables.map(t => {
              const isOpen = expanded.has(t.name);
              return (
                <div key={t.name}>
                  <div
                    onClick={() => toggle(t.name)}
                    onDoubleClick={() => selectTable(t.name)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '5px 14px',
                      fontSize: 13, color: '#141413',
                      cursor: 'pointer', userSelect: 'none',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#f5f4ed')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                  >
                    <Caret open={isOpen} />
                    <TableIcon />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {t.name}
                    </span>
                    <span style={{ fontSize: 11, color: '#9c9a92' }}>{t.row_count}</span>
                  </div>
                  {isOpen && (
                    <div style={{ padding: '2px 0 6px 0' }}>
                      {t.columns.map(c => (
                        <div
                          key={c.name}
                          style={{
                            display: 'flex', alignItems: 'center',
                            padding: '3px 14px 3px 38px',
                            fontSize: 12, color: '#3d3d3a',
                          }}
                        >
                          <ColumnDot isPk={c.pk} />
                          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {c.name}
                          </span>
                          <span style={{
                            fontSize: 11, color: '#9c9a92', fontFamily: 'var(--font-mono)',
                            marginLeft: 8, whiteSpace: 'nowrap',
                          }}>
                            {c.type}{c.notnull ? ' NOT NULL' : ''}{c.pk ? ' PK' : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </aside>

      {/* ── Query + Results ── */}
      <section style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>

        {/* Query editor */}
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
              Query
            </span>
            <span style={{ fontSize: 11, color: '#9c9a92', fontFamily: 'var(--font-mono)' }}>
              ⌘/Ctrl + Enter
            </span>
            <button
              onClick={runQuery}
              disabled={running || !sql.trim()}
              style={{
                ...btnPrimary,
                opacity: running || !sql.trim() ? 0.5 : 1,
                cursor: running || !sql.trim() ? 'default' : 'pointer',
              }}
            >
              {running ? 'Running…' : 'Run'}
            </button>
          </div>
          <textarea
            value={sql}
            onChange={e => setSql(e.target.value)}
            onKeyDown={onSqlKeyDown}
            placeholder="SELECT * FROM users;"
            spellCheck={false}
            style={{
              width: '100%', height: 140,
              padding: '10px 14px',
              border: 'none',
              background: '#ffffff',
              color: '#141413',
              fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1.5,
              resize: 'vertical', outline: 'none',
              boxSizing: 'border-box',
            }}
          />
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
                {result.columns.length > 0
                  ? `${result.rowcount} row${result.rowcount === 1 ? '' : 's'}`
                  : `${result.rowcount} row${result.rowcount === 1 ? '' : 's'} affected`}
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
            {!error && result && result.columns.length > 0 && (
              <table style={{
                width: '100%', borderCollapse: 'collapse',
                fontSize: 12, fontFamily: 'var(--font-ui)',
              }}>
                <thead>
                  <tr>
                    {result.columns.map(c => (
                      <th key={c} style={{
                        position: 'sticky', top: 0, zIndex: 1,
                        textAlign: 'left', fontWeight: 600,
                        padding: '8px 12px',
                        background: '#f0eee6', color: '#141413',
                        borderBottom: '0.8px solid rgba(31,30,29,0.15)',
                        whiteSpace: 'nowrap',
                      }}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i} style={{
                      background: i % 2 === 0 ? '#ffffff' : '#faf9f5',
                    }}>
                      {row.map((v, j) => (
                        <td key={j} style={{
                          padding: '6px 12px',
                          borderBottom: '0.4px solid rgba(31,30,29,0.06)',
                          color: v === null ? '#9c9a92' : '#141413',
                          fontStyle: v === null ? 'italic' : 'normal',
                          fontFamily: typeof v === 'number' ? 'var(--font-mono)' : 'var(--font-ui)',
                          whiteSpace: 'nowrap',
                          maxWidth: 480,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}>
                          {v === null ? 'NULL' : typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {!error && result && result.columns.length === 0 && (
              <div style={{ padding: 14, fontSize: 13, color: '#2f7613' }}>
                OK — {result.rowcount} row{result.rowcount === 1 ? '' : 's'} affected ({result.duration_ms} ms)
              </div>
            )}
            {!error && !result && (
              <div style={{ padding: 14, fontSize: 13, color: '#9c9a92' }}>
                Run a query to see results. Double-click a table on the left to insert a SELECT.
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
