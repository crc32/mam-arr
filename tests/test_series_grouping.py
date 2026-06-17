import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mamarr.abs.client import AudiobookshelfClient
from mamarr.db import init_db
from mamarr.inventory.sync import (
    _refresh_tracked_series_from_library,
    _series_key,
    _upsert_library_item,
)


class ParseItemSeriesTests(unittest.TestCase):
    def test_parse_item_series_object(self):
        raw = {
            "id": "book-1",
            "media": {
                "metadata": {
                    "title": "Book One",
                    "authorName": "Author A",
                    "series": {
                        "id": "series-1",
                        "name": "Test Series",
                        "sequence": "1",
                    },
                }
            },
        }
        parsed = AudiobookshelfClient.parse_item(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["series"], "Test Series")
        self.assertEqual(parsed["abs_series_id"], "series-1")
        self.assertEqual(parsed["series_sequence"], 1.0)

    def test_parse_series(self):
        raw = {
            "id": "series-1",
            "name": "Test Series",
            "books": [{"id": "book-1"}, {"id": "book-2"}],
        }
        parsed = AudiobookshelfClient.parse_series(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["num_books"], 2)
        self.assertEqual(parsed["book_ids"], ["book-1", "book-2"])


class RefreshTrackedSeriesTests(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.db_path = self.temp_db.name
        self.settings_patch = patch("mamarr.db.settings")
        self.sync_settings_patch = patch("mamarr.inventory.sync.settings")
        mock_settings = self.settings_patch.start()
        mock_sync_settings = self.sync_settings_patch.start()
        mock_settings.db_path = self.db_path
        mock_sync_settings.db_path = self.db_path
        mock_sync_settings.audiobookshelf_url = "http://abs.local"
        mock_sync_settings.audiobookshelf_token = "token"
        init_db()

    def tearDown(self):
        self.settings_patch.stop()
        self.sync_settings_patch.stop()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _seed_false_single_book_series(self, conn):
        for idx, title in enumerate(["Book One", "Book Two", "Book Three"], start=1):
            _upsert_library_item(
                conn,
                source="audiobookshelf",
                external_id=f"book-{idx}",
                title=title,
                author="Author",
                narrator="",
                series=title,
                series_sequence=float(idx),
                abs_series_id=None,
                asin=None,
                isbn=None,
                confidence="high",
            )
            conn.execute(
                """
                INSERT INTO tracked_series
                    (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
                VALUES (?, ?, 'library', 1, 1, '2026-01-01T00:00:00')
                """,
                (_series_key(title), title),
            )
        conn.commit()

    @patch("mamarr.inventory.sync.abs_client.iter_library_series")
    def test_refresh_uses_abs_catalog_and_groups_books(self, mock_iter_series):
        mock_iter_series.return_value = [
            {
                "id": "series-1",
                "name": "Real Series",
                "books": [{"id": "book-1"}, {"id": "book-2"}],
            }
        ]

        with self._conn() as conn:
            self._seed_false_single_book_series(conn)
            _refresh_tracked_series_from_library(conn)
            conn.commit()

            rows = conn.execute(
                "SELECT series_key, display_name, owned_book_count, origin FROM tracked_series ORDER BY display_name"
            ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["display_name"], "Real Series")
        self.assertEqual(rows[0]["owned_book_count"], 2)
        self.assertEqual(rows[0]["origin"], "library")

    @patch("mamarr.inventory.sync.abs_client.iter_library_series")
    def test_refresh_preserves_manual_favorites(self, mock_iter_series):
        mock_iter_series.return_value = [
            {
                "id": "series-1",
                "name": "Real Series",
                "books": [{"id": "book-1"}],
            }
        ]

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO tracked_series
                    (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
                VALUES ('manual series', 'Manual Series', 'manual', 1, 0, '2026-01-01T00:00:00')
                """
            )
            conn.commit()
            _refresh_tracked_series_from_library(conn)
            conn.commit()

            manual = conn.execute(
                "SELECT origin FROM tracked_series WHERE series_key = 'manual series'"
            ).fetchone()

        self.assertIsNotNone(manual)
        self.assertEqual(manual["origin"], "manual")


if __name__ == "__main__":
    unittest.main()
