# Wiki maintenance and publication

## Canonical-home decision — September 14, 2026

`docs/wiki/` is the only maintained guide source. Its player/technical structure
preserves the clearer manual organization. Useful unique flat-Wiki material and
assets have been migrated. Full superseded articles are retained in
`docs/archive/legacy-wiki/`, labelled historical. Root `wiki/` files are
compatibility pointers only, with no duplicate guide body. They are not publishable
source. The public `Player-Manual` URL forwards to `Player-Guide`.

Engineering contracts remain in `docs/`; code/tests define executable behavior.
The separate GitHub Wiki is generated publication output. Edit the canonical
source, never maintain a second live article by hand.

## Page standard

Start with a short plain-language summary. Substantive guides use **For players —
no technical background needed** and **Technical details — for advanced users
and contributors**. Index pages need no artificial technical section. Use actual
labels, expected results, failure guidance and necessary term definitions. Keep
planned, implemented, installed and hardware-tested claims distinct.

Use the [feature template](../templates/WIKI_FEATURE_TEMPLATE.md) and
[troubleshooting template](../templates/WIKI_TROUBLESHOOTING_TEMPLATE.md).
Keep shared explanations linked rather than copying long passages. Mockups and
their written instructions must identify design/candidate status. A mock is not
an installed screenshot or a hardware result.

## Publication procedure

1. Verify owning source/evidence, active claims and live Wiki edits. Review the
   final canonical diff independently and merge the source first.
2. Run `python scripts/check_docs_links.py`. It checks local paths, case and
   encoding plus root-document reachability from INDEX. It does not validate
   remote availability or heading fragments.
3. Render to an empty directory with
   `python scripts/publish_wiki.py --output <empty-staging-directory>`.
   [publication.json](publication.json) explicitly maps every published page.
   The renderer rewrites internal page links and stages images with Wiki-safe
   URLs. It does not push Git or overwrite existing output.
4. Fetch the separate `https://github.com/ronnierosal/Re-Gear.wiki.git` repository.
   Inspect changes since the last publication, compare every affected destination
   and preserve unrelated changes. Copy only reviewed generated files; never
   blanket-delete unknown pages or force-push.
5. Commit with a public no-reply identity, push, and verify content, navigation,
   images and aliases on GitHub. Record source commit, Wiki commit, URLs and
   remaining gaps in the shared hub. A main-repository commit alone is not Wiki
   publication.

Archives are never in the publication map. Historical evidence remains available
through explicitly labelled technical history pages and links to repository
records. No automatic publication is configured; CI validates documentation.
