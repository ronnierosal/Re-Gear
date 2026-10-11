import { Field, GamepadButton, scrollPanelClasses } from "@decky/ui";
import type { ReactNode } from "react";

// Decky resolves these names from the current Steam build. Never target guessed
// Steam hashes or unrelated scroll areas. Keep the native scrolling mechanism.
const nativeScrollSelectors = Object.values(scrollPanelClasses ?? {})
  .flatMap(value => value.split(/\s+/))
  .filter(value => /^[a-zA-Z_][\w-]*$/.test(value)).map(value => `.${value}`);
const scrollSelector = [".rg-expanded-content", "[data-regear-popup-body]", ...nativeScrollSelectors].join(",");

/** Styles exist only while a reading is mounted; :has scopes chrome to its host.
 * Native scrollbar arrows are scrollbar pseudo-elements, never action buttons.
 * Warning panels inside the labeled group retain their own meaningful paint. */
export function ReadingChrome() {
  const hosts = scrollSelector.split(",").map(selector => `${selector}:has(.rg-readable,.rg-egpu-reading)`);
  return <style>{`
.rg-readable,.rg-egpu-reading,.rg-readable.gpfocus,.rg-egpu-reading.gpfocus,
.rg-readable:focus-visible,.rg-egpu-reading:focus-visible,.rg-readable:focus-within,.rg-egpu-reading:focus-within{
background:transparent!important;outline:none!important;box-shadow:none!important}
${hosts.join(",")}{scrollbar-width:none!important}
${hosts.map(selector => `${selector}::-webkit-scrollbar`).join(",")}{display:none!important;width:0!important;height:0!important}
${hosts.map(selector => `${selector}::-webkit-scrollbar-button`).join(",")}{display:none!important}
`}</style>;
}

/** Reveal information with the smallest scroll; never focus or activate an action. */
export function revealReadable(target: HTMLElement) {
  const area = target.closest<HTMLElement>(scrollSelector);
  if (!area) { target.scrollIntoView({ block: "nearest", inline: "nearest" }); return; }
  const box = area.getBoundingClientRect(), row = target.getBoundingClientRect();
  if (row.height > box.height && row.bottom > box.top && row.top < box.bottom) return;
  if (row.top < box.top) area.scrollTop += row.top - box.top;
  else if (row.bottom > box.bottom) area.scrollTop += row.height > box.height ? row.top - box.top : row.bottom - box.bottom;
}

/** A paragraph group can exceed the viewport. Read it in steps, then let normal
 * spatial navigation continue at either edge. No A/B/click handlers exist. */
export function scrollReadable(target: HTMLElement, direction: "up" | "down") {
  const area = target.closest<HTMLElement>(scrollSelector);
  if (!area) return false;
  const box = area.getBoundingClientRect(), row = target.getBoundingClientRect();
  if (box.height <= 0) return false;
  const remaining = direction === "down" ? row.bottom - box.bottom : box.top - row.top;
  if (row.height > box.height && remaining > 2) {
    area.scrollTop += (direction === "down" ? 1 : -1) * Math.min(remaining, box.height * .65);
    return true;
  }
  // Nearest row reveal can leave its preceding section title just out of view.
  // At the first reading's upper edge, reveal that context before spatial exit.
  if (direction === "up" && area.scrollTop > 0 && row.top >= box.top - 2 &&
      area.querySelector(".rg-readable,.rg-egpu-reading") === target) {
    area.scrollTop = Math.max(0, area.scrollTop - box.height * .65);
    return true;
  }
  return false;
}

export function ReadableBlock({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <Field focusable highlightOnFocus={false} padding="none" bottomSeparator="none" childrenLayout="below"
    className={`rg-readable ${className}`} data-rg-readable aria-label={label}
    onGamepadFocus={(event: Event) => { if (event.currentTarget instanceof HTMLElement) revealReadable(event.currentTarget); }}
    onGamepadDirection={(event: CustomEvent<{ button: number }>) => {
      const direction = event.detail.button === GamepadButton.DIR_UP ? "up" : event.detail.button === GamepadButton.DIR_DOWN ? "down" : null;
      if (!direction || !(event.currentTarget instanceof HTMLElement) || !scrollReadable(event.currentTarget, direction)) return false;
      event.preventDefault(); event.stopPropagation(); return true;
    }}>
    <ReadingChrome />
    <div role="group" aria-label={label}>{children}</div>
  </Field>;
}
