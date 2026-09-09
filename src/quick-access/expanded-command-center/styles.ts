/** Scoped layout: native base buttons retain focus behavior, without Dialog styling. */
export const expandedStyles = `
.rg-expanded-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.44);z-index:10;display:flex;align-items:center;padding-left:2vw;color:#f4f7fb;font-family:Arial,sans-serif}
.rg-expanded{box-sizing:border-box;width:53vw;height:82vh;display:flex;flex-direction:column;min-width:0;border:1px solid #496379;border-radius:14px;background:linear-gradient(145deg,#112434fa,#05111bfa);box-shadow:0 16px 60px #0008;overflow:hidden;font-size:15px;container:rg-menu / inline-size}
.rg-expanded *{box-sizing:border-box}
.rg-expanded button{font:inherit;color:inherit;cursor:pointer;line-height:1.3;white-space:normal;text-transform:none;letter-spacing:normal}
.rg-expanded-brand{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 16px;font-size:26px;font-weight:700;flex-shrink:0}
.rg-expanded-demo{font-size:11px;line-height:1.3;color:#a9bdce;font-weight:400;text-align:right}
.rg-expanded .rg-expanded-tabs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;margin:0 12px;border-bottom:1px solid #294665;flex-shrink:0;min-width:0}
.rg-expanded .rg-expanded-tab{width:100%;min-width:0;max-width:100%;height:52px;min-height:0;margin:0;padding:4px 1px;display:block;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;font-size:12px;box-shadow:none}
.rg-expanded .rg-expanded-tab-body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;width:100%;white-space:nowrap}
.rg-expanded .rg-expanded-tab svg{width:20px;height:20px;flex-shrink:0}
.rg-expanded .rg-expanded-tab[aria-selected=true]{border-bottom-color:#39d8ff;color:#55ddff}
.rg-expanded-content{min-height:0;overflow-y:auto;overflow-x:hidden;flex:1;padding:10px 14px;scrollbar-color:#527087 #0a1725;scrollbar-width:thin}
.rg-expanded h2{margin:0 0 3px;font-size:24px;line-height:1.2}.rg-expanded h3{margin:0;font-size:18px}
.rg-expanded-context{margin:0 0 8px;color:#b1c9df;font-size:13px;line-height:1.35}
.rg-expanded .rg-expanded-grid{display:grid;grid-template-columns:repeat(var(--ec-columns),minmax(0,1fr));gap:10px;min-width:0}
.rg-expanded .rg-expanded-tile{width:100%;max-width:100%;min-width:0;height:auto;min-height:104px;margin:0;padding:12px;display:block;background:#102331;border:1px solid #365569;border-radius:11px;box-shadow:none;text-align:left;word-break:normal;overflow-wrap:normal}
.rg-expanded .rg-expanded-tile-body{display:flex;flex-direction:column;align-items:flex-start;gap:5px;width:100%;min-width:0;text-align:left}
.rg-expanded .rg-expanded-tile-heading{display:flex;align-items:center;gap:7px;width:100%;min-width:0}
.rg-expanded .rg-expanded-tile-heading svg{width:20px;height:20px;flex:0 0 20px}
.rg-expanded .rg-expanded-label{font-size:14px;font-weight:600;line-height:1.2}
.rg-expanded .rg-expanded-value{display:block;font-size:22px;font-weight:700;line-height:1.15;white-space:normal;word-break:normal;overflow-wrap:normal}
.rg-expanded .rg-expanded-detail{display:block;font-size:12px;line-height:1.3;color:#b1c9df;white-space:normal;word-break:normal;overflow-wrap:normal}
.rg-expanded .rg-expanded-tile[data-tone=active] .rg-expanded-value{color:#51dfff}
.rg-expanded .rg-expanded-tile[data-tone=warning]{min-height:88px}
.rg-expanded .rg-expanded-tile[data-tone=warning] .rg-expanded-value{color:#ffca62;font-size:18px}
.rg-expanded .rg-expanded-tile[data-tone=unavailable]{background:#142530}
.rg-expanded .rg-expanded-tile[data-tone=unavailable] .rg-expanded-value{color:#b9c4cf}
.rg-expanded button.gpfocus,.rg-expanded button:focus,.rg-expanded button:focus-visible{outline:2px solid #55ddff!important;outline-offset:-2px;color:#f4f7fb!important;background:#143044!important;box-shadow:0 0 9px #39d8ff35!important}
.rg-expanded-summary{margin-top:10px;color:#a9bdce;font-size:12px;line-height:1.35}
.rg-expanded-footer{display:flex;flex-wrap:nowrap;align-items:center;justify-content:space-between;gap:7px;border-top:1px solid #294665;padding:8px 12px;min-height:40px;flex-shrink:0;background:#071522;font-size:12px;white-space:nowrap}
.rg-expanded-footer>span{display:inline-flex;align-items:center;gap:4px;color:#b1c9df}
.rg-expanded kbd{font:600 11px Arial,sans-serif;border:1px solid #567082;border-radius:4px;padding:2px 4px;color:#e8f3fb;background:#182e3b}
.rg-expanded .rg-expanded-back{width:auto;min-width:0;margin:0;border:1px solid #4c6a81;border-radius:7px;background:#162e40;padding:7px 10px;min-height:32px}
.rg-expanded-detail-page{padding:12px;border:1px solid #365569;border-radius:11px;background:#102331;line-height:1.5;word-break:normal;overflow-wrap:normal}.rg-expanded-detail-page p{color:#b1c9df}
@container rg-menu (max-width:699px){
 .rg-expanded-brand{padding:7px 12px;font-size:22px}.rg-expanded-demo{font-size:10px}
 .rg-expanded .rg-expanded-tabs{margin:0 8px}.rg-expanded .rg-expanded-tab{height:48px;font-size:11px}
 .rg-expanded-content{padding:8px 10px}.rg-expanded h2{font-size:22px}.rg-expanded-context{font-size:12px;margin-bottom:7px}
 .rg-expanded .rg-expanded-grid{gap:8px}.rg-expanded .rg-expanded-tile{min-height:96px;padding:10px}
 .rg-expanded .rg-expanded-tile[data-tone=warning]{min-height:76px}
 .rg-expanded .rg-expanded-value{font-size:20px}.rg-expanded .rg-expanded-label{font-size:13px}
 .rg-expanded .rg-expanded-tile-body{gap:4px}.rg-expanded .rg-expanded-tile-heading{gap:6px}
 .rg-expanded .rg-expanded-tile-heading svg{width:18px;height:18px;flex-basis:18px}
 .rg-expanded-footer{min-height:36px;padding:6px 10px;font-size:11px;gap:5px}
}
@container rg-menu (max-width:470px){
 .rg-expanded .rg-expanded-tab{font-size:10px;height:44px}.rg-expanded .rg-expanded-tab svg{width:18px;height:18px}
 .rg-expanded-brand{font-size:20px}.rg-expanded-demo{font-size:9px}
 .rg-expanded .rg-expanded-value{font-size:18px}.rg-expanded .rg-expanded-label{font-size:12px}.rg-expanded .rg-expanded-detail{font-size:11px}
 .rg-expanded-footer{font-size:10px;padding:6px;gap:3px}.rg-expanded kbd{font-size:10px;padding:1px 3px}
}
@media(max-width:600px){.rg-expanded-backdrop{padding-left:3vw}.rg-expanded{width:94vw;height:90vh}}
@media(prefers-reduced-motion:no-preference){.rg-expanded-tab{transition:border-color .12s}}
`;
