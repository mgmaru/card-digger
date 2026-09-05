"""Unit tests for `photos_probe`.

Everything here is decided before the run touches Mercari. The counting rules,
the "is it big enough to look at" rule and the harness's image count are the
things a result could be talked into afterwards, so they are pinned first.

    poc/mercapi/.venv/bin/python -m unittest discover -s poc/mercapi -p 'test*.py'
"""

from __future__ import annotations

import unittest

from photos_probe import (
    adapter_choice,
    build_harness,
    compare_modes,
    count_summary,
    is_valid_run,
    photo_urls,
    thumbnail_urls,
    timing_summary,
    url_shape,
    usable_summary,
)


class Photo:
    def __init__(self, uri):
        self.uri = uri


class Entry:
    def __init__(self, photos=None, thumbnails=None):
        if photos is not None:
            self.photos = photos
        if thumbnails is not None:
            self.thumbnails = thumbnails


class ReadingTheLists(unittest.TestCase):
    def test_reads_objects_and_bare_strings_alike(self):
        entry = Entry(photos=[Photo("https://a/1.jpg"), "https://a/2.jpg"])
        self.assertEqual(
            photo_urls(entry), ["https://a/1.jpg", "https://a/2.jpg"]
        )

    def test_drops_blanks_rather_than_counting_them(self):
        # A blank uri is not a photo. Counting it would inflate the number the
        # whole decision rests on.
        entry = Entry(photos=[Photo("  "), Photo(None), "https://a/1.jpg", ""])
        self.assertEqual(photo_urls(entry), ["https://a/1.jpg"])

    def test_a_missing_field_is_no_photos_not_an_error(self):
        self.assertEqual(photo_urls(Entry()), [])
        self.assertEqual(thumbnail_urls(Entry()), [])

    def test_reports_which_list_the_adapter_would_use(self):
        self.assertEqual(adapter_choice(["a"], ["b"]), "photos")
        self.assertEqual(adapter_choice([], ["b"]), "thumbnails")
        self.assertEqual(adapter_choice([], []), "none")


class ReadingAUrl(unittest.TestCase):
    def test_reads_the_resize_segment_mercari_puts_in_the_path(self):
        shape = url_shape("https://static.mercdn.net/c!/w=240,f=webp/thumb/x_1.jpg")
        self.assertEqual(shape["declaredWidth"], 240)
        self.assertEqual(shape["host"], "static.mercdn.net")

    def test_says_nothing_when_the_url_declares_nothing(self):
        shape = url_shape("https://static.mercdn.net/item/detail/orig/x_1.jpg")
        self.assertIsNone(shape["declaredWidth"])
        self.assertIsNone(shape["declaredHeight"])


class CountingPhotos(unittest.TestCase):
    def test_keeps_the_distribution_not_just_an_average(self):
        # Four listings with one photo and four with eight average the same as
        # eight with four, and lead to different screens.
        summary = count_summary([1, 1, 1, 1, 8, 8, 8, 8])
        self.assertEqual(summary["one"], 4)
        self.assertEqual(summary["twoOrMore"], 4)
        self.assertEqual(summary["min"], 1)
        self.assertEqual(summary["max"], 8)
        self.assertEqual(summary["histogram"], {1: 4, 8: 4})

    def test_counts_listings_with_no_photo_at_all(self):
        self.assertEqual(count_summary([0, 0, 3])["zero"], 2)

    def test_an_empty_search_is_not_a_zero_median(self):
        self.assertEqual(count_summary([]), {"items": 0})


class WhetherAnImageCanBeLookedAt(unittest.TestCase):
    def test_a_200_is_not_a_picture_and_a_picture_is_not_a_readable_one(self):
        records = [
            {"httpStatus": 200, "bytes": 10, "pixelWidth": 240, "pixelHeight": 240,
             "decodeFormat": "jpeg"},
            {"httpStatus": 200, "bytes": 90, "pixelWidth": 1080, "pixelHeight": 1080,
             "decodeFormat": "jpeg"},
            # Arrived, never decoded.
            {"httpStatus": 200, "bytes": 4},
            {"httpStatus": 404, "bytes": 0},
        ]
        summary = usable_summary(records, minimum_edge=400)

        self.assertEqual(summary["fetched"], 3)
        self.assertEqual(summary["decoded"], 2)
        self.assertEqual(summary["readable"], 1)

    def test_measures_the_shorter_side_so_a_wide_strip_does_not_pass(self):
        records = [
            {"httpStatus": 200, "bytes": 1, "pixelWidth": 1200, "pixelHeight": 80,
             "decodeFormat": "jpeg"}
        ]
        self.assertEqual(usable_summary(records, minimum_edge=200)["readable"], 0)

    def test_reports_the_floor_it_used(self):
        # The floor is this repository's, not Mercari's. It travels with the
        # number so a different one can be applied to the same measurement.
        self.assertEqual(usable_summary([], minimum_edge=200)["minimumEdgePx"], 200)


class SummarisingRepeats(unittest.TestCase):
    def test_takes_the_median_and_keeps_the_spread(self):
        runs = [
            {"aboveFoldReadyMs": 100, "networkIdleMs": 1, "imageRequests": 10,
             "imageBytes": 5, "aboveFoldImages": 12},
            {"aboveFoldReadyMs": 900, "networkIdleMs": 1, "imageRequests": 10,
             "imageBytes": 5, "aboveFoldImages": 12},
            {"aboveFoldReadyMs": 200, "networkIdleMs": 1, "imageRequests": 10,
             "imageBytes": 5, "aboveFoldImages": 12},
        ]
        ready = timing_summary(runs)["aboveFoldReadyMs"]

        self.assertEqual(ready["median"], 200)
        self.assertEqual(ready["min"], 100)
        self.assertEqual(ready["max"], 900)

    def test_no_runs_is_not_a_zero(self):
        self.assertEqual(
            timing_summary([]), {"runs": 0, "attempted": 0, "discarded": 0}
        )


class WhetherARepeatMeasuredAnything(unittest.TestCase):
    def test_a_repeat_that_decoded_nothing_is_not_a_slow_repeat(self):
        # Seen for real: one image request, none of twenty four decoded,
        # eighteen seconds. Nothing loaded, so nothing was timed.
        self.assertFalse(
            is_valid_run(
                {"aboveFoldImages": 24, "aboveFoldDecoded": 0, "imageRequests": 1}
            )
        )

    def test_a_partial_decode_is_not_comparable_either(self):
        self.assertFalse(
            is_valid_run({"aboveFoldImages": 24, "aboveFoldDecoded": 23})
        )

    def test_every_image_decoded_is_a_measurement(self):
        self.assertTrue(is_valid_run({"aboveFoldImages": 24, "aboveFoldDecoded": 24}))

    def test_a_page_with_no_images_above_the_fold_measures_nothing(self):
        self.assertFalse(is_valid_run({"aboveFoldImages": 0, "aboveFoldDecoded": 0}))

    def test_the_summary_drops_the_broken_repeat_and_says_so(self):
        runs = [
            {"aboveFoldImages": 2, "aboveFoldDecoded": 0, "aboveFoldReadyMs": 18000},
            {"aboveFoldImages": 2, "aboveFoldDecoded": 2, "aboveFoldReadyMs": 600},
            {"aboveFoldImages": 2, "aboveFoldDecoded": 2, "aboveFoldReadyMs": 800},
        ]
        summary = timing_summary(runs)

        self.assertEqual(summary["attempted"], 3)
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["discarded"], 1)
        self.assertEqual(summary["aboveFoldReadyMs"]["median"], 700)
        self.assertEqual(summary["aboveFoldReadyMs"]["max"], 800)

    def test_every_repeat_broken_is_no_measurement_not_a_zero(self):
        runs = [{"aboveFoldImages": 2, "aboveFoldDecoded": 0, "aboveFoldReadyMs": 9}]
        self.assertEqual(timing_summary(runs)["runs"], 0)


class ComparingModes(unittest.TestCase):
    def test_compares_every_mode_against_the_one_that_ships(self):
        summaries = {
            "one": {"aboveFoldReadyMs": {"median": 400}, "imageBytes": {"median": 100}},
            "four": {"aboveFoldReadyMs": {"median": 600}, "imageBytes": {"median": 400}},
        }
        comparison = compare_modes(summaries)

        self.assertEqual(comparison["one"]["readyRatio"], 1.0)
        self.assertEqual(comparison["four"]["readyRatio"], 1.5)
        self.assertEqual(comparison["four"]["readyDeltaMs"], 200)
        self.assertEqual(comparison["four"]["bytesRatio"], 4.0)

    def test_no_baseline_means_no_ratio_rather_than_a_made_up_one(self):
        summaries = {"four": {"aboveFoldReadyMs": {"median": 600}}}
        self.assertIsNone(compare_modes(summaries)["four"]["readyRatio"])


class TheHarnessPage(unittest.TestCase):
    CARDS = [
        ["https://a/1.jpg", "https://a/2.jpg", "https://a/3.jpg"],
        ["https://b/1.jpg"],
    ]

    def test_one_photo_per_card_is_what_ships_today(self):
        html = build_harness(self.CARDS, 1)
        self.assertEqual(html.count("<img"), 2)

    def test_asking_for_more_than_a_listing_has_does_not_invent_one(self):
        html = build_harness(self.CARDS, 4)
        self.assertEqual(html.count("<img"), 4)

    def test_all_means_every_photo_the_listing_carries(self):
        html = build_harness(self.CARDS, None)
        self.assertEqual(html.count("<img"), 4)

    def test_every_image_stays_lazy_the_way_the_card_does(self):
        html = build_harness(self.CARDS, None)
        self.assertEqual(html.count('loading="lazy"'), html.count("<img"))

    def test_a_listing_with_no_photo_renders_no_card(self):
        self.assertEqual(build_harness([[]], None).count("<img"), 0)

    def test_uses_the_real_grid_minimum_so_the_fold_holds_the_real_count(self):
        self.assertIn("minmax(200px, 1fr)", build_harness(self.CARDS, 1))


if __name__ == "__main__":
    unittest.main()
