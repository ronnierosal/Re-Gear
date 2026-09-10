import type { ReactNode } from "react";

/** Shared layout; callers own the control, persistence and its error state. */
export function ShortcutSettings({ control, available = true, error, preview = false }: {
  control: ReactNode; available?: boolean; error?: string; preview?: boolean;
}) {
  return <section data-settings-section="shortcut" className="rg-expanded-settings-section">
    <span className="rg-expanded-anchor" tabIndex={-1} aria-label="Open Re-Gear section" />
    <h3>Open Re-Gear</h3>
    <p className="rg-expanded-context">Choose your menu shortcut</p>
    <div data-ec-control="binding-menu" className="rg-expanded-shortcut-control">{control}</div>
    <p className="rg-expanded-context rg-expanded-note">{available
      ? "Press both buttons together. Release both before opening again."
      : "Controller input is unavailable. Use the Open expanded demo button in Quick Access."}</p>
    {!preview && <p className="rg-expanded-context rg-expanded-note">Saved on this Steam client. Steam or the game may also respond to these buttons.</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
