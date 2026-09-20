const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function composeCommandCenterArtwork(tileArtwork, buttonArtwork, prefix = "rg-cc-") {
  const buttonDefinitions = buttonArtwork.match(/<defs>([\s\S]*?)<\/defs>/)?.[1];
  if (!buttonDefinitions) throw new Error("button-artwork.svg has no defs block");

  let sprite = tileArtwork
    .replace("<defs>", `<defs>${buttonDefinitions}`)
    .replaceAll('href="button-artwork.svg#', 'href="#');

  const ids = new Set([...sprite.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  for (const id of ids) {
    const escaped = escapeRegExp(id);
    sprite = sprite
      .replace(new RegExp(`\\bid="${escaped}"`, "g"), `id="${prefix}${id}"`)
      .replace(new RegExp(`\\bhref="#${escaped}"`, "g"), `href="#${prefix}${id}"`)
      .replace(new RegExp(`url\\(#${escaped}\\)`, "g"), `url(#${prefix}${id})`);
  }

  const classes = new Set(
    [...sprite.matchAll(/\bclass="([^"]+)"/g)].flatMap(match => match[1].trim().split(/\s+/)),
  );
  for (const className of classes) {
    if (!className) continue;
    const escaped = escapeRegExp(className);
    sprite = sprite
      .replace(new RegExp(`(\\bclass="[^"]*)\\b${escaped}\\b`, "g"), `$1${prefix}${className}`)
      .replace(new RegExp(`\\.${escaped}(?=[\\s,{.:#>+~[])`, "g"), `.${prefix}${className}`);
  }

  return sprite;
}
