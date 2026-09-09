// Browser fixture composition: production renderers, mocked Decky primitives.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { CommandCenterGrid, TileReason } from '@source/quick-access/command-center-grid';
import { CommandCenterHeader } from '@source/quick-access/page-layout';
import { ModulesButton, ModulesList, StatusLinks } from '@source/quick-access/shell';
import { TdpPicker, DisplayPicker } from '@source/quick-access/compact-picker';
import { AutoTdpModule } from '@source/quick-access/modules/auto-tdp';

const fixture = new URLSearchParams(location.search).get('fixture') ?? 'ready';
const unavailable = fixture === 'unavailable';
const manual = { schema_version: 1, enabled: true, can_enable: true, ready: true, code: 'tdp.ready',
  current_watts: 18, minimum_watts: 8, maximum_watts: 30, restore_available: true,
  recovery_required: false, last_result: null, auto_tdp_available: true };
const noop = async () => {};
const auto = { schema_version: 1, enabled: false, can_start: true, running: false, stopping: false,
  code: 'auto_tdp.ready', activity_code: null, target_fps: 60, minimum_watts: 8, maximum_watts: 30 };
const controller = { manual: fixture === 'auto-tdp-unavailable' ? null : fixture === 'auto-tdp-recovery' ? { ...manual, ready: false, recovery_required: true } : manual,
  auto: fixture === 'auto-tdp-unavailable' ? null : { ...auto, enabled: fixture === 'auto-tdp-running', running: fixture === 'auto-tdp-running', can_start: fixture !== 'auto-tdp-running' }, busy: false, stopping: false, refresh: noop,
  setEnabled: noop, apply: noop, restore: noop, start: noop, stop: noop };
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
  if (fixture === 'tdp-picker') return <main><TdpPicker status={manual as any} busy={false} onApply={() => {}} onConfigure={() => {}} /></main>;
  if (fixture === 'display-picker') return <main><DisplayPicker current="Handheld display" action={{ title: 'Use external display', description: 'Switch after the current game closes.', disabled: true } as any} onSwitch={() => {}} onConfigure={() => {}} /></main>;
  if (fixture.startsWith('auto-tdp')) return <main><AutoTdpModule controller={controller as any} /></main>;
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
