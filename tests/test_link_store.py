import json
import tempfile
import unittest
from pathlib import Path

from RandomYouTubeVideos import (
    BACKUP_DIR,
    choose_random_link,
    create_link,
    filter_links,
    extract_urls,
    load_links,
    normalize_url,
    parse_tags,
    save_links,
    sort_links,
    youtube_video_id,
)


class LinkStoreTests(unittest.TestCase):
    def test_normalize_url_accepts_common_youtube_forms(self):
        self.assertEqual(normalize_url("youtu.be/abc123"), "https://youtu.be/abc123")
        self.assertEqual(
            normalize_url("www.youtube.com/watch?v=abc123"),
            "https://www.youtube.com/watch?v=abc123",
        )

    def test_normalize_url_rejects_unsupported_schemes(self):
        with self.assertRaises(ValueError):
            normalize_url("ftp://example.com/video")

    def test_youtube_video_id_extracts_watch_short_and_shorts_links(self):
        self.assertEqual(youtube_video_id("https://youtu.be/abc123"), "abc123")
        self.assertEqual(youtube_video_id("https://www.youtube.com/watch?v=xyz789"), "xyz789")
        self.assertEqual(youtube_video_id("https://www.youtube.com/shorts/short123"), "short123")

    def test_parse_tags_normalizes_and_deduplicates(self):
        self.assertEqual(parse_tags("Music, tutorial; Music"), ["music", "tutorial"])

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.json"
            links = [create_link("https://youtu.be/abc123", "Demo", ["test"], "Demo Channel")]

            save_links(links, path)
            loaded = load_links(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].url, "https://youtu.be/abc123")
        self.assertEqual(loaded[0].title, "Demo")
        self.assertEqual(loaded[0].channel, "Demo Channel")
        self.assertEqual(loaded[0].tags, ["test"])

    def test_save_links_can_keep_a_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test-links.json"
            first = [create_link("https://example.com/a", "A")]
            second = [create_link("https://example.com/b", "B")]
            save_links(first, path)
            before = set(BACKUP_DIR.glob("test-links-*.json.bak"))

            save_links(second, path, keep_backup=True)

        backups = set(BACKUP_DIR.glob("test-links-*.json.bak")) - before
        self.assertTrue(backups)
        for backup in backups:
            backup.unlink(missing_ok=True)

    def test_load_imports_string_arrays_and_skips_duplicates_when_not_strict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.json"
            path.write_text(
                json.dumps(["https://youtu.be/abc123", "https://youtu.be/abc123", "not-a-url"]),
                encoding="utf-8",
            )

            loaded = load_links(path, strict=False)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].url, "https://youtu.be/abc123")

    def test_strict_load_rejects_invalid_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.json"
            path.write_text(json.dumps(["https://youtu.be/abc123", "not-a-url"]), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_links(path)

    def test_strict_load_rejects_duplicate_urls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.json"
            path.write_text(
                json.dumps(["https://youtu.be/abc123", "https://youtu.be/abc123"]),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                load_links(path)

    def test_load_regenerates_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "links.json"
            path.write_text(
                json.dumps(
                    {
                        "links": [
                            {"id": "same", "url": "https://example.com/a"},
                            {"id": "same", "url": "https://example.com/b"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_links(path)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(len({link.id for link in loaded}), 2)

    def test_extract_urls_from_free_text(self):
        text = "Watch https://youtu.be/abc123 and youtube.com/watch?v=xyz789."

        urls = extract_urls(text)

        self.assertEqual(urls, ["https://youtu.be/abc123", "https://youtube.com/watch?v=xyz789"])

    def test_extract_urls_trims_markdown_closing_parenthesis(self):
        text = "Watch [demo](https://youtu.be/abc123)."

        urls = extract_urls(text)

        self.assertEqual(urls, ["https://youtu.be/abc123"])

    def test_filter_links_searches_title_channel_tags_and_url(self):
        links = [
            create_link("https://example.com/a", "Alpha", ["math"], "Channel One"),
            create_link("https://example.com/b", "Beta", ["music"], "Channel Two"),
        ]

        self.assertEqual(filter_links(links, "channel one math"), [links[0]])
        self.assertEqual(filter_links(links, "music"), [links[1]])

    def test_sort_links_by_open_count(self):
        links = [create_link("https://example.com/a", "A"), create_link("https://example.com/b", "B")]
        links[0].open_count = 5
        links[1].open_count = 1

        sorted_links = sort_links(links, "opens")

        self.assertEqual([link.title for link in sorted_links], ["B", "A"])

    def test_choose_random_link_discovery_prefers_unopened(self):
        opened = create_link("https://example.com/a", "Opened")
        opened.open_count = 2
        unopened = create_link("https://example.com/b", "Unopened")

        picked = choose_random_link([opened, unopened], mode="Discovery")

        self.assertEqual(picked, unopened)


if __name__ == "__main__":
    unittest.main()
