import unittest
from unittest.mock import patch

from mamarr.format_filter import formats_from_qbit_tags, has_m4_format, owned_is_mp3_only
from mamarr.inventory.format_swap import find_potential_swaps, get_owned_formats_for_book


class FormatSwapTests(unittest.TestCase):
    def test_has_m4_format(self):
        self.assertTrue(has_m4_format("m4b"))
        self.assertTrue(has_m4_format("mp3,m4a"))
        self.assertFalse(has_m4_format("mp3"))

    def test_owned_is_mp3_only(self):
        self.assertTrue(owned_is_mp3_only({"mp3"}))
        self.assertFalse(owned_is_mp3_only({"mp3", "m4b"}))
        self.assertFalse(owned_is_mp3_only(set()))

    def test_formats_from_qbit_tags(self):
        self.assertEqual(
            formats_from_qbit_tags("audiobooks, MaM Do Not Delete, mp3"),
            "mp3",
        )

    def test_find_potential_swaps_flags_m4_for_mp3_owned_book(self):
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
            {"id": 1, "title": "Book One", "author": "Author", "narrator": "", "filetypes": "m4b"},
            {"id": 2, "title": "Book Two", "author": "Author", "narrator": "", "filetypes": "m4b"},
        ]

        with patch(
            "mamarr.inventory.format_swap.get_owned_books_for_series",
            return_value=owned,
        ), patch(
            "mamarr.inventory.format_swap.get_owned_formats_for_book",
            side_effect=lambda item, *_args, **_kwargs: (
                {"mp3"} if item["title"] == "Book One" else set()
            ),
        ):
            swaps = find_potential_swaps(
                mam_results,
                series_key="test series",
                series_name="Test Series",
            )

        self.assertEqual(len(swaps), 1)
        self.assertEqual(swaps[0]["title"], "Book One")
        self.assertTrue(swaps[0]["potential_swap"])
        self.assertEqual(swaps[0]["owned_formats"], ["mp3"])
        self.assertEqual(swaps[0]["upgrade_formats"], ["m4b"])


if __name__ == "__main__":
    unittest.main()
