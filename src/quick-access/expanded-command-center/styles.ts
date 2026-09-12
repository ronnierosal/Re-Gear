/** Shared browser/native presentation; state and launcher logic remain separate. */
export const expandedStyles = `
.rg-expanded-backdrop{position:fixed;inset:0;z-index:10;display:flex;align-items:center;padding:9vh 0 9vh 2vw;box-sizing:border-box;background:#0009;color:#f4f7fb;font-family:Arial,sans-serif}
.rg-expanded-frame{position:relative;display:flex;align-items:flex-start;min-width:0;max-width:96vw;max-height:82vh;color:#f4f7fb}
.rg-expanded{box-sizing:border-box;width:min(64vw,980px);height:82vh;max-height:82vh;display:flex;flex-direction:column;min-width:0;overflow:hidden;border:1px solid #315c75;border-radius:16px;background:linear-gradient(145deg,#102536fb,#061520fb 62%,#04101afe);box-shadow:0 22px 70px #000b;font-size:14px;container:rg-menu / inline-size}
.rg-expanded *{box-sizing:border-box}.rg-expanded button,.rg-expanded select{font:inherit;color:inherit;cursor:pointer;white-space:normal;line-height:1.3;text-transform:none;letter-spacing:normal}

.rg-expanded-brand{position:relative;display:flex;align-items:center;justify-content:space-between;gap:12px;flex:0 0 auto;min-height:0;margin:0;padding:10px 16px 8px}
.rg-expanded-wordmark{display:flex;align-items:center;gap:9px;font-size:25px;font-weight:780;letter-spacing:-.5px;white-space:nowrap}.rg-expanded-wordmark img{width:32px;height:32px}
.rg-expanded-demo{display:flex;flex-direction:column;gap:2px;text-align:right;font-size:9px;color:#86a9c0;line-height:1.25}.rg-expanded-demo-label{display:flex;align-items:center;justify-content:flex-end;gap:5px;color:#bdd8e9}.rg-expanded-demo-label i{width:5px;height:5px;background:#39d8ff;border-radius:50%;box-shadow:0 0 8px #39d8ff88}

.rg-expanded-tabs{position:relative;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));flex:0 0 auto;min-width:0;margin:0 14px 8px;border:1px solid #28526d;border-radius:12px;overflow:hidden;background:#061a29d9;box-shadow:inset 0 1px 0 #ffffff08}
.rg-expanded .rg-expanded-tab{position:relative;min-width:0;max-width:100%;width:100%;height:50px;min-height:0;margin:0;padding:5px 3px;border:0;border-bottom:3px solid transparent;border-radius:0;background:transparent;box-shadow:none;font-size:11px;color:#a9c4d6}
.rg-expanded-tab+.rg-expanded-tab:before{content:'';position:absolute;left:0;top:22%;height:56%;width:1px;background:#214258}
.rg-expanded-tab-body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px}.rg-expanded-tab svg{width:21px;height:21px}
.rg-expanded-tab[aria-selected=true]{background:linear-gradient(0deg,#07506d8a,transparent 72%);border-bottom-color:#39d8ff;color:#63e5ff;box-shadow:inset 0 -8px 18px #1bc6ff14}

.rg-expanded-content{position:relative;flex:1 1 0;min-height:0;overflow:auto;overflow-x:hidden;margin:0;padding:10px 15px 12px;scrollbar-color:#315f78 #061724;scrollbar-width:thin;scroll-padding-block:10px;overscroll-behavior:contain}
.rg-expanded h2{font-size:22px;line-height:1.2;margin:0 0 3px;letter-spacing:-.3px}.rg-expanded h3{font-size:18px;margin:0 0 10px}.rg-expanded-context{font-size:12px;line-height:1.35;color:#9fc3dc;margin:0 0 8px}

/* Quick already identifies itself in the selected tab. Remove the redundant root
   heading/subtitle, while retaining nested Quick detail headings. */
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page))>h2,
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page))>.rg-expanded-context{display:none}

.rg-expanded-grid{display:grid;grid-template-columns:repeat(var(--ec-columns),minmax(0,1fr));gap:10px;min-width:0;align-items:stretch}
.rg-expanded .rg-expanded-tile{position:relative;display:block;width:100%;min-width:0;max-width:100%;min-height:116px;height:auto;margin:0;padding:12px;border:1px solid #315f79;border-radius:13px;background:linear-gradient(150deg,#113247,#0a2233 58%,#071827);box-shadow:inset 0 1px 0 #ffffff0b,0 6px 18px #00000022;text-align:left;overflow:hidden;transition:border-color .12s ease,background .12s ease,box-shadow .12s ease}
.rg-expanded-tile:before{content:'';position:absolute;top:0;right:0;width:58%;height:44%;background:linear-gradient(135deg,#39d8ff12,transparent 70%);clip-path:polygon(32% 0,100% 0,62% 100%,0 100%);pointer-events:none}
.rg-expanded-tile:after{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:#39d8ff00;transition:background .12s ease}
.rg-expanded-tile-body{position:relative;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;min-width:0;gap:6px;width:100%;height:auto}
.rg-expanded-tile-heading{display:flex;align-items:center;gap:8px;width:100%;min-width:0}.rg-expanded-tile-icon{position:static;display:grid;place-items:center;flex:0 0 auto;width:30px;height:30px;margin:0;border:1px solid #386783;border-radius:9px;background:#0b2435;color:#ccecff;box-shadow:inset 0 1px 0 #ffffff09}.rg-expanded-tile-icon svg{width:22px;height:22px}
.rg-expanded-label{font-size:12.5px;font-weight:680;line-height:1.2;color:#e7f4fb;overflow-wrap:normal;word-break:normal}.rg-expanded-value{display:block;max-width:100%;font-size:18px;line-height:1.18;font-weight:780;letter-spacing:-.2px;overflow-wrap:normal;word-break:normal;hyphens:none}.rg-expanded-detail{display:block;padding-right:14px;font-size:10.5px;line-height:1.35;color:#95b8cf;overflow-wrap:normal;word-break:normal}
.rg-expanded-chevron{position:absolute;right:0;bottom:-2px;font-size:24px;line-height:1;color:#8ccce8}
.rg-expanded-tile[data-tone=active] .rg-expanded-value,.rg-expanded-tile[data-tone=active] .rg-expanded-tile-icon{color:#39d8ff}.rg-expanded-tile[data-tone=active]:after{background:#39d8ff}.rg-expanded-tile[data-ec-control=egpu] .rg-expanded-value{color:#49e6b1}
.rg-expanded-tile[data-tone=unavailable]{background:linear-gradient(150deg,#162936,#0d1d29);border-color:#334d60}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-value,.rg-expanded-tile[data-tone=unavailable] .rg-expanded-tile-icon{color:#8fa7b9}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-tile-icon{background:#0a1a25;border-color:#2c4658}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-detail{color:#859eaf}
.rg-expanded-tile[data-ec-control=disconnect]{border-color:#8d7138;background:linear-gradient(145deg,#493b221e,#142a3a 48%,#091b2a)}.rg-expanded-tile[data-ec-control=disconnect]:after{background:#ffc247}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-body{padding:0;justify-content:flex-start;gap:6px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon{color:#ffc247;border-color:#8b6c35;background:#2b2517}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{display:flex;align-items:center;gap:5px;color:#ffc247;font-size:16px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:10.5px;color:#bfae86}

.rg-expanded button:hover{border-color:#75acc8}.rg-expanded button:focus,.rg-expanded button:focus-visible,.rg-expanded button.gpfocus{outline:2px solid #39d8ff!important;outline-offset:-2px;background:linear-gradient(145deg,#17465f,#0b2d42)!important;box-shadow:0 0 0 1px #39d8ff33,0 0 18px #39d8ff2a,inset 0 1px 0 #ffffff10!important;color:#f4f7fb!important}.rg-expanded button:focus:after,.rg-expanded button:focus-visible:after,.rg-expanded button.gpfocus:after{background:#39d8ff}.rg-expanded-tab[aria-selected=true]:focus{border-bottom-color:#39d8ff;color:#63e5ff!important}

.rg-expanded-info{display:flex;align-items:center;gap:9px;padding:9px 10px;margin-top:10px;border:1px solid #294f68;border-radius:11px;background:#0b2231a6;color:#8fd5f0;box-shadow:inset 0 1px 0 #ffffff08}.rg-expanded-info>span{min-width:0}.rg-expanded-info strong{display:block;font-size:11px;font-weight:650;color:#dbeef9;line-height:1.3}.rg-expanded-info small{display:block;margin-top:2px;font-size:9.5px;color:#91b7d1;line-height:1.3}.rg-expanded-badges{display:flex;flex-wrap:wrap;gap:5px;margin-left:auto}.rg-expanded-badges>span{display:flex;align-items:center;gap:4px;white-space:nowrap;font-size:9px;padding:4px 7px;border:1px solid #315c75;border-radius:14px;color:#b7d8ed;background:#061827}

.rg-expanded-footer{position:relative;display:flex;align-items:center;gap:9px;flex:0 0 auto;min-height:34px;margin:0;padding:6px 11px;border-top:1px solid #294f68;background:#061521;font-size:10px;white-space:nowrap}.rg-expanded-footer>span{display:inline-flex;align-items:center;gap:5px}.rg-expanded-footer-spacer{flex:1}.rg-expanded kbd{font:650 10px Arial,sans-serif;padding:2px 4px;border:1px solid #6099b8;border-radius:5px;background:linear-gradient(#20455b,#0a2538);box-shadow:inset 0 1px 0 #ffffff12;color:#e3f6ff}.rg-expanded kbd.rg-expanded-round{display:inline-grid;place-items:center;width:19px;height:19px;border-radius:50%;padding:0;color:#72e5ff}

.rg-expanded-back{padding:8px 12px;min-height:36px;border:1px solid #4f809c;border-radius:8px;background:#12364b}.rg-expanded-detail-page{padding:14px;background:#102b3e;border:1px solid #356683;border-radius:11px;line-height:1.45}.rg-expanded-detail-page p{color:#b1cfe3}.rg-expanded-settings-section{position:relative;padding:14px;border:1px solid #315c76;border-radius:11px;background:#0a2133;margin-bottom:12px}.rg-expanded-settings-list .rg-expanded-settings-section{padding:0;margin:0;background:none;border:0}.rg-expanded-settings-list .rg-expanded .rg-expanded-tile{height:100%}.rg-expanded-anchor{position:absolute;top:0;left:0;width:1px;height:1px;overflow:hidden;pointer-events:none}.rg-expanded-shortcut-control{max-width:280px}.rg-expanded-shortcut-select{max-width:100%;width:280px;padding:9px 12px;min-height:42px;background:#173b4d;border:1px solid #5097b4;border-radius:8px;color:#f4f7fb}.rg-expanded-shortcut-select:focus{outline:2px solid #39d8ff;outline-offset:2px}.rg-expanded-note{margin:12px 0 0}

/* Brightness/volume are part of the main Command Center composition rather than
   a detached settings card. Keep the rail visually quiet so the tile grid remains
   the primary action surface. */
.rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{position:absolute;z-index:3;left:14px;top:108px;bottom:42px;width:clamp(72px,7.5vw,86px);max-height:none;overflow:hidden}
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:calc(clamp(72px,7.5vw,86px) + 28px)}

/* Detached thumb rail: compact icon-first actions with enough separation from the
   main panel that the running game still reads between both surfaces. */
.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{position:fixed;z-index:3;right:2.2vw;top:9vh;width:clamp(76px,7vw,92px);height:82vh;max-height:82vh;overflow:hidden;justify-content:center}

@container rg-menu (max-width:760px){
  .rg-expanded-brand{padding:7px 11px}.rg-expanded-wordmark{font-size:21px}.rg-expanded-wordmark img{width:28px;height:28px}.rg-expanded-demo{font-size:8px}
  .rg-expanded-tabs{margin:0 10px 7px}.rg-expanded .rg-expanded-tab{height:44px;font-size:10px}.rg-expanded-tab svg{width:18px;height:18px}
  .rg-expanded-content{padding:8px 10px}.rg-expanded-grid{gap:7px}.rg-expanded .rg-expanded-tile{min-height:98px;padding:8px}.rg-expanded-tile-icon{width:27px;height:27px}.rg-expanded-tile-icon svg{width:19px;height:19px}.rg-expanded-label{font-size:11px}.rg-expanded-value{font-size:15px}.rg-expanded-detail{font-size:9.5px}
  .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{font-size:13px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:9.5px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{left:10px;top:96px;bottom:38px;width:68px}
  .rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:84px}
}

@media(max-height:520px){
  .rg-expanded-backdrop{padding-block:6vh}.rg-expanded{height:88vh;max-height:88vh}.rg-expanded-frame{max-height:88vh}
  .rg-expanded-brand{padding:5px 10px}.rg-expanded-wordmark{font-size:19px}.rg-expanded-wordmark img{width:25px;height:25px}.rg-expanded-demo{font-size:7.5px}
  .rg-expanded .rg-expanded-tab{height:39px;font-size:9px}.rg-expanded-tab svg{width:16px;height:16px}.rg-expanded-content{padding-top:6px;padding-bottom:6px}
  .rg-expanded .rg-expanded-tile{min-height:82px;padding:7px}.rg-expanded-tile-icon{width:24px;height:24px;border-radius:7px}.rg-expanded-tile-icon svg{width:16px;height:16px}.rg-expanded-label{font-size:10px}.rg-expanded-value{font-size:13px}.rg-expanded-detail{font-size:8.5px;line-height:1.2}.rg-expanded-chevron{font-size:18px}
  .rg-expanded-info{padding:6px 8px;margin-top:6px}.rg-expanded-info small{font-size:8px}.rg-expanded-footer{min-height:28px;padding:3px 8px;font-size:9px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{top:79px;bottom:31px;width:64px;left:9px}
  .rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:78px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{top:6vh;height:88vh;max-height:88vh;width:70px}
}

@media(max-width:900px){.rg-expanded{width:72vw}}
@media(max-width:760px){
  .rg-expanded-backdrop{padding-left:2vw}.rg-expanded{width:76vw}.rg-expanded-frame{max-width:98vw}.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{right:1.5vw}
}
@media(max-width:620px){
  .rg-expanded{width:80vw}.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{width:64px}.rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{width:60px}.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:72px}
}
`;
