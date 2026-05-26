import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

const SESSION_KEY = 'choola_terminal_session';

export default function GlobalTerminal({ open, height, onResize, onClose }) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const wsRef = useRef(null);
  const connectedSessionRef = useRef('');
  const mountedRef = useRef(true);
  const reconnectTimerRef = useRef(null);

  // One-time xterm + WebSocket setup. The terminal and connection live for
  // the entire mounted lifetime of the component so output keeps streaming
  // while the panel is hidden, and pty state is unaffected by page navigation.
  useEffect(() => {
    if (!containerRef.current || termRef.current) return;

    const term = new Terminal({
      fontFamily: '"Anthropic Mono", ui-monospace, "Fira Code", "JetBrains Mono", Consolas, monospace',
      fontSize: 12,
      theme: {
        background: '#1f1e1d',
        foreground: '#e8e6dc',
        cursor: '#e8e6dc',
        selectionBackground: '#3d3d3a',
      },
      cursorBlink: true,
      convertEol: true,
      scrollback: 5000,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    termRef.current = term;
    fitRef.current = fit;

    const connect = () => {
      if (!mountedRef.current) return;
      const stored = localStorage.getItem(SESSION_KEY) || '';
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const qs = stored ? `?session_id=${encodeURIComponent(stored)}` : '';
      const ws = new WebSocket(`${proto}//${window.location.host}/api/terminal${qs}`);
      wsRef.current = ws;

      ws.onopen = () => {
        try { fit.fit(); } catch {}
        ws.send(JSON.stringify({ type: 'resize', rows: term.rows, cols: term.cols }));
      };
      ws.onmessage = (ev) => {
        let parsed;
        try { parsed = JSON.parse(ev.data); } catch { return; }
        if (parsed.type === 'session') {
          const incoming = parsed.id || '';
          if (!incoming) return;
          // Backend handed us a different session (server restart, expired,
          // unknown id) — clear the screen so old scrollback doesn't sit above
          // the new shell prompt.
          if (stored && incoming !== stored) {
            term.reset();
          }
          connectedSessionRef.current = incoming;
          localStorage.setItem(SESSION_KEY, incoming);
        } else if (parsed.type === 'output') {
          term.write(parsed.data || '');
        }
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (!mountedRef.current) return;
        reconnectTimerRef.current = setTimeout(() => {
          reconnectTimerRef.current = null;
          if (mountedRef.current && !wsRef.current) connect();
        }, 1500);
      };
      ws.onerror = () => {
        try { ws.close(); } catch {}
      };
    };

    term.onData((data) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    term.onResize(({ rows, cols }) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', rows, cols }));
      }
    });

    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch {}
    });
    ro.observe(containerRef.current);

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      try { ro.disconnect(); } catch {}
      try { wsRef.current?.close(); } catch {}
      try { termRef.current?.dispose(); } catch {}
      wsRef.current = null;
      termRef.current = null;
      fitRef.current = null;
    };
  }, []);

  // Re-fit when the panel becomes visible or is resized — xterm's FitAddon
  // measures the DOM, and a hidden (display:none) container reports zero size.
  useEffect(() => {
    if (open && fitRef.current) {
      requestAnimationFrame(() => {
        try { fitRef.current.fit(); } catch {}
      });
    }
  }, [open, height]);

  const onResizeMouseDown = (e) => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = height;
    const onMove = (ev) => {
      const next = Math.min(800, Math.max(120, startH + (startY - ev.clientY)));
      onResize(next);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.userSelect = '';
    };
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div style={{
      position: 'fixed', left: 0, right: 0, bottom: 0,
      height,
      display: open ? 'flex' : 'none',
      flexDirection: 'column',
      background: '#1f1e1d',
      boxShadow: '0 -8px 24px rgba(0,0,0,0.18)',
      zIndex: 50,
    }}>
      <div
        onMouseDown={onResizeMouseDown}
        style={{
          height: 5, flexShrink: 0,
          cursor: 'row-resize',
          background: 'rgba(255,255,255,0.06)',
        }}
      />
      <div style={{
        padding: '6px 12px',
        borderBottom: '0.8px solid rgba(255,255,255,0.08)',
        color: '#a8a69e',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        display: 'flex', alignItems: 'center', gap: 8,
        flexShrink: 0,
      }}>
        <span style={{ color: '#e8e6dc' }}>●</span>
        <span>terminal</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={onClose}
          title="Hide terminal"
          style={{
            background: 'transparent', border: 'none',
            color: '#a8a69e', cursor: 'pointer',
            fontSize: 16, lineHeight: 1, padding: '0 4px',
          }}
        >×</button>
      </div>
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 0 }}
      />
    </div>
  );
}
