# Manual installation from a GitHub release

**Audience:** prospective users and coordinated testers<br>
**Reviewed:** 2026-09-08<br>
**Availability:** no public supported Re-Gear release yet

Re-Gear does not currently have a public supported release or a Decky Store
listing. The downloadable [GitHub releases](https://github.com/ronnierosal/Re-Gear/releases)
are development candidates. **Ordinary users must not install these development
artifacts.** This page explains the Decky installation route for a future verified,
supported release; it does not approve a build for use today. Coordinated testers
must follow their exact supervised [Getting Started](Getting-Started) baseline.

## Before installing

- Have [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader#installation)
  installed and working in Game Mode.
- Wait for a Re-Gear release explicitly approved for your hardware and installation
  path. Check [Current State](Current-State) and [Supported Hardware](Supported-Hardware).
- Download only the exact versioned Re-Gear plugin ZIP identified by that release,
  together with its published SHA-256 checksum. GitHub's automatic **Source code**
  archives are not installable plugin packages.
- Calculate the downloaded ZIP's SHA-256 using a checksum utility and compare the
  entire value with the release's published value. A missing or different checksum
  means stop. A matching checksum checks the download; it does not establish
  hardware support or safety.
- Read [Permissions and privacy](Diagnostics-and-Privacy#why-re-gear-requests-root-permission)
  and [Safety and eGPU Handling](Safety-and-eGPU-Handling) before proceeding.
  Existing legacy test installations require the separately supervised
  [identity cutover procedure](https://github.com/ronnierosal/Re-Gear/blob/main/docs/IDENTITY_CUTOVER.md).

## Install the verified ZIP through Decky

Use these steps only once the release and your installation path meet the checks
above. Keep the downloaded ZIP somewhere you can find in Decky's file picker.

1. Return to **Game Mode** and open **Quick Access**.
2. Open the **Decky** tab and select its **settings gear**.
3. In **General**, enable **Developer mode**.
4. Open **Developer** and find **Install Plugin from ZIP File**.
5. Select **Browse**, choose the verified Re-Gear ZIP, and review Decky's
   installation prompt before confirming.
6. Confirm **Re-Gear** appears in the Decky tab. Open it and review the linked
   root-permission and safety guidance before requesting hardware actions.

Re-Gear requests a root backend for limited SteamOS operations; its interface
does not run as root. Installation does not remove confirmation requirements or
expand supported hardware. If the plugin does not appear or reports an error,
stop and use [Troubleshooting](Troubleshooting).

## Optional installation from a release URL

Decky also offers **Install Plugin from URL** on the Developer page. A direct
URL option will be documented here only after a final, version-specific,
immutable Re-Gear Release asset URL and checksum are published and verified.
There is no supported install URL to use now.

## Updates, removal and recovery

Do not assume a manually installed build will receive Decky Store updates.
Check Re-Gear's release guidance before an update; it must identify the exact
replacement artifact and any migration or recovery requirements.

For Decky's plugin-management controls, use its
[official plugin guide](https://github.com/SteamDeckHomebrew/decky-loader#plugins)
and [official documentation](https://wiki.deckbrew.xyz/).
Decky notes that uninstalling a plugin removes its plugin files, but may leave
files the plugin created. Uninstalling Re-Gear is not proof that hardware state
or persistent settings were restored. Coordinated testers use their recorded
rollback plan; other users should seek help through [Troubleshooting](Troubleshooting).

## Verification behind this guide

The labels and ZIP/URL file-picker flow were checked against Decky's
[Developer settings source](https://github.com/SteamDeckHomebrew/decky-loader/blob/1ea69d315a49376e32f1fba46ffa7d028eed8046/frontend/src/components/settings/pages/developer/index.tsx),
[General settings source](https://github.com/SteamDeckHomebrew/decky-loader/blob/1ea69d315a49376e32f1fba46ffa7d028eed8046/frontend/src/components/settings/pages/general/index.tsx)
and [English labels](https://github.com/SteamDeckHomebrew/decky-loader/blob/1ea69d315a49376e32f1fba46ffa7d028eed8046/backend/decky_loader/locales/en-US.json).
This is a source review, not a fresh device installation test. Labels may vary
by Decky version and language.
