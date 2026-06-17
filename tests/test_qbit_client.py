import unittest
from unittest.mock import MagicMock, patch

import requests

from mamarr.qbit.client import QBittorrentClient, QBittorrentError


class QBittorrentClientSessionTests(unittest.TestCase):
    def setUp(self):
        self.client = QBittorrentClient(
            base_url="http://qbit.local",
            username="admin",
            password="secret",
            session_max_age_seconds=3600,
        )

    def _login_response(self) -> MagicMock:
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.cookies = requests.cookies.RequestsCookieJar()
        response.cookies.set("SID", "session-1")
        return response

    def _api_response(self, status_code: int = 200, payload: list | None = None) -> MagicMock:
        response = MagicMock()
        response.ok = status_code < 400
        response.status_code = status_code
        response.json.return_value = payload or []
        return response

    @patch("mamarr.qbit.client.requests.post")
    def test_login_sets_session_timestamp(self, mock_post):
        mock_post.return_value = self._login_response()

        self.client.login()

        self.assertIsNotNone(self.client._logged_in_at)
        self.assertIsNotNone(self.client._cookies)

    @patch("mamarr.qbit.client.time.monotonic")
    @patch("mamarr.qbit.client.requests.post")
    def test_relogin_when_session_is_older_than_one_hour(self, mock_post, mock_monotonic):
        mock_post.return_value = self._login_response()
        mock_monotonic.side_effect = [100.0, 4600.0, 4600.1]

        self.client.login()
        self.client.login()

        self.assertEqual(mock_post.call_count, 2)

    @patch("mamarr.qbit.client.requests.request")
    @patch("mamarr.qbit.client.requests.post")
    def test_retries_once_after_403(self, mock_post, mock_request):
        mock_post.return_value = self._login_response()
        mock_request.side_effect = [
            self._api_response(status_code=403),
            self._api_response(payload=[{"hash": "abc"}]),
        ]

        torrents = self.client.list_torrents()

        self.assertEqual(len(torrents), 1)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_request.call_count, 2)

    @patch("mamarr.qbit.client.requests.request")
    @patch("mamarr.qbit.client.requests.post")
    def test_raises_after_repeated_403(self, mock_post, mock_request):
        mock_post.return_value = self._login_response()
        mock_request.return_value = self._api_response(status_code=403)

        with self.assertRaises(QBittorrentError) as ctx:
            self.client.list_torrents()

        self.assertIn("403", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(mock_request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
