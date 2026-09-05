export const regearTheme = {
  text: "#edf3f8",
  muted: "#b5c3d2",
  border: "#394653",
  surface: "linear-gradient(145deg, #18212c, #10171f)",
  accent: "#66d9f7",
  accentSoft: "#acebfa",
  activeSurface: "linear-gradient(145deg, #193542, #14242d)",
};

// Scoped to Re-Gear controls. Native Decky focus handling remains in charge.
export const regearControlCss = `
.rg-section-focus {
  min-width: 0;
  border-radius: 14px;
  scroll-margin-top: 48px;
  scroll-margin-bottom: 16px;
}
.rg-section-focus, .rg-section-focus.gpfocus, .rg-section-focus:focus-visible,
.rg-section-focus:focus-within {
  /* Informational navigation stops remain focusable but visually neutral. */
  background: transparent !important;
  outline: none !important;
  box-shadow: none !important;
}
.rg-dashboard-action:focus-visible, .rg-dashboard-action.gpfocus,
.gpfocus > .rg-dashboard-action {
  outline: 2px solid #66d9f7 !important;
  outline-offset: -3px;
  background: #213744 !important;
}
.rg-dashboard-action:disabled { opacity: .7; }
`;
