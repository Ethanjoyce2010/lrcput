import unittest
import types
import lrcput

class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload

class TestLRCPut(unittest.TestCase):
    def test_parse_artist_title_from_filename_dash(self):
        path = r"C:\music\Artist Name - Song Title.mp3"
        artist, title = lrcput.parse_artist_title_from_filename(path)
        self.assertEqual(artist, "Artist Name")
        self.assertEqual(title, "Song Title")

    def test_parse_artist_title_from_filename_underscore(self):
        path = r"/home/user/Some_Track.flac"
        artist, title = lrcput.parse_artist_title_from_filename(path)
        self.assertEqual(artist, "Some")
        self.assertEqual(title, "Track")

    def test_fetch_lyrics_from_lrclib_get(self):
        # Simulate /get returning plainLyrics
        def fake_get(url, params=None, timeout=None):
            if url.endswith('/get'):
                return DummyResponse(200, {'plainLyrics': 'these are the lyrics'})
            return DummyResponse(404, {})
        orig_get = lrcput.requests.get
        lrcput.requests.get = fake_get
        try:
            res = lrcput.fetch_lyrics_from_lrclib('Artist', 'Title', duration=200)
            self.assertEqual(res, 'these are the lyrics')
        finally:
            lrcput.requests.get = orig_get

    def test_fetch_lyrics_from_lrclib_search(self):
        # Simulate /get miss and /search returns list of items
        def fake_get(url, params=None, timeout=None):
            if url.endswith('/get'):
                return DummyResponse(404, {})
            if url.endswith('/search'):
                return DummyResponse(200, [ {'plainLyrics': 'from search'} ])
            return DummyResponse(404, {})
        orig_get = lrcput.requests.get
        lrcput.requests.get = fake_get
        try:
            res = lrcput.fetch_lyrics_from_lrclib('A', 'B')
            self.assertEqual(res, 'from search')
        finally:
            lrcput.requests.get = orig_get

if __name__ == '__main__':
    unittest.main()
