import richTileSprite from "../../../../assets/command-center/tile-artwork.svg?rich-sprite";

const controlArtworkIds: Readonly<Record<string, string>> = {
  fps: "fps",
  manual: "manual-tdp",
  auto: "auto-tdp",
  display: "display",
  egpu: "egpu",
  controller: "controller",
  builtin: "controller",
  priority: "player-order",
  disconnect: "safe-disconnect",
  appearance: "settings",
  about: "about",
};

export const richTileArtworkStyles = `
.rg-rich-tile-sprite{position:absolute;width:0;height:0;overflow:hidden;pointer-events:none}
.rg-rich-tile-artwork{position:absolute;inset:0;display:block;pointer-events:none;overflow:hidden;border-radius:inherit}
.rg-rich-tile-artwork>svg{display:block;width:100%;height:100%}
.rg-rich-tile-artwork:after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,#071825f5 0%,#071825d9 44%,#07182524 76%,transparent 100%)}
.rg-expanded-tile[data-tone=unavailable] .rg-rich-tile-artwork{opacity:.5;filter:saturate(.45)}
@media(prefers-reduced-motion:reduce){.rg-rich-tile-artwork *{animation:none!important;transition:none!important}}
`;

export function RichTileSprite() {
  return <span className="rg-rich-tile-sprite" aria-hidden="true" dangerouslySetInnerHTML={{ __html: richTileSprite }}/>;
}

export function richTileArtworkId(controlId: string): string | undefined {
  return controlArtworkIds[controlId];
}

export function RichTileArtwork({ controlId }: { controlId: string }) {
  const artworkId = richTileArtworkId(controlId);
  if (!artworkId) return null;
  return <span className="rg-rich-tile-artwork" aria-hidden="true">
    <svg viewBox="0 0 180 180" focusable="false"><use href={`#rg-cc-tile-${artworkId}`}/></svg>
  </span>;
}
