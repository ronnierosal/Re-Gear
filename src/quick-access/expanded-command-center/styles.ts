/** Shared browser/native presentation; state and launcher logic remain separate. */
export const expandedStyles = `
.rg-expanded-backdrop{position:fixed;inset:0;z-index:10;display:flex;align-items:center;padding:9vh 0 9vh 2vw;box-sizing:border-box;background:#0008;color:#f4f7fb;font-family:Arial,sans-serif}
.rg-expanded-frame{position:relative;display:flex;align-items:flex-start;min-width:0;max-width:96vw;max-height:82vh;color:#f4f7fb}
.rg-expanded{box-sizing:border-box;width:min(74vw,1120px);height:82vh;max-height:82vh;display:flex;flex-direction:column;min-width:0;overflow:hidden;border:1px solid #315c75;border-radius:14px;background:linear-gradient(145deg,#102536f7,#061520f7 62%,#04101afa);box-shadow:0 18px 55px #0009;font-size:14px;container:rg-menu / inline-size}
.rg-expanded *{box-sizing:border-box}.rg-expanded button,.rg-expanded select{font:inherit;color:inherit;cursor:pointer;white-space:normal;line-height:1.3;text-transform:none;letter-spacing:normal}

.rg-expanded-brand{position:relative;display:flex;align-items:center;justify-content:space-between;gap:10px;flex:0 0 auto;min-height:0;margin:0;padding:8px 14px}
.rg-expanded-wordmark{display:flex;align-items:center;gap:8px;font-size:24px;font-weight:750;letter-spacing:-.4px;white-space:nowrap}.rg-expanded-wordmark img{width:31px;height:31px}
.rg-expanded-demo{display:flex;flex-direction:column;gap:2px;text-align:right;font-size:9px;color:#8fb3cc;line-height:1.25}.rg-expanded-demo-label{display:flex;align-items:center;justify-content:flex-end;gap:5px;color:#bdd8e9}.rg-expanded-demo-label i{width:5px;height:5px;background:#39d8ff;border-radius:50%}

.rg-expanded-tabs{position:relative;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));flex:0 0 auto;min-width:0;margin:0 12px;border:1px solid #28526d;border-radius:11px;overflow:hidden;background:#061a29b8}
.rg-expanded .rg-expanded-tab{position:relative;min-width:0;max-width:100%;width:100%;height:44px;min-height:0;margin:0;padding:4px 2px;border:0;border-bottom:3px solid transparent;border-radius:0;background:transparent;box-shadow:none;font-size:11px}
.rg-expanded-tab+.rg-expanded-tab:before{content:'';position:absolute;left:0;top:22%;height:56%;width:1px;background:#214258}
.rg-expanded-tab-body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}.rg-expanded-tab svg{width:18px;height:18px}
.rg-expanded-tab[aria-selected=true]{background:linear-gradient(0deg,#07506d72,transparent);border-bottom-color:#39d8ff;color:#55e0ff;box-shadow:inset 0 -6px 14px #1bc6ff10}

.rg-expanded-content{position:relative;flex:1 1 0;min-height:0;overflow:auto;overflow-x:hidden;margin:0;padding:9px 14px;scrollbar-color:#315f78 #061724;scrollbar-width:thin;scroll-padding-block:10px;overscroll-behavior:contain}
.rg-expanded h2{font-size:22px;line-height:1.2;margin:0 0 3px;letter-spacing:-.3px}.rg-expanded h3{font-size:18px;margin:0 0 10px}.rg-expanded-context{font-size:12px;line-height:1.35;color:#9fc3dc;margin:0 0 8px}

/* Quick already identifies itself in the selected tab. Remove the redundant root
   heading/subtitle, while retaining nested Quick detail headings. */
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page))>h2,
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page))>.rg-expanded-context{display:none}

.rg-expanded-grid{display:grid;grid-template-columns:repeat(var(--ec-columns),minmax(0,1fr));gap:8px;min-width:0;align-items:stretch}
.rg-expanded .rg-expanded-tile{position:relative;display:block;width:100%;min-width:0;max-width:100%;min-height:100px;height:auto;margin:0;padding:9px;border:1px solid #315f79;border-radius:11px;background:linear-gradient(150deg,#102b3d,#0a2030 58%,#071827);box-shadow:inset 0 1px 0 #ffffff08;text-align:left;overflow:hidden}
.rg-expanded-tile:before{content:'';position:absolute;top:0;right:0;width:55%;height:38%;background:linear-gradient(135deg,#39d8ff0b,transparent);clip-path:polygon(28% 0,100% 0,58% 100%,0 100%);pointer-events:none}
.rg-expanded-tile-body{position:relative;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;min-width:0;gap:5px;width:100%;height:auto}
.rg-expanded-tile-heading{display:flex;align-items:center;gap:5px;width:100%;min-width:0}.rg-expanded-tile-icon{position:static;display:flex;flex:0 0 auto;margin:0;color:#c4e7f8}.rg-expanded-tile-icon svg{width:20px;height:20px}
.rg-expanded-label{font-size:12px;font-weight:650;line-height:1.2;overflow-wrap:normal;word-break:normal}.rg-expanded-value{display:block;max-width:100%;font-size:16px;line-height:1.2;font-weight:750;overflow-wrap:normal;word-break:normal;hyphens:none}.rg-expanded-detail{display:block;padding-right:10px;font-size:10.5px;line-height:1.3;color:#9ec0d7;overflow-wrap:normal;word-break:normal}
.rg-expanded-chevron{position:absolute;right:0;bottom:-1px;font-size:22px;line-height:1;color:#d9f2ff}
.rg-expanded-tile[data-tone=active] .rg-expanded-value,.rg-expanded-tile[data-tone=active] .rg-expanded-tile-icon{color:#39d8ff}.rg-expanded-tile[data-ec-control=egpu] .rg-expanded-value{color:#49e6b1}
.rg-expanded-tile[data-tone=unavailable]{background:linear-gradient(150deg,#1a2c3a,#10202d);border-color:#38556a}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-value,.rg-expanded-tile[data-tone=unavailable] .rg-expanded-tile-icon{color:#9fb4c7}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-detail{color:#9eb2c4}
.rg-expanded-tile[data-ec-control=disconnect]{border-color:#9b7c3b;background:linear-gradient(145deg,#3e372414,#142635 50%,#091b2a)}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-body{padding:0;justify-content:flex-start;gap:5px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon{position:static;margin:0}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon svg{width:20px;height:20px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-label{font-size:12px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{display:flex;align-items:center;gap:4px;color:#ffc247;font-size:14px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:10.5px}

.rg-expanded button:hover{border-color:#75acc8}.rg-expanded button:focus,.rg-expanded button:focus-visible,.rg-expanded button.gpfocus{outline:2px solid #39d8ff!important;outline-offset:-2px;background:linear-gradient(145deg,#17445b,#09283c)!important;box-shadow:0 0 0 1px #39d8ff22,0 0 12px #39d8ff20!important;color:#f4f7fb!important}.rg-expanded-tab[aria-selected=true]:focus{border-bottom-color:#39d8ff;color:#55e0ff!important}

.rg-expanded-info{display:flex;align-items:center;gap:9px;padding:9px 10px;margin-top:9px;border:1px solid #294f68;border-radius:10px;background:#0b223180;color:#8fd5f0}.rg-expanded-info>span{min-width:0}.rg-expanded-info strong{display:block;font-size:11px;font-weight:600;color:#dbeef9;line-height:1.3}.rg-expanded-info small{display:block;margin-top:2px;font-size:9.5px;color:#91b7d1;line-height:1.3}.rg-expanded-badges{display:flex;flex-wrap:wrap;gap:5px;margin-left:auto}.rg-expanded-badges>span{display:flex;align-items:center;gap:4px;white-space:nowrap;font-size:9px;padding:4px 6px;border:1px solid #315c75;border-radius:14px;color:#b7d8ed;background:#061827}

.rg-expanded-footer{position:relative;display:flex;align-items:center;gap:8px;flex:0 0 auto;min-height:31px;margin:0;padding:5px 10px;border-top:1px solid #294f68;background:#061521;font-size:10px;white-space:nowrap}.rg-expanded-footer>span{display:inline-flex;align-items:center;gap:5px}.rg-expanded-footer-spacer{flex:1}.rg-expanded kbd{font:600 10px Arial,sans-serif;padding:1px 3px;border:1px solid #6099b8;border-radius:4px;background:linear-gradient(#20455b,#0a2538);box-shadow:inset 0 1px 0 #ffffff12;color:#e3f6ff}.rg-expanded kbd.rg-expanded-round{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;padding:0;color:#72e5ff}

.rg-expanded-back{padding:8px 12px;min-height:36px;border:1px solid #4f809c;border-radius:8px;background:#12364b}.rg-expanded-detail-page{padding:14px;background:#102b3e;border:1px solid #356683;border-radius:11px;line-height:1.45}.rg-expanded-detail-page p{color:#b1cfe3}.rg-expanded-settings-section{position:relative;padding:14px;border:1px solid #315c76;border-radius:11px;background:#0a2133;margin-bottom:12px}.rg-expanded-settings-list .rg-expanded-settings-section{padding:0;margin:0;background:none;border:0}.rg-expanded-settings-list .rg-expanded .rg-expanded-tile{height:100%}.rg-expanded-anchor{position:absolute;top:0;left:0;width:1px;height:1px;overflow:hidden;pointer-events:none}.rg-expanded-shortcut-control{max-width:280px}.rg-expanded-shortcut-select{max-width:100%;width:280px;padding:9px 12px;min-height:42px;background:#173b4d;border:1px solid #5097b4;border-radius:8px;color:#f4f7fb}.rg-expanded-shortcut-select:focus{outline:2px solid #39d8ff;outline-offset:2px}.rg-expanded-note{margin:12px 0 0}

/* The defining brightness/volume strip belongs to the Command Center body. It
   remains a sibling in the focus tree, but is visually contained inside the main
   panel so the central grid keeps its existing navigation contract. */
.rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{position:absolute;z-index:3;left:12px;top:94px;bottom:38px;width:clamp(68px,8.5vw,88px);max-height:none;overflow:hidden}
.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:calc(clamp(68px,8.5vw,88px) + 24px)}

/* Detached thumb rail: proportional width and action height, no extra title. */
.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{position:fixed;z-index:3;right:2vw;top:9vh;width:clamp(68px,8.5vw,94px);height:82vh;max-height:82vh;overflow:hidden;justify-content:center}

@container rg-menu (max-width:760px){
  .rg-expanded-brand{padding:7px 11px}.rg-expanded-wordmark{font-size:21px}.rg-expanded-wordmark img{width:28px;height:28px}.rg-expanded-demo{font-size:8px}
  .rg-expanded-tabs{margin:0 10px}.rg-expanded .rg-expanded-tab{height:41px;font-size:10px}.rg-expanded-tab svg{width:17px;height:17px}
  .rg-expanded-content{padding:7px 10px}.rg-expanded-grid{gap:6px}.rg-expanded .rg-expanded-tile{min-height:92px;padding:7px}.rg-expanded-label{font-size:11px}.rg-expanded-value{font-size:14px}.rg-expanded-detail{font-size:9.5px}
  .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{font-size:12px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:9.5px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{left:10px;top:86px;bottom:35px}
  .rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:calc(clamp(68px,8.5vw,88px) + 18px)}
}

@media(max-height:520px){
  .rg-expanded-backdrop{padding-block:6vh}.rg-expanded{height:88vh;max-height:88vh}.rg-expanded-frame{max-height:88vh}
  .rg-expanded-brand{padding:5px 10px}.rg-expanded-wordmark{font-size:19px}.rg-expanded-wordmark img{width:25px;height:25px}.rg-expanded-demo{font-size:7.5px}
  .rg-expanded .rg-expanded-tab{height:37px;font-size:9px}.rg-expanded-tab svg{width:15px;height:15px}.rg-expanded-content{padding-top:6px;padding-bottom:6px}
  .rg-expanded .rg-expanded-tile{min-height:78px;padding:6px}.rg-expanded-tile-icon svg{width:16px;height:16px}.rg-expanded-label{font-size:10px}.rg-expanded-value{font-size:12px}.rg-expanded-detail{font-size:8.5px;line-height:1.2}.rg-expanded-chevron{font-size:18px}
  .rg-expanded-info{padding:6px 8px;margin-top:6px}.rg-expanded-info small{font-size:8px}.rg-expanded-footer{min-height:27px;padding:3px 8px;font-size:9px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{top:73px;bottom:31px;width:66px;left:9px}
  .rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:80px}
  .rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{top:6vh;height:88vh;max-height:88vh;width:70px}
}

@media(max-width:760px){
  .rg-expanded-backdrop{padding-left:2vw}.rg-expanded{width:78vw}.rg-expanded-frame{max-width:98vw}.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{right:1.5vw}
}
@media(max-width:620px){
  .rg-expanded{width:80vw}.rg-expanded-frame>.rg-utility-rail[data-utility-side=right]{width:64px}.rg-expanded-frame>.rg-utility-rail[data-utility-side=left]{width:62px}.rg-expanded:has(.rg-expanded-tab[data-ec-tab=quick][aria-selected=true]) .rg-expanded-content:not(:has(.rg-expanded-detail-page)){padding-left:74px}
}
`;
