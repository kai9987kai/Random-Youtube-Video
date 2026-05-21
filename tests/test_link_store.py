import json
import tempfile
import unittest
from pathlib import Path

from RandomYouTubeVideos import (
    create_link,
    extract_urls,
    load_links,
    normalize_url,
    parse_tags,
    save_links,
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
            links = [create_link("https://youtu.be/abc123", "Demo", ["test"])]

            save_links(links, path)
            loaded = load_links(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].url, "https://youtu.be/abc123")
        self.assertEqual(loaded[0].title, "Demo")
        self.assertEqual(loaded[0].tags, ["test"])

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


if __name__ == "__main__":
    unittest.main()
