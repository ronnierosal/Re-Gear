# Attribution and licensing for Panel de Control research

Credit should identify both the project and the actual contribution. Re-Gear can
acknowledge an idea without claiming to contain upstream code. Once implementation
is copied or adapted, applicable copyright and license obligations accompany it;
a README thank-you does not replace those obligations.

This is internal engineering guidance based on the reviewed licenses and primary
copyright guidance. It does not change Re-Gear's public licensing policy or resolve
every derivative-work or commercial agreement question.

## What the repositories actually declare

Panel de Control's [package metadata][pdc-package] and [third-party notices][pdc-notices]
explicitly say **GPL-3.0-only**. Its top-level [LICENSE][pdc-license] contains the
GPLv3 text. The notices attribute the library context-menu implementation to
`decky-steamgriddb`; the [source header][pdc-context] records that derivation too.
Adapting that path requires tracing the credit chain, not only crediting Hooandee.

Re-Gear's [LICENSE][rg-license] and [licensing document][rg-licensing] declare
**GPL-3.0-or-later** and discuss separately negotiated terms outside the GPL.
Re-Gear already has a [third-party notice][rg-notices] for a GPL-derived Steam
app-details helper which expressly does not claim proprietary/OEM relicensing
rights for that contribution.

GPLv3 is a common permitted version for these codebases. That does **not** grant
permission to put imported GPL-3.0-only code under a future GPL version. Preserve
its original notice and describe the combined distribution accurately. Likewise,
ownership of Re-Gear's original code does not convey ownership of upstream
contributions. A proprietary/OEM distribution containing those contributions
needs the applicable rights from their rightsholders; a Re-Gear-only agreement
cannot supply them. Commercial distribution that complies with the GPL is a
different matter and is permitted by the GPL. [FSF licensing FAQ][faq]

## Reuse categories

| Category | Example | Record and treatment |
|---|---|---|
| Research only | These notes compare their profile state model with ours | Keep immutable evidence links. No claim that runtime code has been adopted |
| Independently implemented idea | Re-Gear gets a Battery Care module with original domain/adapters/UI | Add an accurate inspiration acknowledgment when delivered; retain design provenance |
| Adapted source or tests | Port their configuration-ownership journal or a test fixture | Record source files/revision, retain notices, mark modifications and date, check downstream source delivery |
| Copied assets or text | Icons, screenshots, sounds, presets containing creative content, explanatory copy | Inspect the particular asset's provenance and terms; do not assume code licensing settles everything |
| Redistributed dependency or executable | Ship a helper binary rather than invoke an installed provider | Inventory its own dependencies, notices, source/build requirements, and exact version separately |

The US Copyright Office distinguishes protected program expression from ideas,
algorithms, and methods. An independently expressed feature is different from
translating or rearranging protected implementation. “Rewritten” is not by itself
evidence of independence. Preserve the design/source history and examine a
proposed adaptation rather than deciding solely from its filename or language.
[Copyright Office guidance][copyright]

## Distribution checklist for an actual adaptation

Before including adapted GPL code in a release:

1. Preserve applicable copyright, license, and warranty notices; include the
   license text. Identify modifications and their dates.
2. Determine the license of the covered combined work and any applicable
   interactive legal-notice requirements.
3. Provide the exact Corresponding Source through a GPL-compliant distribution
   method. Include needed build/install scripts; a link to an unrelated upstream
   revision is not the source of our modified build.
4. Assess Installation Information obligations if the distribution scenario
   involves a covered User Product transaction.

These requirements follow GPLv3 sections 1, 4, 5 and 6. [License text][gpl]
The FSF also recommends retaining upstream copyright notices when copying
same-license code. [GNU license application guidance][howto]

For Re-Gear's release process, the practical evidence should identify the release
ZIP, exact Re-Gear commit, adapted upstream commit/file set, license inventory,
and source/build material delivered for that release. An attestation identifies
build provenance; it is not a substitute for source availability or license
compliance.

## Existing Re-Gear issue to resolve before distribution

At baseline `c09df57`, Re-Gear's `LICENSE` is a short notice pointing to the GPL
website, while `THIRD_PARTY_NOTICES.md` says the full GPL text is included in that
file. The inspected [package file list][rg-build] includes `LICENSE` and
`THIRD_PARTY_NOTICES.md` but does not enumerate a separate full GPL text. This is
a concrete source-level inconsistency and a release-review item. No produced ZIP
was inspected here, so this note does not assert what every historical release
contained.

Recommended follow-up: include the complete applicable GPL terms in the distributed
material, reconcile the notice's claim, and validate the actual archive contents
plus corresponding-source delivery. This research leaves the existing public
licensing files unchanged.

## Upstream documentation conflict relevant to reuse

The [README][pdc-readme] says RyzenAdj is not bundled. The
[third-party notices][pdc-notices], [release workflow][pdc-release], and
[build recipe][pdc-ryzen-build] describe/build a release binary, including static
libpci. Treat this as a documentation conflict resolved in favor of the inspected
build path for source-level analysis; inspect a particular ZIP before claiming
its actual contents. Do not copy that binary/build recipe into Re-Gear under the
assumption that invoking a subprocess removes redistribution obligations. This
review does not establish the full license inventory of the linked binary.

## Notice templates for future use

For inspiration only, after the referenced feature is actually implemented:

> The design of [specific feature] was informed by Hooandee's Panel de Control,
> reviewed at [commit permalink]. Re-Gear implements this feature independently;
> no Panel de Control source or assets were copied for this feature.

Use the independence sentence only when supported by the implementation history.
Do not apply it to a translation or substantial adaptation.

For adapted implementation, fill in an internal provenance record first:

| Field | Required content |
|---|---|
| Project and author attribution | Panel de Control; Hooandee and applicable contributors, plus upstream chain where relevant |
| Source | Exact repository URL, commit, file paths and relevant symbols |
| Original notices | Verbatim applicable notices; do not invent a copyright year or holder |
| License | Exact applicable identifier, including the `-only` distinction |
| Destination | Re-Gear files and introducing commit |
| Modifications | What changed and when |
| Dependencies/assets | Separately checked provenance and terms |
| Distribution evidence | License files, source delivery, and release-specific verification |

Then add a concise factual entry to `THIRD_PARTY_NOTICES.md`, retain relevant
file-level notices, and make Credits/Licenses accessible where applicable. Credit
only actual adaptations; do not imply upstream endorsement of Re-Gear.

## Sources

Primary sources below were accessed September 9, 2026, America/Los_Angeles.
Repository links are pinned to the revisions reviewed; legal guidance is general
and must be applied to the actual material and distribution.

[pdc-package]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/package.json#L13-L14
[pdc-notices]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/THIRD_PARTY_NOTICES.md
[pdc-license]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/LICENSE
[pdc-context]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/gameContextMenu.tsx#L18-L23
[pdc-readme]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/README.md
[pdc-release]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/.github/workflows/release-please.yml
[pdc-ryzen-build]: https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/scripts/build-ryzenadj.sh#L16-L68
[rg-license]: https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/LICENSE
[rg-licensing]: https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/docs/LICENSING.md
[rg-notices]: https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/THIRD_PARTY_NOTICES.md
[rg-build]: https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/scripts/build_plugin.py#L24-L42
[gpl]: https://opensource.org/license/gpl-3.0
[howto]: https://www.gnu.org/licenses/gpl-howto.en.html
[faq]: https://www.gnu.org/licenses/gpl-faq.en.html
[copyright]: https://www.copyright.gov/register/tx-programs.html
