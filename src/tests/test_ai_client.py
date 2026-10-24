import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from glance.ai.client import GroqError, chat, check_key, parse
from glance.ai.key import find_key, key_file, save_key

REPLY = json.dumps({"choices": [{"message": {"content": "  It is a greeting.\n"}}]})
PAYLOAD: dict[str, Any] = {"model": "m", "messages": []}


class ParseTest(unittest.TestCase):
    def test_the_reply_is_trimmed(self) -> None:
        self.assertEqual(parse(REPLY), "It is a greeting.")

    def test_an_unexpected_response_is_an_error(self) -> None:
        empty = json.dumps({"choices": [{"message": {"content": " "}}]})
        for body in ("not json", "[]", '{"choices": []}', '{"choices": 3}', empty):
            with self.subTest(body=body), self.assertRaises(GroqError):
                parse(body)


class ChatTest(unittest.TestCase):
    def _respond(self, body: str) -> MagicMock:
        response = MagicMock()
        response.read.return_value = body.encode()
        response.__enter__.return_value = response
        return response

    def test_the_payload_is_posted_with_the_key_and_the_reply_returned(self) -> None:
        with patch(
            "urllib.request.urlopen", return_value=self._respond(REPLY)
        ) as urlopen:
            answer = chat(PAYLOAD, "secret")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(json.loads(request.data), PAYLOAD)
        self.assertEqual(answer, "It is a greeting.")

    def test_the_key_comes_from_the_environment(self) -> None:
        with (
            patch.dict(os.environ, {"GROQ_API_KEY": "from-env"}),
            patch("urllib.request.urlopen", return_value=self._respond(REPLY)) as o,
        ):
            chat(PAYLOAD)

        self.assertEqual(
            o.call_args.args[0].get_header("Authorization"), "Bearer from-env"
        )

    def test_the_key_comes_from_the_key_file_when_the_environment_has_none(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as config:
            folder = Path(config, "glance")
            folder.mkdir()
            (folder / "groq_key").write_text("from-file\n")
            with (
                patch.dict(os.environ, {"XDG_CONFIG_HOME": config}, clear=True),
                patch("urllib.request.urlopen", return_value=self._respond(REPLY)) as o,
            ):
                chat(PAYLOAD)

        header = o.call_args.args[0].get_header("Authorization")
        self.assertEqual(header, "Bearer from-file")

    def test_a_missing_key_is_explained_and_nothing_is_sent(self) -> None:
        # An empty config folder, so a key file of the developer's own is not found.
        with (
            tempfile.TemporaryDirectory() as config,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": config}, clear=True),
            patch("urllib.request.urlopen") as urlopen,
            self.assertRaisesRegex(GroqError, "glance key"),
        ):
            chat(PAYLOAD)

        urlopen.assert_not_called()

    def test_http_errors_are_explained(self) -> None:
        for code, message in ((401, "key"), (429, "limiting"), (500, "HTTP 500")):
            error = urllib.error.HTTPError("u", code, "x", None, None)  # pyright: ignore[reportArgumentType]
            with (
                self.subTest(code=code),
                patch("urllib.request.urlopen", side_effect=error),
                self.assertRaisesRegex(GroqError, message),
            ):
                chat(PAYLOAD, "k")

    def test_groqs_own_message_is_shown(self) -> None:
        body = io.BytesIO(b'{"error": {"message": "The model does not exist"}}')
        error = urllib.error.HTTPError("u", 404, "x", None, body)  # pyright: ignore[reportArgumentType]
        with (
            patch("urllib.request.urlopen", side_effect=error),
            self.assertRaisesRegex(GroqError, "HTTP 404.*model does not exist"),
        ):
            chat(PAYLOAD, "k")

    def test_no_network_is_explained(self) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")),
            self.assertRaisesRegex(GroqError, "reach"),
        ):
            chat(PAYLOAD, "k")


class KeyFileTest(unittest.TestCase):
    def test_a_saved_key_is_found_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as config:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": config}, clear=True):
                save_key("  gsk_abc \n")

                self.assertEqual(find_key(), "gsk_abc")
                self.assertEqual(key_file().stat().st_mode & 0o777, 0o600)

    def test_saving_again_replaces_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as config:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": config}, clear=True):
                save_key("a-much-longer-first-key")
                save_key("second")

                self.assertEqual(find_key(), "second")

    def test_the_environment_wins_over_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as config:
            environment = {"XDG_CONFIG_HOME": config, "GROQ_API_KEY": "from-env"}
            with patch.dict(os.environ, environment, clear=True):
                save_key("from-file")

                self.assertEqual(find_key(), "from-env")


class CheckKeyTest(unittest.TestCase):
    def test_an_accepted_key_lists_the_models_with_it(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            check_key("secret")

        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/models"))
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_failures_are_explained(self) -> None:
        unauthorized = urllib.error.HTTPError("u", 401, "x", None, None)  # pyright: ignore[reportArgumentType]
        for error, message in (
            (unauthorized, "rejected"),
            (urllib.error.URLError("x"), "reach"),
        ):
            with (
                self.subTest(message=message),
                patch("urllib.request.urlopen", side_effect=error),
                self.assertRaisesRegex(GroqError, message),
            ):
                check_key("k")
