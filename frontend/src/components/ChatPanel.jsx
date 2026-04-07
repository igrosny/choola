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

import { useState, useRef, useEffect } from 'react';

export default function ChatPanel({ workflowName, onNodesChanged }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    setMessages([]);
  }, [workflowName]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading || !workflowName) return;

    const userMsg = { role: 'user', content: text };
    const allMessages = [...messages, userMsg];
    setMessages(allMessages);
    setInput('');
    setLoading(true);

    const assistantIdx = allMessages.length;
    setMessages(prev => [...prev, { role: 'assistant', content: '', toolCalls: [], loading: true }]);

    try {
      const res = await fetch(`/api/workflows/${workflowName}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: allMessages.map(m => ({ role: m.role, content: m.content })),
        }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let didChangeNodes = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          if (event.type === 'text') {
            setMessages(prev => {
              const updated = [...prev];
              const msg = { ...updated[assistantIdx] };
              msg.content = (msg.content || '') + event.content;
              updated[assistantIdx] = msg;
              return updated;
            });
          } else if (event.type === 'tool_call') {
            setMessages(prev => {
              const updated = [...prev];
              const msg = { ...updated[assistantIdx] };
              msg.toolCalls = [...(msg.toolCalls || []), { tool: event.tool, input: event.input, status: 'running' }];
              updated[assistantIdx] = msg;
              return updated;
            });
          } else if (event.type === 'tool_result') {
            didChangeNodes = true;
            setMessages(prev => {
              const updated = [...prev];
              const msg = { ...updated[assistantIdx] };
              const calls = [...(msg.toolCalls || [])];
              const lastIdx = calls.findLastIndex(c => c.tool === event.tool && c.status === 'running');
              if (lastIdx >= 0) {
                calls[lastIdx] = { ...calls[lastIdx], result: event.result, status: 'done' };
              }
              msg.toolCalls = calls;
              updated[assistantIdx] = msg;
              return updated;
            });
          } else if (event.type === 'done') {
            setMessages(prev => {
              const updated = [...prev];
              updated[assistantIdx] = { ...updated[assistantIdx], loading: false };
              return updated;
            });
          } else if (event.type === 'error') {
            setMessages(prev => {
              const updated = [...prev];
              updated[assistantIdx] = { ...updated[assistantIdx], content: event.message, loading: false, error: true };
              return updated;
            });
          }
        }
      }

      if (didChangeNodes && onNodesChanged) {
        onNodesChanged();
      }
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev];
        updated[assistantIdx] = { role: 'assistant', content: `Error: ${err.message}`, loading: false, error: true };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const toolLabel = (name) => {
    switch (name) {
      case 'create_node': return 'Creating node';
      case 'edit_node': return 'Editing node';
      case 'add_node_to_topology': return 'Adding to canvas';
      default: return name;
    }
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#ffffff',
      borderLeft: '0.8px solid rgba(31,30,29,0.1)',
      fontFamily: 'var(--font-ui)',
    }}>
      {/* Header */}
      <div style={{
        padding: '13px 16px',
        borderBottom: '0.8px solid rgba(31,30,29,0.1)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: '#3d3d3a' }}>✦</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#141413' }}>AI chat</span>
        <span style={{ fontSize: 12, color: '#73726c', marginLeft: 2 }}>· {workflowName}</span>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '12px 14px',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}>
        {messages.length === 0 && (
          <div style={{
            color: '#73726c', fontSize: 13, textAlign: 'center',
            marginTop: 40, lineHeight: 1.6,
          }}>
            Ask me to create or edit nodes for this workflow.
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{
            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
            maxWidth: '88%',
            display: 'flex', flexDirection: 'column', gap: 6,
          }}>
            {msg.content && (
              <div style={{
                background: msg.role === 'user' ? '#141413' : msg.error ? '#ffe8e8' : '#f5f4ed',
                color: msg.role === 'user' ? '#ffffff' : msg.error ? '#b33232' : '#141413',
                padding: '9px 12px',
                borderRadius: msg.role === 'user' ? '12px 12px 3px 12px' : '12px 12px 12px 3px',
                fontSize: 13, lineHeight: 1.55,
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                border: msg.role !== 'user' ? '0.8px solid rgba(31,30,29,0.1)' : 'none',
              }}>
                {msg.content}
              </div>
            )}

            {msg.toolCalls?.map((tc, j) => (
              <div key={j} style={{
                padding: '7px 10px', borderRadius: 8,
                background: '#faf9f5',
                border: '0.8px solid rgba(31,30,29,0.1)',
                fontSize: 12,
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  color: tc.status === 'done' ? '#2f7613' : '#875a08',
                  fontWeight: 500,
                }}>
                  <span style={{ fontSize: 11 }}>{tc.status === 'done' ? '✓' : '○'}</span>
                  {toolLabel(tc.tool)}
                  {tc.input?.filename && <span style={{ color: '#73726c', fontWeight: 400 }}>· {tc.input.filename}</span>}
                  {tc.input?.label && <span style={{ color: '#73726c', fontWeight: 400 }}>· {tc.input.label}</span>}
                </div>
                {tc.result?.error && (
                  <div style={{ color: '#b33232', fontSize: 11, marginTop: 3 }}>{tc.result.error}</div>
                )}
              </div>
            ))}

            {msg.loading && !msg.content && (!msg.toolCalls || msg.toolCalls.length === 0) && (
              <div style={{
                background: '#f5f4ed', padding: '9px 12px', borderRadius: '12px 12px 12px 3px',
                color: '#73726c', fontSize: 13,
                border: '0.8px solid rgba(31,30,29,0.1)',
              }}>
                Thinking…
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{
        padding: '10px 12px',
        borderTop: '0.8px solid rgba(31,30,29,0.1)',
        display: 'flex', gap: 8, alignItems: 'flex-end',
      }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={workflowName ? 'Describe a node to create or edit…' : 'Select a workflow first'}
          disabled={!workflowName || loading}
          rows={2}
          style={{
            flex: 1, padding: '8px 10px', borderRadius: 8,
            border: '0.8px solid rgba(31,30,29,0.15)',
            background: '#ffffff', color: '#141413',
            fontFamily: 'var(--font-ui)', fontSize: 13,
            resize: 'none', outline: 'none',
            transition: 'border-color 0.15s ease',
            lineHeight: 1.5,
          }}
          onFocus={e => (e.target.style.borderColor = '#2c84db')}
          onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || loading || !workflowName}
          style={{
            height: 36, padding: '0 14px',
            borderRadius: 8, border: 'none',
            background: input.trim() && !loading && workflowName ? '#141413' : '#e8e6dc',
            color: input.trim() && !loading && workflowName ? '#ffffff' : '#73726c',
            cursor: input.trim() && !loading && workflowName ? 'pointer' : 'default',
            fontWeight: 500, fontSize: 13,
            fontFamily: 'var(--font-ui)',
            transition: 'all 0.15s ease',
            flexShrink: 0,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
