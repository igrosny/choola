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

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Panel,
  getBezierPath,
  BaseEdge,
  EdgeLabelRenderer,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/themes/prism-tomorrow.css';
import ChatPanel from './ChatPanel';
import '../App.css';

// ── Status colors (light theme) ───────────────────────────
const STATUS_COLORS = {
  IDLE: 'rgba(31,30,29,0.2)',
  RUNNING: '#875a08',
  COMPLETED: '#2f7613',
  ERROR: '#b33232',
};

// ── Shared styles ─────────────────────────────────────────
const btnPrimary = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 6, height: 34, padding: '0 14px',
  borderRadius: 8, border: 'none',
  background: '#141413', color: '#ffffff',
  fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-ui)',
  cursor: 'pointer', whiteSpace: 'nowrap',
  transition: 'opacity 0.15s ease',
};

const btnGhost = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  gap: 6, height: 34, padding: '0 12px',
  borderRadius: 8, border: '0.4px solid rgba(31,30,29,0.22)',
  background: 'transparent', color: '#3d3d3a',
  fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-ui)',
  cursor: 'pointer', whiteSpace: 'nowrap',
  transition: 'background-color 0.15s ease',
};

const inputStyle = {
  display: 'block', width: '100%',
  height: 38, padding: '0 10px',
  borderRadius: 8, border: '0.8px solid rgba(31,30,29,0.15)',
  background: '#ffffff', color: '#141413',
  fontSize: 13, fontFamily: 'var(--font-ui)',
  outline: 'none', transition: 'border-color 0.15s ease',
};

// ── Deletable edge ────────────────────────────────────────
function DeletableEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd }) {
  const [hovered, setHovered] = useState(false);
  const { deleteElements } = useReactFlow();
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{ cursor: 'pointer' }}
      />
      {hovered && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'all',
            }}
            className="nodrag nopan"
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
          >
            <button
              onClick={() => deleteElements({ edges: [{ id }] })}
              style={{
                background: '#ffffff',
                border: '1px solid #b33232',
                borderRadius: '50%',
                width: 22, height: 22,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', color: '#b33232', padding: 0, lineHeight: 1,
                boxShadow: 'rgba(0,0,0,0.08) 0px 2px 6px',
              }}
              title="Delete edge"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6l-1 14H6L5 6" />
                <path d="M10 11v6M14 11v6" />
                <path d="M9 6V4h6v2" />
              </svg>
            </button>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const EDGE_TYPES = { deletable: DeletableEdge };

// ── Docstring helpers ─────────────────────────────────────
function parseChoolaDocstring(source) {
  const match = source.match(/^"""([\s\S]*?)"""/);
  if (!match) return null;
  const raw = match[1].trim();
  const sections = [];
  let current = null;
  for (const line of raw.split('\n')) {
    const tagMatch = line.match(/^@([\w-]+):\s*(.*)/);
    if (tagMatch) {
      if (current) sections.push(current);
      current = { tag: tagMatch[1], title: tagMatch[2].trim(), items: [] };
    } else if (current) {
      const trimmed = line.trim();
      if (trimmed.startsWith('- ')) {
        current.items.push(trimmed.slice(2));
      } else if (trimmed) {
        if (current.items.length > 0) {
          current.items[current.items.length - 1] += ' ' + trimmed;
        } else {
          current.title += ' ' + trimmed;
        }
      }
    }
  }
  if (current) sections.push(current);
  return sections;
}

function stripDocstring(source) {
  return source.replace(/^"""[\s\S]*?"""\n*/, '').trim();
}

function rebuildSource(sections, codeBody) {
  if (!sections || sections.length === 0) return codeBody;
  let doc = '"""\n';
  for (const s of sections) {
    doc += `@${s.tag}: ${s.title}\n`;
    for (const item of s.items) {
      doc += `  - ${item}\n`;
    }
  }
  doc += '"""\n\n';
  return doc + codeBody;
}

const TAG_LABELS = {
  'choola-node': 'Node Name',
  category: 'Category',
  description: 'Description',
  'input-payload': 'Input Payload',
  'output-payload': 'Output Payload',
  'config-fields': 'Config Fields',
  'example-input': 'Example Input',
  'example-output': 'Example Output',
  'side-effects': 'Side Effects',
  errors: 'Errors',
};

const TAG_ICONS = {
  'choola-node': '◆', category: '▦', description: '◇',
  'input-payload': '→', 'output-payload': '←', 'config-fields': '⚙',
  'example-input': '▸', 'example-output': '◂', 'side-effects': '⚡', errors: '⚠',
};

function DocPanel({ sections }) {
  if (!sections || sections.length === 0) {
    return <div style={{ color: '#73726c', fontStyle: 'italic', padding: 16, fontSize: 13 }}>No @choola-node docstring found.</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {sections.map((s, i) => (
        <div key={i}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            color: '#d97757', fontWeight: 600, fontSize: 11, textTransform: 'uppercase',
            letterSpacing: '0.06em', marginBottom: 5,
          }}>
            <span style={{ fontSize: 13, opacity: 0.8 }}>{TAG_ICONS[s.tag] || '•'}</span>
            {TAG_LABELS[s.tag] || s.tag}
          </div>
          {s.title && s.title !== 'none' && (
            <div style={{
              color: '#3d3d3a', fontSize: 13, paddingLeft: 18,
              fontFamily: s.tag.includes('example') ? 'var(--font-mono)' : 'inherit',
              background: s.tag.includes('example') ? '#f5f4ed' : 'transparent',
              borderRadius: 4,
              padding: s.tag.includes('example') ? '4px 8px 4px 18px' : '0 0 0 18px',
            }}>
              {s.title}
            </div>
          )}
          {s.items.length > 0 && (
            <div style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4, marginTop: 3 }}>
              {s.items.map((item, j) => {
                const paramMatch = item.match(/^(\w+)\s*\(([^)]+)\)(?::\s*(.*))?$/);
                if (paramMatch) {
                  return (
                    <div key={j} style={{ fontSize: 13, color: '#3d3d3a' }}>
                      <span style={{ color: '#1b67b2', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{paramMatch[1]}</span>
                      <span style={{ color: '#73726c', fontSize: 11, marginLeft: 4 }}>{paramMatch[2]}</span>
                      {paramMatch[3] && <span style={{ color: '#3d3d3a', marginLeft: 6 }}>{paramMatch[3]}</span>}
                    </div>
                  );
                }
                return (
                  <div key={j} style={{ fontSize: 13, color: '#3d3d3a' }}>
                    <span style={{ color: '#73726c', marginRight: 6 }}>•</span>{item}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── StatusBadge ───────────────────────────────────────────
function StatusBadge({ status }) {
  const published = status === 'published';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      height: 22, padding: '0 8px', borderRadius: 6,
      fontSize: 11, fontWeight: 600, letterSpacing: '0.02em',
      background: published ? '#e7f1da' : '#f8eedd',
      color: published ? '#2f7613' : '#875a08',
      border: `0.8px solid ${published ? 'rgba(47,118,19,0.2)' : 'rgba(135,90,8,0.2)'}`,
    }}>
      {published ? 'Published' : 'Draft'}
    </span>
  );
}

// ── Divider ───────────────────────────────────────────────
function Divider() {
  return <div style={{ height: '0.8px', background: 'rgba(31,30,29,0.08)', margin: '4px 0' }} />;
}

// ── SidebarSection ─────────────────────────────────────────
function SidebarSection({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 16px' }}>
      {label && (
        <div style={{ fontSize: 10, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          {label}
        </div>
      )}
      {children}
    </div>
  );
}

// ── WorkflowEditor ────────────────────────────────────────
export default function WorkflowEditor({ workflowName, onBack, user }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [nodeStatuses, setNodeStatuses] = useState({});
  const [nodePayloads, setNodePayloads] = useState({});
  const [logs, setLogs] = useState([]);
  const [running, setRunning] = useState(false);
  const [payloadInput, setPayloadInput] = useState('{"start": true}');
  const [codeModal, setCodeModal] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [workflowStatus, setWorkflowStatus] = useState('draft');
  const [triggerInfo, setTriggerInfo] = useState(null);
  const [waitingForTrigger, setWaitingForTrigger] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [credentials, setCredentials] = useState([]);
  const [credForm, setCredForm] = useState({ name: '', provider: 'claude', value: '' });
  const logsEndRef = useRef(null);

  const isPublished = workflowStatus === 'published';

  // Load topology & trigger info
  useEffect(() => {
    setWorkflowStatus('draft');
    setTriggerInfo(null);
    setNodes([]);
    setEdges([]);
    setNodeStatuses({});
    setLogs([]);

    fetch(`/api/workflows/${workflowName}/topology`)
      .then(r => r.json())
      .then(topo => {
        setWorkflowStatus(topo.status || 'draft');
        const flowNodes = (topo.nodes || []).map(n => ({
          id: n.id,
          type: 'default',
          position: n.position || { x: 0, y: 0 },
          data: {
            label: n.data?.label || n.type.split('.').pop(),
            ...n.data,
            nodeType: n.type,
          },
          style: { border: `1.5px solid ${STATUS_COLORS.IDLE}` },
        }));
        setNodes(flowNodes);
        setEdges((topo.edges || []).map(e => ({ ...e, type: 'deletable', animated: false })));
      });

    fetch(`/api/workflows/${workflowName}/trigger-info`)
      .then(r => r.json())
      .then(setTriggerInfo);
  }, [workflowName]);

  // Keep refs in sync for saveTopology
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);

  // Update node border colors on status change
  useEffect(() => {
    setNodes(nds =>
      nds.map(n => ({
        ...n,
        style: {
          ...n.style,
          border: `1.5px solid ${STATUS_COLORS[nodeStatuses[n.id]] || STATUS_COLORS.IDLE}`,
        },
      }))
    );
  }, [nodeStatuses]);

  // Scroll logs to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // postMessage from trigger test windows
  useEffect(() => {
    const handler = (event) => {
      if (event.data?.type === 'choola-test-done') {
        setWaitingForTrigger(false);
        setRunning(false);
        if (event.data.status === 'COMPLETED') {
          setLogs(prev => [...prev, '[DONE] Workflow completed via trigger']);
          const statuses = {};
          nodes.forEach(n => { statuses[n.id] = 'COMPLETED'; });
          setNodeStatuses(statuses);
        } else {
          setLogs(prev => [...prev, '[ERROR] Workflow failed via trigger']);
        }
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [nodes]);

  // Save topology
  const saveTopology = useCallback(() => {
    const topo = {
      nodes: nodesRef.current.map(n => ({
        id: n.id,
        type: n.data.nodeType,
        position: n.position,
        data: { label: n.data.label, config: n.data.config || {} },
      })),
      edges: edgesRef.current.map(e => ({ id: e.id, source: e.source, target: e.target })),
    };
    fetch(`/api/workflows/${workflowName}/topology`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(topo),
    });
  }, [workflowName]);

  const onNodeDragStop = useCallback(() => { saveTopology(); }, [saveTopology]);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, type: 'deletable' }, eds)),
    [setEdges],
  );

  // Double-click node → open code editor
  const onNodeDoubleClick = useCallback(async (_event, node) => {
    const nodeType = node.data.nodeType;
    if (!nodeType) return;
    try {
      const [srcRes, fieldsRes] = await Promise.all([
        fetch(`/api/nodes/${encodeURIComponent(nodeType)}/source`),
        fetch(`/api/nodes/${encodeURIComponent(nodeType)}/fields`),
      ]);
      if (!srcRes.ok) { alert('Could not load source code'); return; }
      const data = await srcRes.json();
      const fieldsData = fieldsRes.ok ? await fieldsRes.json() : { fields: [] };
      const docSections = parseChoolaDocstring(data.source);
      const codeBody = stripDocstring(data.source);
      const currentConfig = node.data.config || {};
      const configValues = {};
      for (const f of fieldsData.fields) {
        configValues[f.name] = currentConfig[f.name] ?? f.default ?? '';
      }
      const hasFields = fieldsData.fields.length > 0;
      setCodeModal({
        nodeId: node.id, nodeType, source: data.source, path: data.path,
        saving: false, docSections, codeBody,
        fields: fieldsData.fields, configValues,
        activeTab: hasFields ? 'config' : 'properties',
      });
    } catch (err) {
      alert(`Error loading source: ${err.message}`);
    }
  }, []);

  const handleSaveCode = async () => {
    if (!codeModal) return;
    setCodeModal(prev => ({ ...prev, saving: true }));
    const fullSource = rebuildSource(codeModal.docSections, codeModal.codeBody);
    try {
      const res = await fetch(`/api/nodes/${encodeURIComponent(codeModal.nodeType)}/source`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: fullSource }),
      });
      if (!res.ok) { alert('Failed to save'); return; }
      if (codeModal.configValues) {
        setNodes(nds => nds.map(n =>
          n.id === codeModal.nodeId
            ? { ...n, data: { ...n.data, config: { ...codeModal.configValues } } }
            : n
        ));
      }
      setCodeModal(null);
      setTimeout(saveTopology, 100);
    } catch (err) {
      alert(`Error saving: ${err.message}`);
    } finally {
      setCodeModal(prev => prev ? { ...prev, saving: false } : null);
    }
  };

  const handleSaveConfig = () => {
    if (!codeModal) return;
    setNodes(nds => nds.map(n =>
      n.id === codeModal.nodeId
        ? { ...n, data: { ...n.data, config: { ...codeModal.configValues } } }
        : n
    ));
    setCodeModal(null);
    setTimeout(saveTopology, 100);
  };

  // Publish / unpublish
  const handleToggleStatus = async () => {
    const newStatus = isPublished ? 'draft' : 'published';
    try {
      const res = await fetch(`/api/workflows/${workflowName}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      const result = await res.json();
      if (!res.ok) { alert(result.error || 'Failed to change status'); return; }
      setWorkflowStatus(newStatus);
      setLogs(prev => [...prev, `[INFO] Workflow ${newStatus === 'published' ? 'published' : 'unpublished'}`]);
    } catch (err) {
      alert(`Error: ${err.message}`);
    }
  };

  const attachSseBus = (runId) => {
    const bus = new EventSource(`/api/workflows/${workflowName}/stream/${runId}`);
    bus.addEventListener('node_status', (e) => {
      const data = JSON.parse(e.data);
      setNodeStatuses(prev => ({ ...prev, [data.node_id]: data.status }));
      setLogs(prev => [...prev, `[${data.status}] ${data.node_id}`]);
      setNodePayloads(prev => {
        const entry = { ...prev[data.node_id] };
        if (data.status === 'RUNNING' && data.payload !== undefined) entry.input = data.payload;
        if (data.status === 'COMPLETED' && data.payload !== undefined) entry.output = data.payload;
        if (data.status === 'ERROR') entry.error = data.error;
        return { ...prev, [data.node_id]: entry };
      });
    });
    bus.addEventListener('run_complete', (e) => {
      const data = JSON.parse(e.data);
      bus.close();
      setRunning(false);
      setWaitingForTrigger(false);
      if (data.status === 'COMPLETED') {
        setLogs(prev => [...prev, `[DONE] Output: ${JSON.stringify(data.payload)}`]);
      } else {
        setLogs(prev => [...prev, `[ERROR] ${data.error}`]);
      }
    });
    return bus;
  };

  // Run workflow
  const handleRun = async () => {
    setRunning(true);
    setLogs([]);
    setNodeStatuses({});
    setNodePayloads({});

    const tt = triggerInfo?.trigger_type;

    if (tt === 'form') {
      const runId = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
      setWaitingForTrigger(true);
      setLogs(prev => [...prev, '[INFO] Opening form... Submit the form to trigger the workflow.']);
      attachSseBus(runId);
      window.open(`/dev/${workflowName}/form?run_id=${runId}`, '_blank', 'width=600,height=700');
      return;
    }

    if (tt === 'webhook') {
      const runId = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
      const method = triggerInfo.config?.method || 'POST';
      const devUrl = `${window.location.origin}/dev/${workflowName}/webhook?run_id=${runId}`;
      setWaitingForTrigger(true);
      setLogs(prev => [
        ...prev,
        `[INFO] Waiting for webhook...`,
        `[INFO] ${method} ${devUrl}`,
        `[INFO] Send a request to trigger the workflow.`,
      ]);
      attachSseBus(runId);
      return;
    }

    let payload;
    try {
      payload = JSON.parse(payloadInput);
    } catch {
      alert('Invalid JSON payload');
      setRunning(false);
      return;
    }

    const runId = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
    attachSseBus(runId);
    fetch(`/api/workflows/${workflowName}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload, run_id: runId }),
    }).catch(err => {
      setRunning(false);
      setLogs(prev => [...prev, `[ERROR] ${err.message}`]);
    });
  };

  const handleCancelTest = () => {
    setWaitingForTrigger(false);
    setRunning(false);
    setLogs(prev => [...prev, '[INFO] Test cancelled']);
  };

  // Refresh (re-discover nodes)
  const handleRefresh = async () => {
    try {
      const res = await fetch(`/api/workflows/${workflowName}/refresh`, { method: 'POST' });
      if (!res.ok) { const d = await res.json(); alert(d.error || 'Refresh failed'); return; }
      const topo = await res.json();
      const flowNodes = (topo.nodes || []).map(n => ({
        id: n.id,
        type: 'default',
        position: n.position || { x: 0, y: 0 },
        data: {
          label: n.data?.label || n.type.split('.').pop(),
          ...n.data,
          nodeType: n.type,
        },
        style: { border: `1.5px solid ${STATUS_COLORS.IDLE}` },
      }));
      setNodes(flowNodes);
      setEdges((topo.edges || []).map(e => ({ ...e, type: 'deletable', animated: false })));
      setNodeStatuses({});
      fetch(`/api/workflows/${workflowName}/trigger-info`).then(r => r.json()).then(setTriggerInfo);
      setLogs(prev => [...prev, '[INFO] Workflow refreshed']);
    } catch (err) {
      alert(`Refresh error: ${err.message}`);
    }
  };

  // Refresh after chat changes topology
  const refreshAfterChat = useCallback(() => {
    fetch(`/api/workflows/${workflowName}/topology`)
      .then(r => r.json())
      .then(topo => {
        const flowNodes = (topo.nodes || []).map(n => ({
          id: n.id,
          type: 'default',
          position: n.position || { x: 0, y: 0 },
          data: {
            label: n.data?.label || n.type.split('.').pop(),
            ...n.data,
            nodeType: n.type,
          },
          style: { border: `1.5px solid ${STATUS_COLORS.IDLE}` },
        }));
        setNodes(flowNodes);
        setEdges((topo.edges || []).map(e => ({ ...e, type: 'deletable', animated: false })));
      });
  }, [workflowName]);

  // Credentials
  const refreshCredentials = () =>
    fetch('/api/credentials').then(r => r.json()).then(setCredentials);

  const handleOpenSettings = () => {
    refreshCredentials();
    setSettingsOpen(true);
  };

  const handleSaveCredential = async () => {
    if (credForm.provider === 'google_oauth2') {
      if (!credForm.name || !credForm.client_id || !credForm.client_secret) {
        alert('Name, Client ID, and Client Secret are required'); return;
      }
      const res = await fetch('/api/oauth2/google/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: credForm.name, client_id: credForm.client_id, client_secret: credForm.client_secret }),
      });
      if (!res.ok) { const d = await res.json(); alert(d.error || 'Failed'); return; }
      const { auth_url } = await res.json();
      window.open(auth_url, 'google_oauth2', 'width=500,height=600');
      const onMessage = (e) => {
        if (e.data === 'oauth2_done') {
          window.removeEventListener('message', onMessage);
          setCredForm({ name: '', provider: 'claude', value: '' });
          refreshCredentials();
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
    refreshCredentials();
  };

  const handleDeleteCredential = async (name) => {
    if (!confirm(`Delete credential "${name}"?`)) return;
    await fetch(`/api/credentials/${name}`, { method: 'DELETE' });
    refreshCredentials();
  };

  const runLabel = running ? 'Running...'
    : triggerInfo?.trigger_type === 'form' ? 'Test with form'
    : triggerInfo?.trigger_type === 'webhook' ? 'Test webhook'
    : 'Test workflow';

  // ── Render ────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#faf9f5', fontFamily: 'var(--font-ui)' }}>

      {/* ── Header ── */}
      <header style={{
        height: 52,
        display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px',
        background: '#ffffff',
        borderBottom: '0.8px solid rgba(31,30,29,0.1)',
        flexShrink: 0,
        zIndex: 10,
      }}>
        <button
          onClick={onBack}
          style={{ ...btnGhost, padding: '0 10px', height: 30, fontSize: 12, gap: 5 }}
          title="Back to workflows"
        >
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
            <path d="M12 4L6 10L12 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Back
        </button>

        <div style={{ width: '0.8px', height: 20, background: 'rgba(31,30,29,0.1)' }} />

        <span style={{ fontSize: 14, fontWeight: 600, color: '#141413', letterSpacing: '-0.01em' }}>
          {workflowName}
        </span>
        <StatusBadge status={workflowStatus} />

        <div style={{ flex: 1 }} />

        {/* Published trigger badge */}
        {isPublished && triggerInfo?.trigger_type && (
          <span style={{
            fontSize: 11, padding: '3px 9px', borderRadius: 6,
            background: '#e7f1da', color: '#2f7613',
            border: '0.8px solid rgba(47,118,19,0.2)',
            fontWeight: 500,
          }}>
            {triggerInfo.trigger_type === 'form'
              ? `Form at /webhook${triggerInfo.config?.path || ''}`
              : `Webhook ${triggerInfo.config?.method || 'POST'} /webhook${triggerInfo.config?.path || ''}`}
          </span>
        )}

        {/* Publish / Unpublish */}
        <button
          onClick={handleToggleStatus}
          style={{
            ...btnGhost,
            height: 30, fontSize: 12,
            color: isPublished ? '#b33232' : '#2f7613',
            borderColor: isPublished ? 'rgba(179,50,50,0.25)' : 'rgba(47,118,19,0.25)',
          }}
        >
          {isPublished ? 'Unpublish' : 'Publish'}
        </button>

        {/* AI Chat toggle — draft only */}
        {!isPublished && (
          <button
            onClick={() => setChatOpen(prev => !prev)}
            style={{
              ...btnGhost,
              height: 30, fontSize: 12,
              background: chatOpen ? '#f0eee6' : 'transparent',
              gap: 5,
            }}
          >
            <span style={{ fontSize: 13 }}>✦</span>
            {chatOpen ? 'Close chat' : 'AI chat'}
          </button>
        )}

        {/* Settings */}
        <button
          onClick={handleOpenSettings}
          style={{ ...btnGhost, height: 30, width: 30, padding: 0, fontSize: 14 }}
          title="Settings"
        >⚙</button>
      </header>

      {/* ── Body ── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* ── Left sidebar ── */}
        <aside style={{
          width: 240,
          background: '#ffffff',
          borderRight: '0.8px solid rgba(31,30,29,0.1)',
          display: 'flex', flexDirection: 'column',
          flexShrink: 0,
          overflowY: 'auto',
        }}>

          {/* Trigger info / Payload */}
          {triggerInfo?.trigger_type ? (
            <SidebarSection label="Trigger">
              <div style={{
                fontSize: 12, color: '#3d3d3a',
                background: '#faf9f5', padding: '9px 11px', borderRadius: 7,
                border: '0.8px solid rgba(31,30,29,0.1)',
                lineHeight: 1.5,
              }}>
                {triggerInfo.trigger_type === 'form'
                  ? 'Form trigger — click Test to open the form.'
                  : `Webhook trigger (${triggerInfo.config?.method || 'POST'}) — click Test to get the URL.`}
              </div>
            </SidebarSection>
          ) : (
            <SidebarSection label="Payload">
              <textarea
                rows={5}
                value={payloadInput}
                onChange={e => setPayloadInput(e.target.value)}
                style={{
                  width: '100%', padding: '8px 10px',
                  borderRadius: 7, border: '0.8px solid rgba(31,30,29,0.15)',
                  background: '#ffffff', color: '#141413',
                  fontFamily: 'var(--font-mono)', fontSize: 12,
                  resize: 'vertical', outline: 'none', lineHeight: 1.5,
                  transition: 'border-color 0.15s ease',
                }}
                onFocus={e => (e.target.style.borderColor = '#2c84db')}
                onBlur={e => (e.target.style.borderColor = 'rgba(31,30,29,0.15)')}
              />
            </SidebarSection>
          )}

          <Divider />

          {/* Run / Cancel */}
          <SidebarSection>
            {waitingForTrigger ? (
              <button onClick={handleCancelTest} style={{ ...btnPrimary, width: '100%', background: '#b33232', justifyContent: 'center' }}>
                Cancel test
              </button>
            ) : (
              <button
                onClick={handleRun}
                disabled={running}
                style={{
                  ...btnPrimary, width: '100%', justifyContent: 'center',
                  background: running ? '#e8e6dc' : '#141413',
                  color: running ? '#73726c' : '#ffffff',
                  cursor: running ? 'default' : 'pointer',
                }}
              >
                {running ? (
                  <>
                    <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', fontSize: 12 }}>◌</span>
                    Running...
                  </>
                ) : (
                  <>
                    <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M6.5 4.5l9 5.5-9 5.5V4.5z"/>
                    </svg>
                    {runLabel}
                  </>
                )}
              </button>
            )}
          </SidebarSection>

          {/* Save / Refresh — draft only */}
          {!isPublished && (
            <>
              <Divider />
              <SidebarSection>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    onClick={saveTopology}
                    style={{ ...btnGhost, flex: 1, justifyContent: 'center', fontSize: 12, height: 32 }}
                  >
                    Save layout
                  </button>
                  <button
                    onClick={handleRefresh}
                    title="Re-discover nodes"
                    style={{ ...btnGhost, height: 32, width: 32, padding: 0, fontSize: 15 }}
                  >↻</button>
                </div>
              </SidebarSection>
            </>
          )}

          <Divider />

          {/* Execution log */}
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, padding: '12px 16px', gap: 8, minHeight: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Execution log
            </div>
            <div style={{
              flex: 1, background: '#faf9f5', borderRadius: 7,
              border: '0.8px solid rgba(31,30,29,0.1)',
              padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: 11,
              overflowY: 'auto', minHeight: 80, lineHeight: 1.6,
            }}>
              {logs.length === 0 ? (
                <span style={{ color: '#73726c', fontStyle: 'italic' }}>No runs yet.</span>
              ) : logs.map((line, i) => (
                <div key={i} style={{
                  color: line.startsWith('[ERROR]') ? '#b33232'
                    : line.startsWith('[DONE]') ? '#2f7613'
                    : '#3d3d3a',
                  marginBottom: 2,
                }}>
                  {line}
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>
        </aside>

        {/* ── Canvas ── */}
        <div style={{ flex: 1, position: 'relative' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            edgeTypes={EDGE_TYPES}
            onNodesChange={isPublished ? undefined : onNodesChange}
            onEdgesChange={isPublished ? undefined : onEdgesChange}
            onConnect={isPublished ? undefined : onConnect}
            onEdgesDelete={isPublished ? undefined : saveTopology}
            onNodeDoubleClick={onNodeDoubleClick}
            onNodeDragStop={isPublished ? undefined : onNodeDragStop}
            nodesDraggable={!isPublished}
            nodesConnectable={!isPublished}
            elementsSelectable={!isPublished}
            fitView
          >
            <Controls />
            <Background color="#e8e6dc" gap={28} size={1} />
            {nodes.length === 0 && (
              <Panel position="top-center" style={{ marginTop: 40 }}>
                <div style={{
                  background: 'rgba(255,255,255,0.9)',
                  border: '0.8px solid rgba(31,30,29,0.12)',
                  borderRadius: 10, padding: '14px 20px',
                  fontSize: 13, color: '#73726c', textAlign: 'center',
                  boxShadow: 'rgba(0,0,0,0.05) 0px 2px 8px',
                }}>
                  No nodes yet — use AI chat or add nodes to <code style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>workflows/{workflowName}/nodes/</code>
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>

        {/* ── Chat panel ── */}
        {chatOpen && !isPublished && (
          <div style={{ width: 360, flexShrink: 0 }}>
            <ChatPanel workflowName={workflowName} onNodesChanged={refreshAfterChat} />
          </div>
        )}
      </div>

      {/* ── Settings modal ── */}
      {settingsOpen && (
        <div
          onClick={() => setSettingsOpen(false)}
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(20,20,19,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 200, padding: 24,
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#ffffff', borderRadius: 14, padding: '28px',
              width: '100%', maxWidth: 520, maxHeight: '80vh',
              display: 'flex', flexDirection: 'column', gap: 20,
              border: '0.8px solid rgba(31,30,29,0.1)',
              boxShadow: 'rgba(0,0,0,0.12) 0px 8px 32px',
              overflowY: 'auto',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 600, color: '#141413' }}>Credentials</h2>
                <p style={{ margin: 0, fontSize: 13, color: '#73726c' }}>
                  Store API keys for LLM providers. Reference them by name in nodes.
                </p>
              </div>
              <button
                onClick={() => setSettingsOpen(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 18, padding: 4, lineHeight: 1 }}
              >✕</button>
            </div>

            {credentials.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Saved</div>
                {credentials.map(c => {
                  const providerColors = {
                    claude: { bg: 'rgba(217,119,87,0.1)', color: '#c6613f', border: 'rgba(217,119,87,0.2)' },
                    google: { bg: 'rgba(44,132,219,0.1)', color: '#1b67b2', border: 'rgba(44,132,219,0.2)' },
                    google_oauth2: { bg: 'rgba(44,132,219,0.1)', color: '#1b67b2', border: 'rgba(44,132,219,0.2)' },
                  };
                  const pc = providerColors[c.provider] || { bg: '#f5f4ed', color: '#3d3d3a', border: 'rgba(31,30,29,0.15)' };
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
                        onClick={() => handleDeleteCredential(c.name)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 14, padding: '2px 4px', lineHeight: 1 }}
                      >✕</button>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Add credential form */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, background: '#faf9f5', padding: 16, borderRadius: 10, border: '0.8px solid rgba(31,30,29,0.1)' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#73726c', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Add credential</div>
              <input
                placeholder="Name (e.g. my-claude-key)"
                value={credForm.name}
                onChange={e => setCredForm(p => ({ ...p, name: e.target.value }))}
                style={{ ...inputStyle }}
              />
              <select
                value={credForm.provider}
                onChange={e => setCredForm(p => ({ ...p, provider: e.target.value }))}
                style={{ ...inputStyle }}
              >
                <option value="claude">Claude</option>
                <option value="gemini">Gemini</option>
                <option value="google">Google API Key</option>
                <option value="google_oauth2">Google OAuth2</option>
              </select>
              {credForm.provider === 'google_oauth2' ? (
                <>
                  <input
                    placeholder="Client ID"
                    value={credForm.client_id || ''}
                    onChange={e => setCredForm(p => ({ ...p, client_id: e.target.value }))}
                    style={{ ...inputStyle }}
                  />
                  <input
                    type="password"
                    placeholder="Client Secret"
                    value={credForm.client_secret || ''}
                    onChange={e => setCredForm(p => ({ ...p, client_secret: e.target.value }))}
                    style={{ ...inputStyle }}
                  />
                </>
              ) : (
                <input
                  type="password"
                  placeholder="API key"
                  value={credForm.value}
                  onChange={e => setCredForm(p => ({ ...p, value: e.target.value }))}
                  style={{ ...inputStyle }}
                />
              )}
              <button
                onClick={handleSaveCredential}
                style={{ ...btnPrimary, width: '100%', justifyContent: 'center' }}
              >
                {credForm.provider === 'google_oauth2' ? 'Connect with Google' : 'Save credential'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Node modal ── */}
      {codeModal && (() => {
        const nodeStatus = nodeStatuses[codeModal.nodeId];
        const payloadEntry = nodePayloads[codeModal.nodeId];
        const panelBorder = '0.8px solid rgba(31,30,29,0.1)';
        const panelHeaderStyle = {
          flexShrink: 0, padding: '0 16px', height: 38,
          display: 'flex', alignItems: 'center',
          borderBottom: panelBorder, background: '#faf9f5',
          fontSize: 10, fontWeight: 600, color: '#73726c',
          textTransform: 'uppercase', letterSpacing: '0.08em',
        };
        const tabBtn = (tab, label) => (
          <button
            key={tab}
            onClick={() => setCodeModal(prev => prev ? { ...prev, activeTab: tab } : null)}
            style={{
              padding: '0 18px', height: '100%', border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 500, fontFamily: 'var(--font-ui)',
              background: 'transparent',
              color: codeModal.activeTab === tab ? '#141413' : '#73726c',
              borderBottom: codeModal.activeTab === tab ? '2px solid #141413' : '2px solid transparent',
              transition: 'all 0.15s ease',
            }}
          >{label}</button>
        );
        const PayloadPane = ({ data, error, emptyMsg }) => (
          <div style={{ flex: 1, overflowY: 'auto', padding: 14 }}>
            {error
              ? <pre style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.6, color: '#b33232', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{error}</pre>
              : data !== undefined
                ? <pre style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.6, color: '#141413', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{JSON.stringify(data, null, 2)}</pre>
                : <span style={{ fontSize: 12, color: '#73726c', fontStyle: 'italic' }}>{emptyMsg}</span>
            }
          </div>
        );
        return (
          <div
            onClick={() => setCodeModal(null)}
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(20,20,19,0.5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              zIndex: 200,
            }}
          >
            <div
              onClick={e => e.stopPropagation()}
              style={{
                background: '#ffffff', borderRadius: 14,
                width: '88vw', height: '82vh',
                display: 'flex', flexDirection: 'column',
                border: panelBorder,
                boxShadow: 'rgba(0,0,0,0.12) 0px 8px 40px',
                overflow: 'hidden',
              }}
            >
              {/* Modal header */}
              <div style={{
                flexShrink: 0, height: 48,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0 20px',
                borderBottom: panelBorder, background: '#faf9f5',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#141413' }}>
                    {codeModal.nodeType.split('.').pop()}
                  </span>
                  <span style={{ fontSize: 11, color: '#73726c', fontFamily: 'var(--font-mono)' }}>
                    {codeModal.path}
                  </span>
                  {nodeStatus && (
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5,
                      background: nodeStatus === 'ERROR' ? 'rgba(179,50,50,0.1)' : nodeStatus === 'COMPLETED' ? 'rgba(47,118,19,0.1)' : 'rgba(135,90,8,0.1)',
                      color: STATUS_COLORS[nodeStatus],
                    }}>{nodeStatus}</span>
                  )}
                </div>
                <button
                  onClick={() => setCodeModal(null)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#73726c', fontSize: 18, padding: 4, lineHeight: 1 }}
                >✕</button>
              </div>

              {/* Body — 3 columns */}
              <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>

                {/* Left: input payload (25%) */}
                <div style={{ width: '25%', flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: panelBorder }}>
                  <div style={panelHeaderStyle}>Input Payload</div>
                  <PayloadPane
                    data={payloadEntry?.input}
                    emptyMsg="Run the workflow to see the input payload."
                  />
                </div>

                {/* Center: tabs (50%) */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: panelBorder }}>
                  {/* Tab bar */}
                  <div style={{
                    flexShrink: 0, height: 38, display: 'flex', alignItems: 'stretch',
                    borderBottom: panelBorder, background: '#faf9f5',
                  }}>
                    {tabBtn('properties', 'Properties')}
                    {codeModal.fields && codeModal.fields.length > 0 && tabBtn('config', 'Configuration')}
                    {tabBtn('code', 'Code')}
                  </div>

                  {/* Tab content */}
                  <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>

                    {/* Properties tab */}
                    {codeModal.activeTab === 'properties' && (
                      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 18px' }}>
                        <DocPanel sections={codeModal.docSections} />
                      </div>
                    )}

                    {/* Configuration tab */}
                    {codeModal.activeTab === 'config' && (
                      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
                        {(codeModal.fields || []).map(field => (
                          <div key={field.name} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <label style={{ fontSize: 13, fontWeight: 500, color: '#141413' }}>
                              {field.name}
                              {field.required && <span style={{ color: '#b33232', marginLeft: 4 }}>*</span>}
                            </label>
                            {field.description && (
                              <span style={{ fontSize: 12, color: '#73726c' }}>{field.description}</span>
                            )}
                            {field.type === 'select' ? (
                              <select
                                value={codeModal.configValues[field.name] ?? field.default ?? ''}
                                onChange={e => setCodeModal(prev => prev ? {
                                  ...prev, configValues: { ...prev.configValues, [field.name]: e.target.value },
                                } : null)}
                                disabled={isPublished}
                                style={{ ...inputStyle, height: 44 }}
                              >
                                <option value="">Select...</option>
                                {(field.options || []).map(opt => (
                                  <option key={opt} value={opt}>{opt}</option>
                                ))}
                              </select>
                            ) : field.type === 'textarea' ? (
                              <textarea
                                value={codeModal.configValues[field.name] ?? ''}
                                onChange={e => setCodeModal(prev => prev ? {
                                  ...prev, configValues: { ...prev.configValues, [field.name]: e.target.value },
                                } : null)}
                                readOnly={isPublished}
                                placeholder={field.placeholder || ''}
                                rows={4}
                                style={{
                                  width: '100%', padding: '10px 12px',
                                  borderRadius: 8, border: '0.8px solid rgba(31,30,29,0.15)',
                                  background: '#ffffff', color: '#141413',
                                  fontSize: 13, resize: 'vertical',
                                  fontFamily: 'var(--font-ui)', outline: 'none',
                                }}
                              />
                            ) : field.type === 'number' ? (
                              <input
                                type="number"
                                value={codeModal.configValues[field.name] ?? ''}
                                onChange={e => setCodeModal(prev => prev ? {
                                  ...prev, configValues: { ...prev.configValues, [field.name]: e.target.value === '' ? '' : Number(e.target.value) },
                                } : null)}
                                readOnly={isPublished}
                                placeholder={field.placeholder || ''}
                                style={{ ...inputStyle, height: 44, width: 200 }}
                              />
                            ) : field.type === 'json' ? (
                              <textarea
                                value={typeof codeModal.configValues[field.name] === 'string'
                                  ? codeModal.configValues[field.name]
                                  : JSON.stringify(codeModal.configValues[field.name] ?? '', null, 2)}
                                onChange={e => setCodeModal(prev => {
                                  if (!prev) return null;
                                  let val = e.target.value;
                                  try { val = JSON.parse(val); } catch {}
                                  return { ...prev, configValues: { ...prev.configValues, [field.name]: val } };
                                })}
                                readOnly={isPublished}
                                placeholder={field.placeholder || '[]'}
                                rows={6}
                                style={{
                                  width: '100%', padding: '10px 12px',
                                  borderRadius: 8, border: '0.8px solid rgba(31,30,29,0.15)',
                                  background: '#ffffff', color: '#141413',
                                  fontSize: 12, resize: 'vertical',
                                  fontFamily: 'var(--font-mono)', outline: 'none',
                                }}
                              />
                            ) : (
                              <input
                                type="text"
                                value={codeModal.configValues[field.name] ?? ''}
                                onChange={e => setCodeModal(prev => prev ? {
                                  ...prev, configValues: { ...prev.configValues, [field.name]: e.target.value },
                                } : null)}
                                readOnly={isPublished}
                                placeholder={field.placeholder || ''}
                                style={{ ...inputStyle, height: 44 }}
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Code tab */}
                    {codeModal.activeTab === 'code' && (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: '#1a1a18' }}>
                        <div style={{
                          fontSize: 11, fontWeight: 600, color: '#73726c', textTransform: 'uppercase',
                          letterSpacing: '0.08em', padding: '10px 16px 6px', flexShrink: 0,
                        }}>
                          Source code
                        </div>
                        <div className="code-editor-wrapper" style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
                          <pre
                            className="code-editor-pre"
                            aria-hidden="true"
                            style={{
                              position: 'absolute', inset: 0, margin: 0, padding: 16,
                              fontFamily: 'var(--font-mono)',
                              fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre', overflow: 'auto',
                              pointerEvents: 'none', color: '#ccc', background: 'transparent',
                            }}
                            dangerouslySetInnerHTML={{
                              __html: (() => {
                                try {
                                  return Prism.highlight(codeModal.codeBody || '', Prism.languages.python, 'python');
                                } catch {
                                  return (codeModal.codeBody || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
                                }
                              })() + '\n',
                            }}
                          />
                          <textarea
                            className="code-editor-textarea"
                            value={codeModal.codeBody || ''}
                            onChange={e => setCodeModal(prev => prev ? ({ ...prev, codeBody: e.target.value }) : null)}
                            readOnly={isPublished}
                            spellCheck={false}
                            style={{
                              position: 'relative', width: '100%', height: '100%',
                              margin: 0, padding: 16, border: 'none', outline: 'none', resize: 'none',
                              fontFamily: 'var(--font-mono)',
                              fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre', tabSize: 4,
                              color: 'transparent', caretColor: '#fff', background: 'transparent',
                            }}
                            onScroll={e => {
                              const pre = e.target.previousSibling;
                              if (pre) { pre.scrollTop = e.target.scrollTop; pre.scrollLeft = e.target.scrollLeft; }
                            }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Right: output payload (25%) */}
                <div style={{ width: '25%', flexShrink: 0, display: 'flex', flexDirection: 'column' }}>
                  <div style={panelHeaderStyle}>Output Payload</div>
                  <PayloadPane
                    data={payloadEntry?.output}
                    error={payloadEntry?.error}
                    emptyMsg="Run the workflow to see the output payload."
                  />
                </div>
              </div>

              {/* Modal footer */}
              <div style={{
                flexShrink: 0, display: 'flex', justifyContent: 'flex-end', gap: 8,
                padding: '10px 20px',
                borderTop: panelBorder, background: '#faf9f5',
              }}>
                <button onClick={() => setCodeModal(null)} style={btnGhost}>
                  {isPublished ? 'Close' : 'Cancel'}
                </button>
                {!isPublished && codeModal.activeTab !== 'properties' && (
                  <button
                    onClick={codeModal.activeTab === 'config' ? handleSaveConfig : handleSaveCode}
                    disabled={codeModal.saving}
                    style={{
                      ...btnPrimary,
                      background: codeModal.saving ? '#e8e6dc' : '#141413',
                      color: codeModal.saving ? '#73726c' : '#ffffff',
                      cursor: codeModal.saving ? 'default' : 'pointer',
                    }}
                  >
                    {codeModal.saving ? 'Saving...' : 'Save'}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
