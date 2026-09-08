export const connectionPanelCss = `
.rg-connection-modal.rg-connection-compact { padding:6px !important; min-width:0 !important; width:min(432px,calc(100vw - 24px)) !important; }
.rg-connection-modal { background: linear-gradient(145deg,#18212c,#10171f) !important; border:1px solid #394653; border-radius:14px; box-sizing:border-box; max-width:calc(100vw - 32px); max-height:calc(100vh - 32px); overflow-y:auto; }
.rg-connection { color:#edf3f8; font-size:16px; line-height:1.4; min-width:0; width:100%; max-width:520px; }
.rg-connection-subtitle { color:#b5c3d2; margin:0 0 18px; }
.rg-connection-list { border:1px solid #394653; border-radius:12px; padding:0 14px; }
.rg-connection-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid #303c48; }
.rg-connection-row:last-child { border:0; }
.rg-connection-label { flex:1; min-width:0; overflow-wrap:break-word; }
.rg-connection-state { display:flex; align-items:center; gap:8px; font-size:14px; white-space:nowrap; }
.rg-connection-ready { color:#87da91; }
.rg-connection-waiting { color:#ffd16b; }
.rg-connection-blocked { color:#ffd16b; }
.rg-connection-icon { width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; }
.rg-connection-ring { width:17px; height:17px; border:2px solid transparent; border-top-color:currentColor; border-right-color:currentColor; border-radius:50%; animation:rg-connection-spin 1.3s linear infinite; }
.rg-connection-check { animation:rg-connection-reveal .2s ease-out; }
.rg-connection-detail { margin:16px 0 8px; color:#b5c3d2; font-size:14px; }
.rg-connection-foot { color:#95a6b7; font-size:13px; margin:8px 0 0; }
.rg-connection-hero { display:flex; justify-content:center; padding:20px 0; color:#87da91; }
.rg-connection-hero .rg-connection-icon, .rg-connection-hero svg { width:76px; height:76px; }
.rg-connection-sweep { overflow:hidden; height:3px; background:#33414f; margin:22px 0; border-radius:3px; }
.rg-connection-sweep::after { content:''; display:block; width:35%; height:100%; background:#66d9f7; animation:rg-connection-sweep 1.8s ease-in-out infinite; }
@keyframes rg-connection-spin { to { transform:rotate(360deg); } }
@keyframes rg-connection-reveal { from { opacity:.3; transform:scale(.8); } to { opacity:1; transform:scale(1); } }
@keyframes rg-connection-sweep { from { transform:translateX(-110%); } to { transform:translateX(390%); } }
@media (prefers-reduced-motion:reduce) { .rg-connection-ring,.rg-connection-check,.rg-connection-sweep::after { animation:none; } }
/* Modal density is independent of the physical display resolution: Steam can
   scale its UI while reporting a large CSS viewport. Keep the base compact. */
.rg-connection-modal .rg-connection { font-size:14px; line-height:1.3; max-width:440px; }
.rg-connection-modal .rg-connection-subtitle { margin:0 0 8px; font-size:13px; }
.rg-connection-modal .rg-connection-list { padding:0 10px; }
.rg-connection-modal .rg-connection-row { padding:4px 0; gap:8px; min-height:20px; }
.rg-connection-modal .rg-connection-icon, .rg-connection-modal .rg-connection-icon svg { width:18px; height:18px; }
.rg-connection-modal .rg-connection-ring { width:14px; height:14px; }
.rg-connection-modal .rg-connection-detail { margin:8px 0 4px; font-size:13px; }
.rg-connection-modal .rg-connection-foot { margin:4px 0 0; font-size:12px; }
.rg-connection-modal .rg-connection-hero { padding:10px 0; }
.rg-connection-modal .rg-connection-hero .rg-connection-icon, .rg-connection-modal .rg-connection-hero svg { width:48px; height:48px; }
.rg-connection-modal .rg-connection-sweep { margin:12px 0; }
@media (max-height:540px) {
  .rg-connection-modal { padding:16px !important; }
  .rg-connection-modal .rg-connection-row { padding:2px 0; }
}
`;
