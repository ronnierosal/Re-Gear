import { forwardRef, type ReactNode } from "react";
import { Focusable } from "@decky/ui";

/** Informational controller stop, not an action or an invisible button. */
export const SectionFocus = forwardRef<HTMLDivElement, {
  label: string; children: ReactNode; onFocused?(): void;
}>(function SectionFocus({ label, children, onFocused }, ref) {
  return <Focusable ref={ref} role="group" aria-label={label}
    className="rg-section-focus" focusClassName="rg-section-focused"
    onGamepadFocus={(event) => {
      if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
      onFocused?.();
    }} style={{ minWidth: 0, borderRadius: 14, scrollMarginTop: 48, scrollMarginBottom: 16 }}>
    {children}
  </Focusable>;
});
