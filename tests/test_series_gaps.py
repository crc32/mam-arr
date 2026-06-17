import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mamarr.db import init_db
from mamarr.inventory.series_gaps import (
    find_missing_series_books,
    is_book_owned_for_series,
    normalize_series_title,
)


class SeriesGapsTests(unittest.TestCase):
    def test_normalize_series_title_strips_prefix_and_book_number(self):
        title = normalize_series_title("Mistborn: The Final Empire", "Mistborn")
        self.assertEqual(title, "the final empire")

        title = normalize_series_title("03 - The Hero of Ages", "Mistborn")
        self.assertEqual(title, "the hero of ages")

    def test_is_book_owned_for_series_matches_series_prefixed_title(self):
        owned = [
            {
                "title": "The Final Empire",
                "author": "Brandon Sanderson",
                "narrator": "Michael Kramer",
                "asin": None,
                "isbn": None,
                "title_key": "the final empire|brandon sanderson|michael kramer",
                "title_author_key": "the final empire|brandon sanderson",
            }
        ]
        item = {
            "title": "Mistborn: The Final Empire",
            "author": "Brandon Sanderson",
            "narrator": "Michael Kramer",
            "asin": None,
            "isbn": None,
        }
        self.assertTrue(is_book_owned_for_series(item, "Mistborn", owned))

    def test_find_missing_series_books_returns_unowned_titles(self):
        owned = [
            {
                "title": "Book One",
                "author": "Author",
                "narrator": "",
                "asin": None,
                "isbn": None,
                "title_key": "book one|author|",
                "title_author_key": "book one|author",
            }
        ]
        mam_results = [
            {"id": 1, "title": "Book One", "author": "Author", "narrator": ""},
            {"id": 2, "title": "Book Two", "author": "Author", "narrator": ""},
        ]

        with patch("mamarr.inventory.series_gaps.get_owned_books_for_series", return_value=owned):
            missing = find_missing_series_books(
                mam_results,
                series_key="test series",
                series_name="Test Series",
            )

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["title"], "Book Two")


class CheckSeriesUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.settings_patch = patch("mamarr.db.settings")
        self.favorites_settings_patch = patch("mamarr.favorites.settings", create=True)
        mock_settings = self.settings_patch.start()
        mock_settings.db_path = self.db_path
        mock_favorites_settings = patch("mamarr.config.settings")
        self.config_settings_patch = mock_favorites_settings.start()
        self.config_settings_patch.mam_cookie = "cookie"
        self.config_settings_patch.db_path = self.db_path
        init_db()

    def tearDown(self):
        self.settings_patch.stop()
        self.config_settings_patch.stop()

    @patch("mamarr.favorites.search_mam_all")
    @patch("mamarr.inventory.series_gaps.get_owned_books_for_series")
    def test_new_torrent_for_same_book_is_not_a_new_upload(
        self,
        mock_owned,
        mock_search,
    ):
        from mamarr.favorites import check_series_updates

        mock_search.return_value = [
            {"id": 202, "title": "Book Two", "author": "Author", "narrator": "Narrator A", "filetype": "mp3"},
        ]
        mock_owned.return_value = [
            {
                "title": "Book One",
                "author": "Author",
                "narrator": "",
                "asin": None,
                "isbn": None,
                "title_key": "book one|author|",
                "title_author_key": "book one|author",
            }
        ]

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO tracked_series
                (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
            VALUES ('test series', 'Test Series', 'manual', 1, 1, '2026-01-01T00:00:00')
            """
        )
        tracked_id = conn.execute("SELECT id FROM tracked_series").fetchone()[0]
        conn.execute(
            """
            INSERT INTO series_seen_torrents
                (tracked_series_id, torrent_id, title, author, narrator, filetypes, first_seen_at)
            VALUES (?, '101', 'Book Two', 'Author', 'Narrator B', 'm4b', '2026-01-01T00:00:00')
            """,
            (tracked_id,),
        )
        conn.commit()
        conn.close()

        result = check_series_updates(series_name="Test Series", mark_seen=False)

        self.assertEqual(result["missing_count"], 1)
        self.assertEqual(result["new_upload_count"], 0)

    @patch("mamarr.favorites.search_mam_all")
    @patch("mamarr.inventory.series_gaps.get_owned_books_for_series")
    def test_missing_books_surface_even_when_torrent_was_seen_before(
        self,
        mock_owned,
        mock_search,
    ):
        from mamarr.favorites import check_series_updates

        mock_search.return_value = [
            {"id": 101, "title": "Book Two", "author": "Author", "narrator": "", "filetype": "m4b"},
        ]
        mock_owned.return_value = [
            {
                "title": "Book One",
                "author": "Author",
                "narrator": "",
                "asin": None,
                "isbn": None,
                "title_key": "book one|author|",
                "title_author_key": "book one|author",
            }
        ]

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO tracked_series
                (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
            VALUES ('test series', 'Test Series', 'manual', 1, 1, '2026-01-01T00:00:00')
            """
        )
        tracked_id = conn.execute("SELECT id FROM tracked_series").fetchone()[0]
        conn.execute(
            """
            INSERT INTO series_seen_torrents
                (tracked_series_id, torrent_id, title, author, narrator, filetypes, first_seen_at)
            VALUES (?, '101', 'Book Two', 'Author', '', 'm4b', '2026-01-01T00:00:00')
            """,
            (tracked_id,),
        )
        conn.commit()
        conn.close()

        result = check_series_updates(series_name="Test Series", mark_seen=False)

        self.assertEqual(result["missing_count"], 1)
        self.assertEqual(result["missing_books"][0]["title"], "Book Two")
        self.assertEqual(result["new_upload_count"], 0)


if __name__ == "__main__":
    unittest.main()
