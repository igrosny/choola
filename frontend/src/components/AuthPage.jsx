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

import { useState } from 'react';

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

export default function AuthPage({ onAuth }) {
  const [tab, setTab] = useState('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('Please fill in all fields.');
      return;
    }

    const users = JSON.parse(localStorage.getItem('choola_users') || '{}');

    if (tab === 'signup') {
      if (password !== confirmPassword) {
        setError('Passwords do not match.');
        return;
      }
      if (password.length < 6) {
        setError('Password must be at least 6 characters.');
        return;
      }
      if (users[email]) {
        setError('An account with this email already exists.');
        return;
      }
      users[email] = { password };
      localStorage.setItem('choola_users', JSON.stringify(users));
    } else {
      if (!users[email] || users[email].password !== password) {
        setError('Invalid email or password.');
        return;
      }
    }

    const session = { email };
    localStorage.setItem('choola_session', JSON.stringify(session));
    onAuth(session);
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'hsl(var(--bg-100))',
      backgroundImage: `
        linear-gradient(to right, hsl(var(--bg-200)) 1px, transparent 1px),
        linear-gradient(to bottom, hsl(var(--bg-200)) 1px, transparent 1px)
      `,
      backgroundSize: '32px 32px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      <div style={{
        background: '#ffffff',
        borderRadius: 16,
        padding: '40px 40px 36px',
        width: '100%',
        maxWidth: 400,
        border: '0.8px solid rgba(31,30,29,0.1)',
        boxShadow: 'rgba(0,0,0,0.06) 0px 4px 32px, rgba(0,0,0,0.03) 0px 1px 4px',
      }}>

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 32 }}>
          <div style={{
            width: 34, height: 34,
            background: 'hsl(var(--accent-brand))',
            borderRadius: 9,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 15, fontWeight: 700,
            flexShrink: 0,
          }}>◆</div>
          <span style={{ fontSize: 18, fontWeight: 600, color: '#141413', letterSpacing: '-0.01em' }}>Choola</span>
        </div>

        {/* Heading */}
        <h1 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 500, color: '#141413', letterSpacing: '-0.01em' }}>
          {tab === 'signin' ? 'Welcome back' : 'Create your account'}
        </h1>
        <p style={{ margin: '0 0 24px', fontSize: 14, color: '#73726c' }}>
          {tab === 'signin' ? 'Sign in to your workspace.' : 'Get started with Choola for free.'}
        </p>

        {/* Tab switcher */}
        <div style={{
          display: 'flex',
          background: '#f5f4ed',
          borderRadius: 10,
          padding: 4,
          marginBottom: 24,
          gap: 3,
        }}>
          {['signin', 'signup'].map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setError(''); }}
              style={{
                flex: 1,
                padding: '7px 0',
                borderRadius: 7,
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'var(--font-ui)',
                background: tab === t ? '#ffffff' : 'transparent',
                color: tab === t ? '#141413' : '#73726c',
                boxShadow: tab === t ? 'rgba(0,0,0,0.06) 0px 1px 4px, rgba(0,0,0,0.02) 0px 0px 0px 0.5px' : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              {t === 'signin' ? 'Sign in' : 'Sign up'}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: '#3d3d3a' }}>Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={inputStyle}
              onFocus={e => (e.target.style.borderColor = '#2c84db')}
              onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label style={{ fontSize: 13, fontWeight: 500, color: '#3d3d3a' }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              style={inputStyle}
              onFocus={e => (e.target.style.borderColor = '#2c84db')}
              onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
            />
          </div>

          {tab === 'signup' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <label style={{ fontSize: 13, fontWeight: 500, color: '#3d3d3a' }}>Confirm password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                style={inputStyle}
                onFocus={e => (e.target.style.borderColor = '#2c84db')}
                onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
              />
            </div>
          )}

          {error && (
            <div style={{
              padding: '10px 13px',
              borderRadius: 8,
              background: 'hsl(var(--danger-900))',
              border: '0.8px solid rgba(179,50,50,0.2)',
              color: '#b33232',
              fontSize: 13,
              lineHeight: 1.4,
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            style={{
              height: 44,
              borderRadius: 10,
              border: 'none',
              background: '#141413',
              color: '#ffffff',
              fontSize: 14,
              fontWeight: 500,
              fontFamily: 'var(--font-ui)',
              cursor: 'pointer',
              marginTop: 4,
              transition: 'opacity 0.15s ease, transform 0.15s ease',
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.88')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            {tab === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <p style={{ margin: '20px 0 0', fontSize: 12, color: '#73726c', textAlign: 'center' }}>
          {tab === 'signin' ? (
            <>No account?{' '}
              <button onClick={() => { setTab('signup'); setError(''); }} style={{ background: 'none', border: 'none', color: '#2c84db', cursor: 'pointer', fontSize: 12, padding: 0, fontFamily: 'var(--font-ui)' }}>
                Sign up
              </button>
            </>
          ) : (
            <>Already have an account?{' '}
              <button onClick={() => { setTab('signin'); setError(''); }} style={{ background: 'none', border: 'none', color: '#2c84db', cursor: 'pointer', fontSize: 12, padding: 0, fontFamily: 'var(--font-ui)' }}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
