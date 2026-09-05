import { forwardRef, type ReactNode } from "react";
import { Field } from "@decky/ui";

/** Informational controller stop, not an action or an invisible button. */
export const SectionFocus = forwardRef<HTMLDivElement, {
  label: string; children: ReactNode; onFocused?(): void;
}>(function SectionFocus({ label, children, onFocused }, ref) {
  // Generic Focusable containers can route to children without becoming a
  // selectable leaf. Field explicitly registers this read-only focus stop.
  return <Field ref={ref} focusable={true} highlightOnFocus={true}
    padding="none" bottomSeparator="none" childrenLayout="below"
    className="rg-section-focus"
    onGamepadFocus={(event) => {
      if (event.currentTarget instanceof HTMLElement) {
        event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
      onFocused?.();
    }}>
    <div role="group" aria-label={label} style={{ minWidth: 0, width: "100%" }}>
      {children}
    </div>
  </Field>;
});
