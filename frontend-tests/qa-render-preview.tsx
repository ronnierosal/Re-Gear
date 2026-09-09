// Browser fixture composition: production renderers, mocked Decky primitives.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CommandCenterGrid, TileReason } from '@source/quick-access/command-center-grid';
import { CommandCenterHeader } from '@source/quick-access/page-layout';
import { ModulesButton, ModulesList, StatusLinks } from '@source/quick-access/shell';

const fixture = new URLSearchParams(location.search).get('fixture') ?? 'ready';
const unavailable = fixture === 'unavailable';
const tiles = [
  ['fps', 'FPS target', 'Unavailable', false, null],
  ['tdp', 'TDP limit', unavailable ? 'Unknown' : '18 W', !unavailable, 'Change limit'],
  ['auto-tdp', 'Auto TDP', unavailable ? 'Unavailable' : 'Running', !unavailable, 'Stop'],
  ['display', 'Display target', 'Handheld', !unavailable, 'Change display'],
  ['safe-disconnect', 'Safe Disconnect', 'In development', false, null],
].map(([id, title, text, available, actionLabel]) => ({ id, title, value: { text, known: available }, available,
  actionLabel, activation: available ? 'open' : 'notice', developmental: id === 'safe-disconnect',
  reason: available ? null : 'Current evidence does not permit this action.' }));
const modules = [
  { id: 'egpu', title: 'eGPU', summary: 'Connection, display and dock actions', available: true, reason: null },
  { id: 'auto-tdp', title: 'Auto TDP', summary: 'Power limits and automatic tuning', available: !unavailable, reason: unavailable ? 'Status not yet observed.' : null },
  { id: 'controller', title: 'Controller', summary: 'Bindings and controller preferences', available: true, reason: null },
];
function App() {
  const [route, setRoute] = useState(fixture === 'modules' ? 'modules' : 'home');
  const [selected, select] = useState<string>();
  return <main>
    {route === 'home' ? <>
      <CommandCenterHeader mode="Portable" display="Handheld display"
        game={fixture === 'long-name' ? 'A very long game title with extra words and multilingual text 日本語' : 'Game running'}
        health={fixture === 'attention' ? 'Display status needs attention. Recheck the connected display.' : 'Ready'}
        navigation={<ModulesButton onOpen={() => setRoute('modules')} />} />
      <CommandCenterGrid tiles={tiles as any} onActivate={select} />
      <TileReason tile={tiles.find(tile => tile.id === selected) as any} />
      <StatusLinks entries={[{ id: 'egpu', title: 'eGPU status', detail: 'Not connected' },
        { id: 'controller', title: 'Controller status', detail: 'Built-in controller' }]} onOpen={select} />
    </> : <><button onClick={() => setRoute('home')}>Back</button><h3>Modules</h3>
      <ModulesList modules={modules as any} onOpen={select} /></>}
    {selected && <div role="status">Selected: {selected}</div>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App />);
