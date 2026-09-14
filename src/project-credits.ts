/** Maintained presentation index for THIRD_PARTY_NOTICES.md. That file retains
 * the full attribution, pinned revisions and license text. Update both when a
 * delivered contribution changes; UI components must not maintain another list. */
export const noticesUrl='https://github.com/ronnierosal/Re-Gear/blob/main/THIRD_PARTY_NOTICES.md';
export const projectCredits=[
 {project:'eGPUBridge',attribution:'Vova + GPT',source:'https://github.com/ronnierosal/eGPUBridge',notice:noticesUrl},
 {project:'Storage Cleaner',attribution:'mcarlucci and contributors',source:'https://github.com/mcarlucci/decky-storage-cleaner',notice:noticesUrl+'#steam-app-details-request-helper'},
 {project:'Gamescope',attribution:'Valve',source:'https://github.com/ValveSoftware/gamescope',notice:noticesUrl+'#gamescope-performance-protocol'},
 {project:'SteamTracking',attribution:'SteamDB contributors',source:'https://github.com/SteamDatabase/SteamTracking',notice:noticesUrl+'#native-brightness-and-volume-api-contract'},
 {project:'Decky Loader / UI',attribution:'SteamDeckHomebrew contributors',source:'https://github.com/SteamDeckHomebrew/decky-frontend-lib',notice:noticesUrl+'#native-brightness-and-volume-api-contract'},
] as const;
