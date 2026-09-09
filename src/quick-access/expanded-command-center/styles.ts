/** Scoped prototype styling. Never targets Steam or Decky containers. */
export const expandedStyles = `
.rg-expanded-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.44);z-index:10;display:flex;align-items:center;padding-left:2vw;color:#f4f7fb;font-family:Arial,sans-serif}
.rg-expanded{box-sizing:border-box;width:53vw;height:82vh;display:flex;flex-direction:column;min-width:0;border:1px solid #496379;border-radius:18px;background:linear-gradient(145deg,rgba(17,36,52,.98),rgba(5,17,27,.98));box-shadow:0 16px 60px #0008;overflow:hidden;font-size:15px}
.rg-expanded *{box-sizing:border-box}
.rg-expanded{container-type:inline-size;container-name:rg-menu}
.rg-expanded button,.rg-expanded [role=button]{min-width:0;width:auto;margin:0;line-height:1.3}
.rg-expanded .gpfocus,.rg-expanded .gpfocuswithin,.rg-expanded button:focus{outline:2px solid #83e8ff;outline-offset:-3px}
.rg-expanded button{font:inherit;color:inherit;cursor:pointer}
.rg-expanded button:focus-visible{outline:3px solid #83e8ff;outline-offset:-4px;box-shadow:inset 0 0 18px #39d8ff25}
.rg-expanded-brand{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:15px 22px 12px;font-size:22px;font-weight:700}
.rg-expanded-demo{font-size:12px;color:#b5c9dd;font-weight:400;text-align:right}
.rg-expanded-tabs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:0 14px;border:1px solid #294665;border-radius:12px;overflow:hidden;flex-shrink:0}
.rg-expanded-tab{min-width:0;min-height:74px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:8px 2px;border:0;border-bottom:4px solid transparent;background:#0a1725;font-size:13px!important;overflow-wrap:anywhere}
.rg-expanded-tab[aria-selected=true]{border-bottom-color:#39d8ff;background:#153446;color:#55ddff}
.rg-expanded-content{min-height:0;overflow-y:auto;overflow-x:hidden;flex:1;padding:18px 22px;scrollbar-color:#527087 #0a1725;scrollbar-width:thin}
.rg-expanded h2{margin:0 0 5px;font-size:25px}.rg-expanded h3{margin:0;font-size:18px}
.rg-expanded-context{margin:0 0 17px;color:#b1c9df;font-size:14px;line-height:1.45}
.rg-expanded-grid{display:grid;grid-template-columns:repeat(var(--ec-columns),minmax(0,1fr));gap:12px}
.rg-expanded-tile{background:linear-gradient(130deg,#1c3343,#102331);border:1px solid #365569;border-radius:13px;min-width:0;min-height:132px;padding:16px;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-start;gap:9px;text-align:left;overflow-wrap:anywhere}
.rg-expanded-tile svg{flex-shrink:0}
.rg-expanded-label{font-size:15px;font-weight:700}.rg-expanded-value{font-size:20px;font-weight:700;line-height:1.2}.rg-expanded-detail{font-size:13px;line-height:1.45;color:#b1c9df}
.rg-expanded-tile[data-tone=active] .rg-expanded-value{color:#51dfff}
.rg-expanded-tile[data-tone=warning] .rg-expanded-value{color:#ffca62;font-size:18px}
.rg-expanded-tile[data-tone=unavailable]{background:#1a2935}.rg-expanded-tile[data-tone=unavailable] .rg-expanded-value{color:#b9c4cf}
.rg-expanded-summary{border-top:1px solid #294665;margin-top:16px;padding-top:12px;color:#b1c9df;font-size:13px;line-height:1.5}
.rg-expanded-footer{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;border-top:1px solid #294665;padding:12px 18px;flex-shrink:0;background:#071522;font-size:12px}
.rg-expanded-footer button,.rg-expanded-back{border:1px solid #4c6a81;border-radius:7px;background:#162e40;padding:7px 10px;min-height:36px}
.rg-expanded-footer span{color:#b1c9df}
.rg-expanded-detail-page{padding:18px;border:1px solid #365569;border-radius:12px;background:#102331;line-height:1.6;overflow-wrap:anywhere}.rg-expanded-detail-page p{color:#b1c9df}.rg-expanded-detail-page strong{color:#f4f7fb}
@media(max-width:1100px){.rg-expanded-brand{padding:10px 16px;font-size:19px}.rg-expanded-content{padding:14px}.rg-expanded-tabs{margin:0 10px}.rg-expanded-tab{font-size:12px!important;min-height:64px}.rg-expanded-tile{padding:12px;gap:7px}.rg-expanded h2{font-size:22px}.rg-expanded-value{font-size:18px}}
@media(max-height:800px) and (min-width:801px){.rg-expanded-brand{padding:10px 16px;font-size:19px}.rg-expanded-tab{min-height:60px;padding:5px 2px;font-size:12px!important}.rg-expanded-tab svg{width:26px;height:26px}.rg-expanded-content{padding:12px 16px}.rg-expanded h2{font-size:22px}.rg-expanded-context{margin-bottom:10px;font-size:13px}.rg-expanded-tile{padding:10px;gap:5px;min-height:132px}.rg-expanded-tile svg{width:26px;height:26px}.rg-expanded-label{font-size:14px}.rg-expanded-value{font-size:18px}.rg-expanded-detail{font-size:12px}.rg-expanded-summary{margin-top:8px;padding-top:8px;font-size:12px}.rg-expanded-footer{padding:9px 14px;gap:8px}}
@media(max-width:800px){.rg-expanded-backdrop{padding-left:3vw}.rg-expanded{width:94vw;height:90vh}.rg-expanded-brand{font-size:18px}.rg-expanded-footer{gap:6px;padding:8px}.rg-expanded-tab{font-size:11px!important}.rg-expanded-label{font-size:14px}.rg-expanded-content{padding:12px}}
@media(prefers-reduced-motion:no-preference){.rg-expanded-tab{transition:background .12s}}
@container rg-menu (max-width:600px){
 .rg-expanded-brand{padding:7px 12px;font-size:17px}.rg-expanded-demo{font-size:10px}
 .rg-expanded-tabs{margin:0 8px}.rg-expanded-tab{min-height:46px;padding:4px 1px;font-size:10px!important;gap:3px}
 .rg-expanded-tab svg{width:18px;height:18px}
 .rg-expanded-content{padding:10px}.rg-expanded h2{font-size:18px}.rg-expanded-context{font-size:11px;margin-bottom:8px}
 .rg-expanded-grid{gap:7px}.rg-expanded-tile{min-height:98px;padding:8px;gap:4px}
 .rg-expanded-tile svg{width:18px;height:18px}.rg-expanded-label{font-size:12px}.rg-expanded-value{font-size:15px}.rg-expanded-detail{font-size:11px}
 .rg-expanded-tile[data-tone=warning] .rg-expanded-value{font-size:14px}.rg-expanded-summary{font-size:11px;margin-top:7px;padding-top:7px}
 .rg-expanded-footer{padding:6px 9px;gap:5px 8px;font-size:10px}.rg-expanded-footer button{min-height:28px;padding:4px 7px}
}
`;
