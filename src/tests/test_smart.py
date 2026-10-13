import unittest

from glance.smart import Kind, find_entities


class FindEntitiesTest(unittest.TestCase):
    def test_nothing_is_found_in_plain_text(self) -> None:
        self.assertEqual(find_entities("Les marées de la baie, e.g. file.txt"), [])

    def test_a_web_link_is_found_and_the_sentence_end_is_dropped(self) -> None:
        [entity] = find_entities("See https://example.com/a?b=1.")

        self.assertEqual(entity.kind, Kind.LINK)
        self.assertEqual(entity.text, "https://example.com/a?b=1")
        self.assertEqual(entity.url, "https://example.com/a?b=1")

    def test_www_without_a_scheme_opens_over_https(self) -> None:
        [entity] = find_entities("visit www.example.org now")

        self.assertEqual(entity.text, "www.example.org")
        self.assertEqual(entity.url, "https://www.example.org")

    def test_a_closing_bracket_is_kept_only_when_the_link_opened_it(self) -> None:
        [wrapped] = find_entities("(see https://example.com/x)")
        [inside] = find_entities("https://en.wikipedia.org/wiki/Glance_(app)")

        self.assertEqual(wrapped.text, "https://example.com/x")
        self.assertEqual(inside.text, "https://en.wikipedia.org/wiki/Glance_(app)")

    def test_a_scheme_without_a_host_is_ignored(self) -> None:
        self.assertEqual(find_entities("https:// and www. alone"), [])

    def test_an_email_is_found_and_opens_as_mailto(self) -> None:
        [entity] = find_entities("write to jane.doe+tag@mail.example.com please")

        self.assertEqual(entity.kind, Kind.EMAIL)
        self.assertEqual(entity.text, "jane.doe+tag@mail.example.com")
        self.assertEqual(entity.url, "mailto:jane.doe+tag@mail.example.com")

    def test_an_email_is_not_also_reported_as_a_link(self) -> None:
        entities = find_entities("a@www.example.com")

        self.assertEqual([e.kind for e in entities], [Kind.EMAIL])

    def test_results_are_in_reading_order_without_repeats(self) -> None:
        text = "b@x.io https://a.example/p b@x.io https://a.example/p"

        entities = find_entities(text)

        self.assertEqual([e.text for e in entities], ["b@x.io", "https://a.example/p"])

    def test_long_labels_are_shortened(self) -> None:
        [entity] = find_entities("https://example.com/" + "a" * 80)

        self.assertEqual(len(entity.label), 40)
        self.assertTrue(entity.label.endswith("…"))


if __name__ == "__main__":
    unittest.main()
