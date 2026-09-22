/** Make an approved V3 tile self-contained without changing its source artwork. */
export function composeV3TileArtwork(tileArtwork, buttonArtwork, expectedId) {
  const reference = /href="\.\.\/button-artwork\.svg#([^"]+)"/.exec(tileArtwork);
  if (!reference) throw new Error("V3 tile has no approved button-artwork reference");
  const iconId = reference[1];
  if (expectedId && iconId !== expectedId) {
    throw new Error(`V3 tile ${expectedId} references ${iconId}`);
  }
  const escaped = iconId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const symbol = new RegExp(`<symbol\\s+id="${escaped}"[\\s\\S]*?<\\/symbol>`).exec(buttonArtwork)?.[0];
  if (!symbol) throw new Error(`button-artwork.svg has no ${iconId} symbol`);
  const style = /<style>[\s\S]*?<\/style>/.exec(buttonArtwork)?.[0] ?? "";
  return tileArtwork
    .replace("</defs>", `${style}${symbol}</defs>`)
    .replaceAll(`href="../button-artwork.svg#${iconId}"`, `href="#${iconId}"`);
}
