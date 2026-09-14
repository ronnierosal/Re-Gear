import type { ReactNode } from "react";

/** Shared layout; callers own the control, persistence and its error state. */
export function ShortcutSettings({ control, available = true, error, preview = false }: {
  control: ReactNode; available?: boolean; error?: string; preview?: boolean;
}) {
  return <section data-settings-section="shortcut" className="rg-expanded-settings-section">
    <span className="rg-expanded-anchor" tabIndex={-1} aria-label="Open Re-Gear section" />
    <h3>Menu shortcut</h3>
    <div data-ec-control="binding-menu" className="rg-expanded-shortcut-control">{control}</div>
    <p className="rg-expanded-context rg-expanded-note">{available
      ? "Press both buttons together. Release both before opening again."
      : "Controller shortcut input is unavailable."}</p>
    {error && <p role="alert">{error}</p>}
  </section>;
}
