import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ExpandedCommandCenter } from '../src/quick-access/expanded-command-center/shell';

const tabs = ['quick', 'performance', 'egpu', 'controllers', 'settings'] as const;
const query = new URLSearchParams(location.search);
const initialTab = tabs.find(tab => tab === query.get('tab')) ?? 'quick';
function Preview() {
  const [open, setOpen] = useState(true);
  return <>
    <div className="sample-world" aria-hidden="true"><span>SIMULATED GAME BACKDROP</span><div className="sample-road" /></div>
    {open ? <ExpandedCommandCenter initialTab={initialTab} previewColumns={query.get("columns") === "3" ? 3 : query.get("columns") === "4" ? 4 : undefined} longReasons={query.has('long')} onClose={() => setOpen(false)} /> :
      <button id="reopen" onClick={() => setOpen(true)}>Reopen sample Command Center</button>}
    <div className="preview-disclaimer">SYNTHETIC PREVIEW · SAMPLE DATA · NO DEVICE ACTIONS</div>
  </>;
}
createRoot(document.getElementById('root')!).render(<Preview />);
