/** Shared browser/native presentation; state and launcher logic remain separate. */
export const expandedStyles = `
.rg-expanded-backdrop{position:fixed;inset:0;background:#0008;z-index:10;display:flex;align-items:center;padding-left:2vw;color:#f4f7fb;font-family:Arial,sans-serif}
.rg-expanded{box-sizing:border-box;width:62vw;max-width:1040px;height:92vh;display:flex;flex-direction:column;min-width:0;border:1px solid #467a9b;border-radius:18px;background:linear-gradient(155deg,#102d42fa,#051522 60%,#04101c);box-shadow:0 20px 60px #0009;overflow:hidden;font-size:14px;container:rg-menu / inline-size}
.rg-expanded *{box-sizing:border-box}.rg-expanded button,.rg-expanded select{font:inherit;color:inherit;cursor:pointer;white-space:normal;line-height:1.3;text-transform:none;letter-spacing:normal}
.rg-expanded-brand{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:16px 20px;flex-shrink:0}
.rg-expanded-wordmark{display:flex;align-items:center;gap:12px;font-size:29px;font-weight:750;letter-spacing:-.5px;white-space:nowrap}.rg-expanded-wordmark img{width:42px;height:42px}
.rg-expanded-demo{display:flex;flex-direction:column;gap:4px;text-align:right;font-size:11px;color:#91b3cd;line-height:1.3;text-transform:none;letter-spacing:normal}.rg-expanded-demo-label{display:flex;align-items:center;justify-content:flex-end;gap:6px;color:#bfdaec}.rg-expanded-demo-label i{width:5px;height:5px;background:#6cabc4;border-radius:50%}
.rg-expanded-tabs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:0 16px;border:1px solid #28526d;border-radius:12px;overflow:hidden;flex-shrink:0;background:#061a29}
.rg-expanded .rg-expanded-tab{position:relative;min-width:0;width:100%;height:68px;background:transparent;border:0;border-bottom:3px solid transparent;border-radius:0;padding:8px 3px;font-size:13px}
.rg-expanded-tab+.rg-expanded-tab:before{content:'';position:absolute;left:0;top:20%;height:60%;width:1px;background:#214258}
.rg-expanded-tab-body{display:flex;flex-direction:column;align-items:center;gap:6px}.rg-expanded-tab svg{width:28px;height:28px}
.rg-expanded-tab[aria-selected=true]{background:linear-gradient(0deg,#07506d88,transparent);border-bottom-color:#39d8ff;color:#55e0ff;box-shadow:inset 0 -7px 16px #1bc6ff12}
.rg-expanded-content{min-height:0;overflow:auto;overflow-x:hidden;flex:1;padding:16px 18px;scrollbar-color:#426f8a #061724;scrollbar-width:thin;scroll-padding-block:12px;overscroll-behavior:contain}
.rg-expanded h2{font-size:27px;line-height:1.15;margin:0 0 6px;letter-spacing:-.4px}.rg-expanded h3{font-size:18px;margin:0 0 10px}.rg-expanded-context{font-size:13px;line-height:1.4;color:#a8cbe5;margin:0 0 14px}
.rg-expanded-grid{display:grid;grid-template-columns:repeat(var(--ec-columns),minmax(0,1fr));gap:10px;min-width:0;align-items:stretch}
.rg-expanded .rg-expanded-tile{position:relative;min-width:0;max-width:100%;width:100%;min-height:150px;margin:0;padding:14px;height:auto;display:block;min-width:0;border:1px solid #326987;border-radius:13px;background:linear-gradient(145deg,#143850,#0a2237 48%,#071a2b);box-shadow:inset 0 1px 0 #ffffff08;text-align:left;overflow:hidden}
.rg-expanded-tile:before{content:'';position:absolute;top:0;right:0;width:60%;height:42%;background:linear-gradient(135deg,#2582ac10,#2582ac00);clip-path:polygon(30% 0,100% 0,55% 100%,0 100%);pointer-events:none}
.rg-expanded-tile-body{position:relative;display:flex;flex-direction:column;align-items:flex-start;min-width:0;gap:5px;width:100%;height:100%}.rg-expanded-tile-icon{display:flex;color:#c4e7f8;margin-bottom:4px}.rg-expanded-tile-icon svg{width:34px;height:34px}
.rg-expanded-value{display:block;font-size:20px;line-height:1.2;font-weight:750;overflow-wrap:break-word;max-width:100%}.rg-expanded-label{font-size:14px;font-weight:600;line-height:1.25}.rg-expanded-detail{display:block;font-size:12px;line-height:1.4;color:#a4c8df;padding-right:10px;overflow-wrap:break-word}
.rg-expanded-chevron{position:absolute;right:0;bottom:0;font-size:25px;color:#d9f2ff;line-height:1}
.rg-expanded-tile[data-tone=active] .rg-expanded-value,.rg-expanded-tile[data-tone=active] .rg-expanded-tile-icon{color:#39d8ff}
.rg-expanded-tile[data-ec-control=egpu] .rg-expanded-value{color:#49e6b1}
.rg-expanded-tile[data-tone=unavailable]{background:linear-gradient(145deg,#263748,#152534);border-color:#456077}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-value,.rg-expanded-tile[data-tone=unavailable] .rg-expanded-tile-icon{color:#a0b3c8}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-detail{color:#afc2d6}
.rg-expanded-tile[data-ec-control=disconnect]{border-color:#bc913c;background:linear-gradient(145deg,#3e372420,#172735 45%,#0a1c2b)}
.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-body{padding-left:45px;justify-content:center;gap:9px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon{position:absolute;left:0;top:8px;color:#dae7f0}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon svg{width:38px;height:38px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-label{font-size:17px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{display:flex;align-items:center;gap:6px;color:#ffc247;font-size:16px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:13px}
.rg-expanded button:hover{border-color:#75acc8}.rg-expanded button:focus,.rg-expanded button:focus-visible,.rg-expanded button.gpfocus{outline:2px solid #39d8ff!important;outline-offset:-2px;background:linear-gradient(145deg,#1b4961,#0a2c41)!important;box-shadow:0 0 0 1px #39d8ff33,0 0 14px #39d8ff2e!important;color:#f4f7fb!important}
.rg-expanded-tab[aria-selected=true]:focus{border-bottom-color:#39d8ff;color:#55e0ff!important}
.rg-expanded-info{display:flex;align-items:center;gap:10px;padding:12px 13px;margin-top:14px;border:1px solid #294f68;border-radius:12px;background:linear-gradient(125deg,#102b3c80,#061c2b80);color:#8fd5f0}.rg-expanded-info>span{min-width:0}.rg-expanded-info strong{display:block;font-size:12px;font-weight:600;color:#dbeef9;line-height:1.4}.rg-expanded-info small{display:block;margin-top:4px;font-size:11px;color:#91b7d1;line-height:1.4}.rg-expanded-badges{display:flex;flex-wrap:wrap;gap:6px;margin-left:auto}.rg-expanded-badges>span{display:flex;align-items:center;gap:5px;white-space:nowrap;font-size:10px;padding:6px 8px;border:1px solid #315c75;border-radius:18px;color:#b7d8ed;background:#061827}
.rg-expanded-footer{display:flex;align-items:center;gap:16px;min-height:45px;flex-shrink:0;background:#061521;border-top:1px solid #294f68;padding:9px 16px;font-size:12px;white-space:nowrap}.rg-expanded-footer>span{display:inline-flex;align-items:center;gap:6px}.rg-expanded-footer-spacer{flex:1}.rg-expanded kbd{font:600 11px Arial,sans-serif;padding:3px 5px;border:1px solid #6099b8;border-radius:4px;background:linear-gradient(#20455b,#0a2538);box-shadow:inset 0 1px 0 #ffffff12;color:#e3f6ff}.rg-expanded kbd.rg-expanded-round{display:inline-grid;place-items:center;width:23px;height:23px;border-radius:50%;padding:0;color:#72e5ff}
.rg-expanded-back{padding:8px 12px;min-height:36px;border:1px solid #4f809c;border-radius:8px;background:#12364b}.rg-expanded-detail-page{padding:18px;background:#102b3e;border:1px solid #356683;border-radius:12px;line-height:1.5}.rg-expanded-detail-page p{color:#b1cfe3}
.rg-expanded-settings-section{position:relative;padding:16px;border:1px solid #315c76;border-radius:12px;background:#0a2133;margin-bottom:14px}.rg-expanded-settings-list .rg-expanded-settings-section{padding:0;margin:0;background:none;border:0}.rg-expanded-settings-list .rg-expanded .rg-expanded-tile{height:100%}.rg-expanded-anchor{position:absolute;top:0;left:0;width:1px;height:1px;overflow:hidden;pointer-events:none}.rg-expanded-shortcut-control{max-width:280px}.rg-expanded-shortcut-select{max-width:100%;width:280px;padding:9px 12px;min-height:42px;background:#173b4d;border:1px solid #5097b4;border-radius:8px;color:#f4f7fb}.rg-expanded-shortcut-select:focus{outline:2px solid #39d8ff;outline-offset:2px}.rg-expanded-note{margin:12px 0 0}
@container rg-menu (max-width:650px){.rg-expanded-brand{padding:12px 15px}.rg-expanded-wordmark{font-size:25px}.rg-expanded-wordmark img{width:36px;height:36px}.rg-expanded-demo{font-size:10px}.rg-expanded-tabs{margin:0 12px}.rg-expanded .rg-expanded-tab{font-size:12px;height:61px}.rg-expanded-tab svg{width:26px;height:26px}.rg-expanded-content{padding:14px}.rg-expanded h2{font-size:25px}.rg-expanded .rg-expanded-tile{padding:12px;min-height:150px}.rg-expanded-value{font-size:18px}.rg-expanded-info{flex-wrap:wrap}.rg-expanded-badges{margin-left:32px}.rg-expanded-footer{font-size:11px;padding:8px 12px}}
@media(max-width:700px){.rg-expanded{width:94vw;height:94vh}.rg-expanded-backdrop{padding-left:3vw}}
@container rg-menu (max-width:380px){.rg-expanded-demo{max-width:120px;font-size:9px}.rg-expanded-wordmark{font-size:22px;gap:6px}.rg-expanded-wordmark img{width:30px;height:30px}.rg-expanded .rg-expanded-tab{font-size:10px}.rg-expanded-tab svg{width:24px;height:24px}.rg-expanded-footer{font-size:10px;gap:8px;padding:8px}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-body{padding-left:0}.rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon{position:static}}

/* Compact approved hierarchy. Scope resets against native button/Focusable styles;
   do not let the host's flex basis or minimum height overlap menu regions. */
.rg-expanded-backdrop{padding-block:9vh;box-sizing:border-box}
.rg-expanded{width:53vw;height:82vh;max-height:100%;border-radius:14px;background:linear-gradient(145deg,#112434fa,#05111bfa)}
.rg-expanded .rg-expanded-brand{position:relative;flex:0 0 auto;min-height:0;margin:0;padding:8px 12px;gap:8px}
.rg-expanded .rg-expanded-wordmark{font-size:24px;gap:8px}.rg-expanded .rg-expanded-wordmark img{width:30px;height:30px}
.rg-expanded .rg-expanded-tabs{position:relative;flex:0 0 auto;min-height:0;min-width:0;margin:0 12px}
.rg-expanded .rg-expanded-tab{min-height:0;max-width:100%;height:44px;margin:0;padding:4px 1px;display:block;box-shadow:none;font-size:11px}
.rg-expanded .rg-expanded-tab-body{justify-content:center;gap:3px}.rg-expanded .rg-expanded-tab svg{width:18px;height:18px}
.rg-expanded .rg-expanded-content{position:relative;flex:1 1 0;min-height:0;margin:0;padding:8px 12px}
.rg-expanded h2{font-size:22px;margin:0 0 3px;line-height:1.2}.rg-expanded .rg-expanded-context{margin:0 0 8px;font-size:12px}
.rg-expanded .rg-expanded-grid{gap:7px}
.rg-expanded .rg-expanded-tile{min-height:96px;padding:8px;display:block;border-radius:11px;background:#102331}
.rg-expanded .rg-expanded-tile-body{gap:5px;height:auto;padding:0;justify-content:flex-start}
.rg-expanded .rg-expanded-tile-heading{display:flex;align-items:center;gap:5px;width:100%;min-width:0}
.rg-expanded .rg-expanded-tile-icon{position:static;margin:0;flex:0 0 auto}
.rg-expanded .rg-expanded-tile-icon svg{width:20px;height:20px}
.rg-expanded .rg-expanded-label{font-size:12px;line-height:1.2;overflow-wrap:normal;word-break:normal}
.rg-expanded .rg-expanded-value{font-size:16px;line-height:1.25;overflow-wrap:normal;word-break:normal;hyphens:none}
.rg-expanded .rg-expanded-detail{font-size:11px;line-height:1.3;overflow-wrap:normal;word-break:normal}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{font-size:14px;display:flex;gap:4px}
.rg-expanded .rg-expanded-footer{position:relative;flex:0 0 auto;min-height:30px;margin:0;padding:5px 10px;font-size:10px;gap:8px}
.rg-expanded .rg-expanded-footer kbd{font-size:10px;padding:1px 3px}.rg-expanded .rg-expanded-footer kbd.rg-expanded-round{width:18px;height:18px}
@container rg-menu (max-width:599px){
.rg-expanded .rg-expanded-brand{padding:7px 10px}.rg-expanded .rg-expanded-wordmark{font-size:21px}.rg-expanded .rg-expanded-demo{font-size:9px}
.rg-expanded .rg-expanded-tile{padding:6px;min-height:88px}.rg-expanded .rg-expanded-tile-icon svg{width:14px;height:14px}
.rg-expanded .rg-expanded-label{font-size:10px}.rg-expanded .rg-expanded-value{font-size:12px}.rg-expanded .rg-expanded-detail{font-size:10px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-value{font-size:12px}
}
@media(max-width:600px){.rg-expanded{width:94vw;height:82vh}}

.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-body{padding:0;justify-content:flex-start;gap:5px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon{position:static;margin:0}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon svg{width:20px;height:20px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-label{font-size:12px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:11px}
@container rg-menu (max-width:599px){
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-tile-icon svg{width:14px;height:14px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-label{font-size:10px}
.rg-expanded .rg-expanded-tile[data-ec-control=disconnect] .rg-expanded-detail{font-size:10px}
}
`;
