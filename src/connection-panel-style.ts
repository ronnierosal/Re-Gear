export const connectionPanelCss = `
.rg-connection-modal { background: linear-gradient(145deg,#18212c,#10171f) !important; border:1px solid #394653; border-radius:18px; }
.rg-connection { color:#edf3f8; font-size:16px; line-height:1.4; min-width:320px; max-width:520px; }
.rg-connection-subtitle { color:#b5c3d2; margin:0 0 18px; }
.rg-connection-list { border:1px solid #394653; border-radius:12px; padding:0 14px; }
.rg-connection-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid #303c48; }
.rg-connection-row:last-child { border:0; }
.rg-connection-label { flex:1; }
.rg-connection-state { display:flex; align-items:center; gap:8px; font-size:14px; white-space:nowrap; }
.rg-connection-ready { color:#87da91; }
.rg-connection-waiting { color:#ffd16b; }
.rg-connection-blocked { color:#ff9c93; }
.rg-connection-icon { width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; }
.rg-connection-ring { width:17px; height:17px; border:2px solid #ffd16b40; border-top-color:currentColor; border-right-color:currentColor; border-radius:50%; animation:rg-connection-spin 1.3s linear infinite; }
.rg-connection-check { animation:rg-connection-reveal .2s ease-out; }
.rg-connection-detail { margin:16px 0 8px; color:#b5c3d2; font-size:14px; }
.rg-connection-foot { color:#95a6b7; font-size:13px; margin:8px 0 0; }
.rg-connection-hero { display:flex; justify-content:center; padding:20px 0; color:#87da91; }
.rg-connection-hero svg { width:76px; height:76px; }
.rg-connection-sweep { overflow:hidden; height:3px; background:#33414f; margin:22px 0; border-radius:3px; }
.rg-connection-sweep::after { content:''; display:block; width:35%; height:100%; background:#66d9f7; animation:rg-connection-sweep 1.8s ease-in-out infinite; }
@keyframes rg-connection-spin { to { transform:rotate(360deg); } }
@keyframes rg-connection-reveal { from { opacity:.3; transform:scale(.8); } to { opacity:1; transform:scale(1); } }
@keyframes rg-connection-sweep { from { transform:translateX(-110%); } to { transform:translateX(390%); } }
@media (prefers-reduced-motion:reduce) { .rg-connection-ring,.rg-connection-check,.rg-connection-sweep::after { animation:none; } }
@media (max-height:700px) { .rg-connection-row { padding:7px 0; } .rg-connection-subtitle { margin-bottom:12px; } }
`;
