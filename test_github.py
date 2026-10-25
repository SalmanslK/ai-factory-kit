"""
Tests for factory/github.py: which reviews count as an approval of the pull request's current commit.

    python -m unittest test_github -v        (from the kit folder)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "factory"))

import github  # noqa: E402

PR = {"author": "alice", "commit": "c2", "branch": "feature/x"}


def review(login: str, state: str, commit: str, at: str) -> dict:
    return {"user": {"login": login}, "state": state, "commit_id": commit, "submitted_at": at}


class ApproversTests(unittest.TestCase):
    def test_an_approval_of_the_current_commit_counts(self):
        self.assertEqual(github.approvers(PR, [review("bob", "APPROVED", "c2", "1")], set()), ["bob"])

    def test_an_approval_of_an_older_commit_does_not(self):
        self.assertEqual(github.approvers(PR, [review("bob", "APPROVED", "c1", "1")], set()), [])

    def test_the_author_never_counts(self):
        self.assertEqual(github.approvers(PR, [review("Alice", "APPROVED", "c2", "1")], set()), [])

    def test_an_excluded_identity_never_counts(self):
        self.assertEqual(github.approvers(PR, [review("ci-bot", "APPROVED", "c2", "1")], {"CI-Bot"}), [])

    def test_a_later_change_request_replaces_an_approval(self):
        reviews = [review("bob", "APPROVED", "c2", "1"), review("bob", "CHANGES_REQUESTED", "c2", "2")]
        self.assertEqual(github.approvers(PR, reviews, set()), [])

    def test_a_later_comment_does_not_remove_an_approval(self):
        reviews = [review("bob", "APPROVED", "c2", "1"), review("bob", "COMMENTED", "c2", "2")]
        self.assertEqual(github.approvers(PR, reviews, set()), ["bob"])

    def test_a_dismissed_approval_is_gone(self):
        reviews = [review("bob", "APPROVED", "c2", "1"), review("bob", "DISMISSED", "c2", "2")]
        self.assertEqual(github.approvers(PR, reviews, set()), [])

    def test_two_approvers_are_both_listed_once(self):
        reviews = [review("bob", "APPROVED", "c2", "1"), review("carol", "APPROVED", "c2", "2"),
                   review("bob", "APPROVED", "c2", "3")]
        self.assertEqual(sorted(github.approvers(PR, reviews, set())), ["bob", "carol"])


class RepositoryTests(unittest.TestCase):
    def test_remote_urls_are_read_in_https_and_ssh_forms(self):
        for url in ("https://github.com/owner/name.git", "git@github.com:owner/name.git", "https://github.com/owner/name"):
            match = github.REMOTE.search(url)
            self.assertIsNotNone(match, url)
            self.assertEqual(match.group("repo"), "owner/name")

    def test_a_bitbucket_remote_is_not_github(self):
        self.assertIsNone(github.REMOTE.search("https://bitbucket.org/owner/name.git"))


if __name__ == "__main__":
    unittest.main()
