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

/**
 * NodePalette — draggable sidebar listing all registered node types,
 * grouped by category.  Drag a node onto the React Flow canvas to add it.
 */
export default function NodePalette({ catalog }) {
  // Group by category
  const grouped = {};
  for (const node of catalog) {
    const cat = node.category || 'general';
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(node);
  }

  const onDragStart = (event, nodeType, nodeName) => {
    event.dataTransfer.setData('application/choola-node-type', nodeType);
    event.dataTransfer.setData('application/choola-node-name', nodeName);
    event.dataTransfer.effectAllowed = 'move';
  };

  if (catalog.length === 0) {
    return <div style={{ color: '#666', fontSize: 12 }}>No nodes registered</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(grouped).map(([category, nodes]) => (
        <div key={category}>
          <div style={{ fontSize: 10, color: '#666', textTransform: 'uppercase', marginBottom: 4 }}>
            {category}
          </div>
          {nodes.map(node => (
            <div
              key={node.type}
              draggable
              onDragStart={e => onDragStart(e, node.type, node.name)}
              style={{
                padding: '6px 10px',
                marginBottom: 4,
                background: '#16213e',
                borderRadius: 4,
                cursor: 'grab',
                fontSize: 13,
                border: '1px solid #2a2a4a',
                transition: 'border-color 0.2s',
              }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = '#7c3aed')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = '#2a2a4a')}
              title={node.description}
            >
              {node.name}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
