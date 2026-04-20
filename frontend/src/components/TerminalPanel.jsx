import { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export default function TerminalPanel({ visible, workflowName }) {
  const containerRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const wsRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

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
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const qs = workflowName ? `?workflow=${encodeURIComponent(workflowName)}` : '';
    const ws = new WebSocket(`${proto}//${window.location.host}/api/terminal${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'resize', rows: term.rows, cols: term.cols }));
    };
    ws.onmessage = (ev) => {
      term.write(ev.data);
    };
    ws.onclose = () => {
      term.write('\r\n\x1b[33m[terminal disconnected]\x1b[0m\r\n');
    };
    ws.onerror = () => {
      term.write('\r\n\x1b[31m[terminal error]\x1b[0m\r\n');
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }));
      }
    });

    term.onResize(({ rows, cols }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', rows, cols }));
      }
    });

    const ro = new ResizeObserver(() => {
      try { fit.fit(); } catch {}
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      try { ws.close(); } catch {}
      try { term.dispose(); } catch {}
    };
  }, [workflowName]);

  useEffect(() => {
    if (visible && fitRef.current) {
      requestAnimationFrame(() => {
        try { fitRef.current.fit(); } catch {}
      });
    }
  }, [visible]);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#1f1e1d',
    }}>
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
      </div>
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 0 }}
      />
    </div>
  );
}
