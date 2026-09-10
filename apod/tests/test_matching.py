"""Unit tests for candidate scoring.

`matching.py` has no Django dependencies, so these are plain unit tests over
strings. The cases are drawn from real APOD titles and the candidates live
MediaWiki actually returns for them.
"""

from django.test import SimpleTestCase

from apod.matching import (
    MATCH_THRESHOLD,
    best_match,
    score_candidate,
    strip_disambiguator,
    tokenize,
)


class TokenizeTests(SimpleTestCase):
    def test_lowercases_and_splits_on_punctuation(self):
        self.assertEqual(tokenize("M31: The Andromeda Galaxy"), ["m31", "andromeda", "galaxy"])

    def test_drops_stopwords(self):
        self.assertEqual(tokenize("Pink Aurora over Crater Lake"), ["pink", "aurora", "crater", "lake"])

    def test_folds_apostrophes_rather_than_splitting_on_them(self):
        self.assertEqual(tokenize("Cat's Eye"), ["cats", "eye"])
        self.assertEqual(tokenize("Cats Eye"), ["cats", "eye"])

    def test_empty_input(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])


class StripDisambiguatorTests(SimpleTestCase):
    def test_removes_wikipedias_parenthetical_qualifier(self):
        self.assertEqual(strip_disambiguator("Halo (optical phenomenon)"), "Halo")

    def test_leaves_ordinary_titles_alone(self):
        self.assertEqual(strip_disambiguator("Comet NEOWISE"), "Comet NEOWISE")


class ScoreCandidateTests(SimpleTestCase):
    def test_exact_subject_match_scores_one(self):
        self.assertEqual(score_candidate("XZ Andromedae", "Witness XZ Andromedae Wink"), 1.0)

    def test_unmatched_words_drag_the_score_down(self):
        """One of four words matching is what makes this rejectable."""
        score = score_candidate("Night Warriors: Darkstalkers' Revenge", "Saturn at Night")
        self.assertAlmostEqual(score, 0.25)
        self.assertLess(score, MATCH_THRESHOLD)

    def test_partial_match_on_a_two_word_title_scores_half(self):
        score = score_candidate("Mono Lake", "Pink Aurora over Crater Lake")
        self.assertAlmostEqual(score, 0.5)
        self.assertLess(score, MATCH_THRESHOLD)

    def test_substring_bridges_compound_words(self):
        """APOD writes "Fishhead"; Wikipedia titles the page "Fish Head Nebula"."""
        self.assertEqual(
            score_candidate("Fish Head Nebula", "IC 1795: The Fishhead Nebula"), 1.0
        )

    def test_disambiguated_title_scores_on_its_subject_alone(self):
        self.assertEqual(
            score_candidate("Halo (optical phenomenon)", "Ice Halos over Bavaria"), 1.0
        )

    def test_explanation_only_match_is_weighted_below_a_title_match(self):
        """A word mentioned in passing is weak evidence, not proof.

        An explanation of ice halos mentions rainbows; that is exactly how the
        page *Rainbow* was being returned as a confident match.
        """
        explanation = "Ice crystals can produce a display as colorful as a rainbow."
        weak = score_candidate("Rainbow", "Ice Halos over Bavaria", explanation)
        strong = score_candidate("Halo", "Ice Halos over Bavaria", explanation)

        self.assertLess(weak, strong)
        self.assertLess(weak, MATCH_THRESHOLD)
        self.assertGreaterEqual(strong, MATCH_THRESHOLD)

    def test_only_the_opening_of_the_explanation_counts(self):
        """Later paragraphs wander into related topics and cause false matches."""
        far_away = "x " * 400 + "quasar"
        self.assertEqual(score_candidate("Quasar", "Ice Halos over Bavaria", far_away), 0.0)

    def test_candidate_with_no_meaningful_tokens_scores_zero(self):
        self.assertEqual(score_candidate("The", "Saturn at Night"), 0.0)
        self.assertEqual(score_candidate("", "Saturn at Night"), 0.0)


class BestMatchTests(SimpleTestCase):
    def test_picks_the_highest_scorer_regardless_of_position(self):
        candidates = ["Perry Saturn", "Night Warriors: Darkstalkers' Revenge", "Saturn"]
        title, score = best_match(candidates, "Saturn at Night")

        self.assertEqual(title, "Saturn")
        self.assertEqual(score, 1.0)

    def test_ties_keep_mediawikis_own_ranking(self):
        title, _score = best_match(["Andromeda Galaxy", "Andromeda Galaxy"], "M31: The Andromeda Galaxy")
        self.assertEqual(title, "Andromeda Galaxy")

    def test_all_zero_scores_still_report_a_candidate(self):
        """A miss should be diagnosable, so name what was considered."""
        title, score = best_match(["Yara Zgheib"], "Comet NEOWISE over Lebanon")

        self.assertEqual(title, "Yara Zgheib")
        self.assertEqual(score, 0.0)

    def test_no_candidates(self):
        self.assertEqual(best_match([], "Saturn at Night"), (None, 0.0))


class SpecificityTieBreakTests(SimpleTestCase):
    """Equal scores resolve toward the more specific page."""

    def test_specific_page_beats_a_generic_one_at_the_same_score(self):
        apod_title = "The Cat's Eye Nebula from Hubble"
        # Both score 1.0: every word of each is present in the APOD title.
        self.assertEqual(score_candidate("Nebula", apod_title), 1.0)
        self.assertEqual(score_candidate("Cat's Eye Nebula", apod_title), 1.0)

        title, score = best_match(["Nebula", "Cat's Eye Nebula"], apod_title)
        self.assertEqual(title, "Cat's Eye Nebula")
        self.assertEqual(score, 1.0)

    def test_a_higher_score_still_wins_over_greater_coverage(self):
        title, _score = best_match(
            ["Andromeda Galaxy Satellite Companion Survey", "Andromeda Galaxy"],
            "M31: The Andromeda Galaxy",
        )
        self.assertEqual(title, "Andromeda Galaxy")
