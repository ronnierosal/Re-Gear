export const connectionPanelCss = `
.rg-popup-host{position:fixed!important;left:50%!important;top:50%!important;right:auto!important;bottom:auto!important;margin:0!important;transform:translate(-50%,-50%)!important;width:max-content!important;min-width:0!important}
.rg-popup-host .rg-popup-body{overflow-y:auto!important}
.rg-popup-recovery:empty{display:none}.rg-popup-recovery{flex:0 0 100%;min-width:0}.rg-compact .rg-popup-footer:has(.rg-popup-recovery:not(:empty)){flex-wrap:wrap}
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
/* Stage-driven milestones: segments fill by completed milestones only, never by time. */
.rg-milestones{display:flex;flex-direction:column;gap:4px}
.rg-milestone-bar{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:3px}
.rg-milestone-segment{height:4px;border-radius:2px;background:#304b60}
.rg-milestone-segment[data-state=done]{background:#87da91}
.rg-milestone-segment[data-state=active]{background:linear-gradient(90deg,#1c6d8a 0,#39d8ff 50%,#1c6d8a 100%);background-size:200% 100%;animation:rg-milestone-shimmer 1.4s linear infinite}
.rg-milestone-segment[data-state=attention]{background:#ffc247}
.rg-milestone-segment[data-state=stale]{background:#51606e}
.rg-milestone-current{font-size:13px;font-weight:600;color:#edf3f8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rg-milestones .rg-flow-node span{max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rg-milestone-list{list-style:none;margin:0;padding:4px 8px;display:flex;flex-direction:column;gap:1px;background:#112333;border:1px solid #1e3548;border-radius:8px}
.rg-milestone{display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.35;color:#93adc1}
.rg-milestone-dot{width:10px;height:10px;border-radius:50%;border:2px solid #304b60;box-sizing:border-box;flex:0 0 auto}
.rg-milestone-label{flex:1;min-width:0}
.rg-milestone-status{font-size:11px;white-space:nowrap}
.rg-milestone[data-state=done]{color:#c9dfef}.rg-milestone[data-state=done] .rg-milestone-dot{background:#87da91;border-color:#87da91;animation:rg-milestone-pop .2s ease-out}.rg-milestone[data-state=done] .rg-milestone-status{color:#87da91}
.rg-milestone[data-state=active]{color:#edf3f8;font-weight:600}.rg-milestone[data-state=active] .rg-milestone-dot{border-color:#39d8ff;animation:rg-milestone-pulse 1.4s ease-out infinite}.rg-milestone[data-state=active] .rg-milestone-status{color:#39d8ff}
.rg-milestone[data-state=attention]{color:#edf3f8}.rg-milestone[data-state=attention] .rg-milestone-dot{border-color:#ffc247;background:#ffc247}.rg-milestone[data-state=attention] .rg-milestone-status{color:#ffc247}
.rg-milestone[data-state=stale]{color:#7d8c99}.rg-milestone[data-state=stale] .rg-milestone-dot{border-color:#51606e;background:#51606e}
.rg-milestone-live{display:flex;align-items:center;gap:6px;font-size:11px;color:#93adc1}
.rg-live-dot{width:7px;height:7px;border-radius:50%;background:#51606e}
.rg-milestone-live[data-live=true] .rg-live-dot{background:#87da91;animation:rg-popup-pulse 1.4s ease-in-out infinite}
.rg-milestone-slow{font-size:12px;color:#ffc247}
/* Stale evidence is history: no motion anywhere in the popup. */
.rg-popup:has(.rg-milestones[data-stale=true]) .rg-popup-state-icon,.rg-milestones[data-stale=true] .rg-flow-line{animation:none!important}
@keyframes rg-milestone-shimmer{from{background-position:100% 0}to{background-position:-100% 0}}
@keyframes rg-milestone-pulse{0%{box-shadow:0 0 0 0 rgba(57,216,255,.55)}70%{box-shadow:0 0 0 6px rgba(57,216,255,0)}100%{box-shadow:0 0 0 0 rgba(57,216,255,0)}}
@keyframes rg-milestone-pop{from{transform:scale(.6);opacity:.4}to{transform:scale(1);opacity:1}}
@media(min-height:650px){.rg-milestones{gap:8px}.rg-milestone-current{font-size:16px}.rg-milestone{font-size:13px}.rg-milestone-list{padding:8px 12px;gap:3px}}
@media(prefers-reduced-motion:reduce){.rg-milestone-segment,.rg-milestone-dot,.rg-live-dot{animation:none!important}}
`;
