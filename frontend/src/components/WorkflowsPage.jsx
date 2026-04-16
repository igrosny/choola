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

import { useState, useEffect } from 'react';

// ── Shared button styles ──────────────────────────────────
const btnPrimary = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  height: 36,
  padding: '0 16px',
  borderRadius: 8,
  border: 'none',
  background: '#141413',
  color: '#ffffff',
  fontSize: 13,
  fontWeight: 500,
  fontFamily: 'var(--font-ui)',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  transition: 'opacity 0.15s ease',
};

const btnGhost = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  height: 36,
  padding: '0 12px',
  borderRadius: 8,
  border: '0.4px solid rgba(31,30,29,0.25)',
  background: 'transparent',
  color: '#3d3d3a',
  fontSize: 13,
  fontWeight: 500,
  fontFamily: 'var(--font-ui)',
  cursor: 'pointer',
  transition: 'background-color 0.15s ease',
};

const inputStyle = {
  display: 'block',
  width: '100%',
  height: 44,
  padding: '0 12px',
  borderRadius: '9.6px',
  border: '0.8px solid rgba(31,30,29,0.15)',
  background: '#ffffff',
  color: '#141413',
  fontSize: 14,
  fontFamily: 'var(--font-ui)',
  outline: 'none',
  transition: 'border-color 0.15s ease',
};

// ── StatusBadge ───────────────────────────────────────────
function StatusBadge({ status }) {
  const published = status === 'published';
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      height: 22,
      padding: '0 8px',
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '0.02em',
      background: published ? '#e7f1da' : '#f8eedd',
      color: published ? '#2f7613' : '#875a08',
      border: `0.8px solid ${published ? 'rgba(47,118,19,0.2)' : 'rgba(135,90,8,0.2)'}`,
    }}>
      {published ? 'Published' : 'Draft'}
    </span>
  );
}

// ── CreateWorkflowModal ───────────────────────────────────
function CreateWorkflowModal({ onClose, onCreate }) {
  const [name, setName] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('Please enter a workflow name.'); return; }
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
      setError('Only letters, numbers, underscores, and hyphens are allowed.');
      return;
    }
    const res = await fetch('/api/workflows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    });
    const result = await res.json();
    if (!res.ok) { setError(result.error || 'Failed to create workflow.'); return; }
    onCreate(name.trim());
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(20,20,19,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 100, padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#ffffff', borderRadius: 14, padding: '32px 32px 28px',
          width: '100%', maxWidth: 420,
          border: '0.8px solid rgba(31,30,29,0.1)',
          boxShadow: 'rgba(0,0,0,0.1) 0px 8px 32px',
        }}
      >
        <h2 style={{ margin: '0 0 6px', fontSize: 18, fontWeight: 600, color: '#141413' }}>New workflow</h2>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: '#73726c' }}>
          Give your workflow a unique name using letters, numbers, underscores or hyphens.
        </p>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: '#3d3d3a' }}>Workflow name</label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. email_processor"
              style={inputStyle}
              onFocus={e => (e.target.style.borderColor = '#2c84db')}
              onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
            />
          </div>
          {error && (
            <div style={{
              padding: '9px 12px', borderRadius: 8,
              background: 'hsl(var(--danger-900))',
              color: '#b33232', fontSize: 13,
              border: '0.8px solid rgba(179,50,50,0.2)',
            }}>
              {error}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
            <button type="button" onClick={onClose} style={btnGhost}>Cancel</button>
            <button type="submit" style={btnPrimary}>Create workflow</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── CredentialsModal ──────────────────────────────────────
function CredentialsModal({ onClose }) {
  const [credentials, setCredentials] = useState([]);
  const [credForm, setCredForm] = useState({ name: '', provider: 'claude', value: '' });

  const refresh = () =>
    fetch('/api/credentials').then(r => r.json()).then(setCredentials);

  useEffect(() => { refresh(); }, []);

  const handleSave = async () => {
    if (credForm.provider === 'google_oauth2' || credForm.provider === 'gmail') {
      if (!credForm.name || !credForm.client_id || !credForm.client_secret) {
        alert('Name, Client ID, and Client Secret are required'); return;
      }
      const endpoint = credForm.provider === 'gmail' ? '/api/oauth2/gmail/start' : '/api/oauth2/google/start';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: credForm.name, client_id: credForm.client_id, client_secret: credForm.client_secret }),
      });
      if (!res.ok) { const d = await res.json(); alert(d.error || 'Failed'); return; }
      const { auth_url } = await res.json();
      const popup = window.open(auth_url, credForm.provider + '_oauth2', 'width=500,height=600');
      const onMessage = (e) => {
        if (e.data === 'oauth2_done') {
          window.removeEventListener('message', onMessage);
          setCredForm({ name: '', provider: 'claude', value: '' });
          refresh();
        }
      };
      window.addEventListener('message', onMessage);
      return;
    }
    if (!credForm.name || !credForm.value) { alert('Name and API key are required'); return; }
    const res = await fetch('/api/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credForm),
    });
    if (!res.ok) { const d = await res.json(); alert(d.error || 'Failed'); return; }
    setCredForm({ name: '', provider: 'claude', value: '' });
    refresh();
  };

  const handleDelete = async (name) => {
    if (!confirm(`Delete credential "${name}"?`)) return;
    await fetch(`/api/credentials/${name}`, { method: 'DELETE' });
    refresh();
  };

  const providerColor = (p) => {
    if (p === 'claude') return { bg: 'rgba(217,119,87,0.1)', color: '#c6613f', border: 'rgba(217,119,87,0.25)' };
    if (p === 'google' || p === 'google_oauth2') return { bg: 'rgba(44,132,219,0.1)', color: '#1b67b2', border: 'rgba(44,132,219,0.25)' };
    if (p === 'gmail') return { bg: 'rgba(234,67,53,0.1)', color: '#c5221f', border: 'rgba(234,67,53,0.25)' };
    return { bg: '#f5f4ed', color: '#3d3d3a', border: 'rgba(31,30,29,0.15)' };
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(20,20,19,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 100, padding: 24,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#ffffff', borderRadius: 14, padding: '28px',
          width: '100%', maxWidth: 520, maxHeight: '80vh',
          display: 'flex', flexDirection: 'column', gap: 20,
          border: '0.8px solid rgba(31,30,29,0.1)',
          boxShadow: 'rgba(0,0,0,0.1) 0px 8px 32px',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 600, color: '#141413' }}>Credentials</h2>
            <p style={{ margin: 0, fontSize: 13, color: '#73726c' }}>
              Store API keys for LLM providers. Reference them by name in nodes.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 18, lineHeight: 1, padding: 4 }}
          >✕</button>
        </div>

        {/* Existing credentials */}
        {credentials.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Saved</div>
            {credentials.map(c => {
              const pc = providerColor(c.provider);
              return (
                <div key={c.name} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  background: '#faf9f5', padding: '10px 14px', borderRadius: 9,
                  border: '0.8px solid rgba(31,30,29,0.1)',
                }}>
                  <span style={{ fontWeight: 600, fontSize: 13, color: '#141413', flex: 1, fontFamily: 'var(--font-mono)' }}>{c.name}</span>
                  <span style={{
                    fontSize: 11, padding: '2px 7px', borderRadius: 5, fontWeight: 500,
                    background: pc.bg, color: pc.color, border: `0.8px solid ${pc.border}`,
                  }}>{c.provider}</span>
                  <button
                    onClick={() => handleDelete(c.name)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 14, padding: '2px 4px', lineHeight: 1 }}
                    title="Delete credential"
                  >✕</button>
                </div>
              );
            })}
          </div>
        )}

        {/* Add form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, background: '#faf9f5', padding: 16, borderRadius: 10, border: '0.8px solid rgba(31,30,29,0.1)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Add credential</div>
          <input
            placeholder="Name (e.g. my-claude-key)"
            value={credForm.name}
            onChange={e => setCredForm(p => ({ ...p, name: e.target.value }))}
            style={{ ...inputStyle, height: 38, fontSize: 13 }}
          />
          <select
            value={credForm.provider}
            onChange={e => setCredForm(p => ({ ...p, provider: e.target.value }))}
            style={{ ...inputStyle, height: 38, fontSize: 13 }}
          >
            <option value="claude">Claude</option>
            <option value="gemini">Gemini</option>
            <option value="google">Google API Key</option>
            <option value="google_oauth2">Google OAuth2</option>
            <option value="gmail">Gmail</option>
          </select>
          {(credForm.provider === 'google_oauth2' || credForm.provider === 'gmail') ? (
            <>
              <input
                placeholder="Client ID"
                value={credForm.client_id || ''}
                onChange={e => setCredForm(p => ({ ...p, client_id: e.target.value }))}
                style={{ ...inputStyle, height: 38, fontSize: 13 }}
              />
              <input
                type="password"
                placeholder="Client Secret"
                value={credForm.client_secret || ''}
                onChange={e => setCredForm(p => ({ ...p, client_secret: e.target.value }))}
                style={{ ...inputStyle, height: 38, fontSize: 13 }}
              />
            </>
          ) : (
            <input
              type="password"
              placeholder="API key"
              value={credForm.value}
              onChange={e => setCredForm(p => ({ ...p, value: e.target.value }))}
              style={{ ...inputStyle, height: 38, fontSize: 13 }}
            />
          )}
          <button
            onClick={handleSave}
            style={{ ...btnPrimary, width: '100%', justifyContent: 'center', height: 38 }}
          >
            {credForm.provider === 'google_oauth2' ? 'Connect with Google' : credForm.provider === 'gmail' ? 'Connect with Gmail' : 'Save credential'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── WorkflowsPage ─────────────────────────────────────────
export default function WorkflowsPage({ user, onOpenWorkflow, onSignOut }) {
  const [workflows, setWorkflows] = useState([]);
  const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [activeNav, setActiveNav] = useState('workflows');

  const refresh = () =>
    fetch('/api/workflows').then(r => r.json()).then(setWorkflows);

  useEffect(() => { refresh(); }, []);

  const filtered = workflows.filter(w =>
    w.name.toLowerCase().includes(search.toLowerCase())
  );

  const initials = user.email
    ? user.email.slice(0, 2).toUpperCase()
    : '??';

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#faf9f5', fontFamily: 'var(--font-ui)' }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: 240,
        background: '#ffffff',
        borderRight: '0.8px solid rgba(31,30,29,0.1)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
        padding: '20px 12px',
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 8px', marginBottom: 28 }}>
          <div style={{
            width: 28, height: 28,
            background: 'hsl(var(--accent-brand))',
            borderRadius: 7,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 12, fontWeight: 700, flexShrink: 0,
          }}>◆</div>
          <span style={{ fontSize: 15, fontWeight: 600, color: '#141413', letterSpacing: '-0.01em' }}>Choola</span>
        </div>

        {/* Nav */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
          {[
            { id: 'workflows', label: 'Workflows', icon: '⬡' },
            { id: 'settings', label: 'Settings', icon: '⚙' },
          ].map(item => (
            <button
              key={item.id}
              onClick={() => {
                setActiveNav(item.id);
                if (item.id === 'settings') setShowSettings(true);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 9,
                padding: '8px 10px',
                borderRadius: 7,
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: activeNav === item.id ? 500 : 430,
                fontFamily: 'var(--font-ui)',
                background: activeNav === item.id ? '#f0eee6' : 'transparent',
                color: activeNav === item.id ? '#141413' : '#3d3d3a',
                textAlign: 'left',
                transition: 'background-color 0.15s ease',
              }}
              onMouseEnter={e => { if (activeNav !== item.id) e.currentTarget.style.background = '#f5f4ed'; }}
              onMouseLeave={e => { if (activeNav !== item.id) e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ fontSize: 14, opacity: 0.7 }}>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        {/* User */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 9,
          padding: '10px 10px',
          borderTop: '0.8px solid rgba(31,30,29,0.08)',
          marginTop: 8,
        }}>
          <div style={{
            width: 30, height: 30,
            background: '#e8e6dc',
            borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 11, fontWeight: 600, color: '#3d3d3a',
            flexShrink: 0,
          }}>{initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: '#141413', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user.email}
            </div>
          </div>
          <button
            onClick={onSignOut}
            title="Sign out"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 13, padding: 3, lineHeight: 1 }}
          >↪</button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Page header */}
        <div style={{
          padding: '24px 32px 0',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexShrink: 0,
        }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: '#141413', letterSpacing: '-0.01em' }}>
            Workflows
          </h1>
          <button
            onClick={() => setShowCreate(true)}
            style={btnPrimary}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            <span style={{ fontSize: 16, lineHeight: 1, marginBottom: 1 }}>+</span>
            New workflow
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: '16px 32px 20px', flexShrink: 0 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 9,
            height: 38, padding: '0 12px',
            borderRadius: '9.6px',
            border: '0.8px solid rgba(31,30,29,0.15)',
            background: '#ffffff',
            maxWidth: 360,
          }}>
            <svg width="15" height="15" viewBox="0 0 20 20" fill="none">
              <circle cx="8.5" cy="8.5" r="5.75" stroke="#73726c" strokeWidth="1.5"/>
              <path d="M13.5 13.5L17 17" stroke="#73726c" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <input
              type="search"
              placeholder="Search workflows..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                flex: 1, border: 'none', outline: 'none',
                background: 'transparent', fontSize: 13, color: '#141413',
                fontFamily: 'var(--font-ui)',
              }}
            />
          </div>
        </div>

        {/* Cards */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '0 32px 32px' }}>
          {filtered.length === 0 ? (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              paddingTop: 80, gap: 12,
            }}>
              <div style={{ fontSize: 40, opacity: 0.3 }}>⬡</div>
              <div style={{ fontSize: 15, fontWeight: 500, color: '#3d3d3a' }}>
                {search ? 'No workflows match your search' : 'No workflows yet'}
              </div>
              {!search && (
                <button
                  onClick={() => setShowCreate(true)}
                  style={{ ...btnGhost, marginTop: 4 }}
                >
                  Create your first workflow
                </button>
              )}
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: 16,
            }}>
              {filtered.map(w => (
                <button
                  key={w.name}
                  onClick={() => onOpenWorkflow(w.name)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 10,
                    padding: '18px 18px 16px 20px',
                    borderRadius: 12,
                    border: '0.4px solid rgba(31,30,29,0.15)',
                    background: 'linear-gradient(to bottom, #faf9f5, rgba(250,249,245,0.4))',
                    cursor: 'pointer',
                    textAlign: 'left',
                    fontFamily: 'var(--font-ui)',
                    transition: 'all 0.15s cubic-bezier(0.4,0,0.2,1)',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'linear-gradient(to bottom, #ffffff, rgba(255,255,255,0.9))';
                    e.currentTarget.style.borderColor = 'rgba(31,30,29,0.22)';
                    e.currentTarget.style.boxShadow = 'rgba(0,0,0,0.06) 0px 2px 10px';
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'linear-gradient(to bottom, #faf9f5, rgba(250,249,245,0.4))';
                    e.currentTarget.style.borderColor = 'rgba(31,30,29,0.15)';
                    e.currentTarget.style.boxShadow = 'none';
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#141413', wordBreak: 'break-all', lineHeight: 1.3 }}>
                      {w.name}
                    </span>
                    <StatusBadge status={w.status} />
                  </div>
                  <div style={{ fontSize: 12, color: '#73726c' }}>
                    {w.nodes === 1 ? '1 node' : `${w.nodes || 0} nodes`}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </main>

      {showCreate && (
        <CreateWorkflowModal
          onClose={() => setShowCreate(false)}
          onCreate={(name) => {
            setShowCreate(false);
            refresh();
            onOpenWorkflow(name);
          }}
        />
      )}

      {showSettings && (
        <CredentialsModal onClose={() => { setShowSettings(false); setActiveNav('workflows'); }} />
      )}
    </div>
  );
}
