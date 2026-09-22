import fpsArtwork from "../../../../assets/command-center/v3/tiles/fps.svg?v3-tile";
import safeDisconnectArtwork from "../../../../assets/command-center/v3/tiles/safe-disconnect.svg?v3-tile";

const proofArtwork: Readonly<Record<string, string>> = {
  fps: fpsArtwork,
  disconnect: safeDisconnectArtwork,
};

export function V3TileArtwork({ controlId }: { controlId: string }) {
  const src = proofArtwork[controlId];
  return src ? <img className="rg-v3-tile-artwork" src={src} alt="" aria-hidden="true"/> : null;
}
