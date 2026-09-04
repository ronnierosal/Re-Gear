import { callable } from "@decky/api";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, Router } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { OfflineDetailsSession } from "./offline-details-session";
import { offlineGameChoices, offlineNativeSource } from "./offline-native-source";
import { offlineReadinessDetail } from "./offline-readiness-detail";

const classify = callable<[Record<string, number | boolean>], { reason_codes?: unknown }>("classify_offline_details");

export function OfflineReadinessPanel({ gameState, visible }: { gameState: string; visible: boolean }) {
  const session = useRef(new OfflineDetailsSession());
  const current = useRef({ gameState, visible, selected: 0 });
  current.current.gameState = gameState;
  current.current.visible = visible;
  const [games, setGames] = useState<Array<{ data: number; label: string }>>([]);
  const [selected, setSelected] = useState(0);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const librarySource = useRef<unknown>(undefined);
  const displayContext = useRef<(() => boolean) | undefined>(undefined);
  const expiry = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const clear = () => {
    sequence.current++;
    session.current.invalidate();
    clearTimeout(expiry.current);
    displayContext.current = undefined;
    setMessage("");
    setBusy(false);
  };
  useEffect(() => {
    clear();
    return () => { sequence.current++; session.current.invalidate(); clearTimeout(expiry.current); };
  }, [gameState, visible]);
  // Reuse existing panel refreshes. No new library polling or session hook.
  useEffect(() => {
    try {
      if (librarySource.current && librarySource.current !== (window.appStore as unknown)) {
        librarySource.current = undefined;
        setGames([]); setSelected(0); current.current.selected = 0; clear();
      } else if (displayContext.current && !displayContext.current()) clear();
    } catch { clear(); }
  });

  const load = () => {
    clear();
    setGames([]); setSelected(0); current.current.selected = 0;
    librarySource.current = undefined;
    try {
      const source = offlineNativeSource();
      const choices = source ? offlineGameChoices(source) : [];
      librarySource.current = source?.store;
      setGames(choices);
      setSelected(choices[0]?.data ?? 0);
      current.current.selected = choices[0]?.data ?? 0;
      if (!choices.length) setMessage("Steam's installed games are unavailable. Try again from your library.");
    } catch { setMessage("Steam's installed games are unavailable. Try again from your library."); }
  };
  const check = async () => {
    clear();
    const request = sequence.current;
    setBusy(true);
    try {
      const source = offlineNativeSource();
      const app = source?.store.GetAppOverviewByAppID(selected);
      if (!source || !app) throw new Error();
      const matches = () => current.current.visible && current.current.gameState === "idle" &&
        current.current.selected === selected && (window.appStore as unknown) === source.store &&
        source.store.GetAppOverviewByAppID(selected) === app &&
        app.display_status !== 4 && Array.isArray(Router.RunningApps) && Router.RunningApps.length === 0;
      const report = await session.current.request(selected, source.subscribe, matches);
      if (!report) throw new Error();
      const result = await classify(report.details);
      if (request !== sequence.current) return;
      if (!report.isValid()) { setMessage("The game context changed or the check expired. Try again."); return; }
      displayContext.current = matches;
      setMessage(offlineReadinessDetail(result.reason_codes) ?? "Steam could not confirm this game's offline requirements.");
      expiry.current = setTimeout(() => {
        if (request === sequence.current) setMessage("This report has expired. Check the game again.");
      }, 30000);
    } catch {
      if (request === sequence.current) setMessage("The check is unavailable. Close any running game and try again.");
    } finally {
      if (request === sequence.current) setBusy(false);
    }
  };
  return <PanelSection title="Offline readiness">
    <PanelSectionRow>Check Steam's report before leaving Wi-Fi. Offline play is not guaranteed.</PanelSectionRow>
    <ButtonItem disabled={busy || gameState !== "idle"} onClick={load}>Choose an installed game</ButtonItem>
    {!!games.length && <>
      <DropdownItem label="Game" rgOptions={games} selectedOption={selected} onChange={(option) => {
        clear(); setSelected(option.data); current.current.selected = option.data;
      }} />
      <ButtonItem disabled={busy || gameState !== "idle" || !visible} onClick={() => void check()}>{busy ? "Checking…" : "Check this game"}</ButtonItem>
      <PanelSectionRow>Shows installed games from up to 256 cached library entries. Results describe Steam's report at check time.</PanelSectionRow>
    </>}
    {!!message && <PanelSectionRow>{message}</PanelSectionRow>}
  </PanelSection>;
}
