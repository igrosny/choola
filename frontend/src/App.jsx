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
import AuthPage from './components/AuthPage';
import WorkflowsPage from './components/WorkflowsPage';
import WorkflowEditor from './components/WorkflowEditor';
import GlobalTerminal from './components/GlobalTerminal';

export default function App() {
  const [user, setUser] = useState(() => {
    try {
      const raw = localStorage.getItem('choola_session');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const [activeWorkflow, setActiveWorkflow] = useState(null);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(260);

  const handleSignOut = () => {
    localStorage.removeItem('choola_session');
    setUser(null);
    setActiveWorkflow(null);
  };

  let page;
  if (!user) {
    page = <AuthPage onAuth={(u) => setUser(u)} />;
  } else if (activeWorkflow) {
    page = (
      <WorkflowEditor
        workflowName={activeWorkflow}
        onBack={() => setActiveWorkflow(null)}
        user={user}
        onSignOut={handleSignOut}
      />
    );
  } else {
    page = (
      <WorkflowsPage
        user={user}
        onOpenWorkflow={(name) => setActiveWorkflow(name)}
        onSignOut={handleSignOut}
      />
    );
  }

  return (
    <>
      {page}
      {user && (
        <>
          <GlobalTerminal
            open={terminalOpen}
            height={terminalHeight}
            onResize={setTerminalHeight}
            onClose={() => setTerminalOpen(false)}
          />
          {!terminalOpen && (
            <button
              onClick={() => setTerminalOpen(true)}
              title="Open terminal"
              style={{
                position: 'fixed', bottom: 16, right: 16,
                zIndex: 60,
                background: '#1f1e1d',
                color: '#e8e6dc',
                border: '0.8px solid rgba(255,255,255,0.12)',
                borderRadius: 6,
                padding: '6px 12px',
                fontFamily: 'var(--font-ui)',
                fontSize: 12,
                cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
                boxShadow: '0 4px 12px rgba(0,0,0,0.18)',
              }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, lineHeight: 1 }}>›_</span>
              Terminal
            </button>
          )}
        </>
      )}
    </>
  );
}
