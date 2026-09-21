"""Fixtures for the documentation CI gate; no network or repository mutation."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.check_docs_links import check


class DocsLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("docs/INDEX.md", "# Docs\n")

    def write(self, name, content=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_relative_images_encoded_paths_titles_and_fragments(self):
        self.write("docs/INDEX.md", '[guide](Guide.md?q=x#missing-anchor) ![picture](assets/a%20b.png "title") [root](/README.md)')
        self.write("docs/Guide.md", '[pic](<assets/a b.png>) [code](../source/a(b).py)')
        self.write("docs/assets/a b.png")
        self.write("source/a(b).py")
        self.write("README.md", "[docs](docs/INDEX.md)")
        self.assertEqual(check(self.root), ([], 3))

    def test_references_full_collapsed_shortcut_and_images(self):
        self.write("docs/INDEX.md", '[full][Guide] [guide][] [guide] ![art][image]\n\n[guide]: Guide.md "Title"\n[image]: assets/a.png\n')
        self.write("docs/Guide.md")
        self.write("docs/assets/a.png")
        self.assertEqual(check(self.root)[0], [])

    def test_missing_reference_destination_and_image_report_lines(self):
        self.write("docs/INDEX.md", '[link][ref]\n\n[ref]: absent.md\n![image](missing.png)')
        errors, _ = check(self.root)
        self.assertTrue(any("INDEX.md:1: missing target: absent.md" in e for e in errors))
        self.assertTrue(any("INDEX.md:4: missing target: missing.png" in e for e in errors))

    def test_code_comments_external_and_anchor_only_are_ignored(self):
        self.write("docs/INDEX.md", '''`[fake](absent.md)`
````md
[fake](absent.md)
```
````
~~~
[fake](absent.md)
~~~
<!-- [fake](absent.md) -->
[web](https://example.invalid/a) [mail](mailto:a@example.invalid)
[anchor](#anything) [url](//example.invalid/a) [scheme](steam://launch)
''')
        self.assertEqual(check(self.root)[0], [])

    def test_case_sensitive_on_all_platforms(self):
        self.write("docs/INDEX.md", "[case](guide.md)")
        self.write("docs/Guide.md")
        errors, _ = check(self.root)
        self.assertTrue(any("case mismatch" in e for e in errors))
        self.assertTrue(any("Guide.md: unreachable" in e for e in errors))

    def test_graph_reachability_and_cycles(self):
        self.write("docs/INDEX.md", "[guide](nested/README.md)")
        self.write("docs/nested/README.md", "[deep](../Guide.md)")
        self.write("docs/Guide.md", "[cycle](INDEX.md)")
        self.write("docs/Orphan.md", "[outgoing](Guide.md)")
        self.assertEqual(check(self.root)[0], ["docs/Orphan.md: unreachable from docs/INDEX.md"])

    def test_unused_reference_does_not_make_page_reachable(self):
        self.write("docs/INDEX.md", "[unused]: Orphan.md\n")
        self.write("docs/Orphan.md")
        self.assertEqual(check(self.root)[0], ["docs/Orphan.md: unreachable from docs/INDEX.md"])

    def test_directories_are_valid_and_landing_page_is_traversed(self):
        self.write("docs/INDEX.md", "[folder](nested/) [assets](assets/)")
        self.write("docs/nested/README.md", "[guide](../Guide.md)")
        self.write("docs/Guide.md")
        self.write("docs/assets/a.png")
        self.assertEqual(check(self.root)[0], [])

    def test_archive_and_root_links_checked(self):
        self.write("docs/archive/old.md", "[broken](missing.md)")
        self.write("README.md", "[broken](absent.md)")
        errors, count = check(self.root)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 2)

    def test_repository_escape_rejected(self):
        self.write("docs/INDEX.md", "[outside](../../outside.md)")
        self.assertIn("target escapes repository", check(self.root)[0][0])

    def test_invalid_encoding_reports_file_without_crashing(self):
        self.write("docs/archive/old.md").write_bytes(b"bad\x97text")
        self.assertEqual(check(self.root)[0], ["docs/archive/old.md: invalid UTF-8 at byte 3"])

    def test_cli_exit_status_and_root(self):
        script = Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py"
        command = [sys.executable, str(script), "--root", str(self.root)]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.write("docs/INDEX.md", "[broken](missing.md)")
        bad = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("missing target", bad.stdout)


if __name__ == "__main__":
    unittest.main()
