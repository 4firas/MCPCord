import unittest
from unittest.mock import Mock

from mcpcord.analysis import activity, matches_user
from mcpcord.discovery import DiscoveryReader
from mcpcord.live import api_to_export
from mcpcord.live_transport import LiveError
from mcpcord.reader import ReaderError, normalize_message
from tests.test_discovery import GID, UID, guild, scope
from tests.test_live import CID, DM, NOW, SINCE, UNTIL, Clock, message


def normalized(raw=None):
    metadata = {"id": CID, "guild_id": GID}
    return normalize_message(api_to_export(raw or message(), metadata), metadata, NOW.isoformat(), "synthetic")


class AnalysisTests(unittest.TestCase):
    def test_author_mention_reply_and_name_collisions_are_distinct(self):
        raw = message(content=f"{UID} <@{UID}> merely quoted")
        raw["author"]["id"] = "99"
        raw["author"]["username"] = "Ari"
        row = normalized(raw)
        self.assertFalse(matches_user(row, UID))
        self.assertFalse(matches_user(row, UID, "mention"))
        raw["mentions"] = [{"id": UID}]
        self.assertTrue(matches_user(normalized(raw), UID, "mention"))
        raw.update({"type": 19, "message_reference": {"message_id": "7"},
                    "referenced_message": {"id": "7", "author": {"id": UID}}})
        row = normalized(raw)
        self.assertTrue(matches_user(row, UID, "reply"))
        raw["webhook_id"] = "99"
        self.assertFalse(matches_user(normalized(raw), "99", "author"))
        self.assertTrue(matches_user(normalized(raw), UID, "mention"))

    def test_exact_ids_do_not_convert_through_float(self):
        raw = message()
        raw["author"]["id"] = "9007199254740993"
        row = normalized(raw)
        self.assertTrue(matches_user(row, "9007199254740993"))
        self.assertFalse(matches_user(row, "9007199254740992"))
        with self.assertRaises(ReaderError):
            matches_user(row, 9007199254740993)

    def test_missing_content_is_still_observed_activity(self):
        raw = message()
        raw.pop("content")
        row = normalized(raw)
        result = activity([row])
        self.assertEqual(result["visible_message_count"], 1)
        self.assertEqual(result["content_empty_or_unavailable_count"], 1)
        self.assertEqual(row["content_state"], "missing")

    def test_dst_repeated_hours_stay_distinct(self):
        rows = []
        for stamp in ("2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"):
            row = normalized()
            row["timestamp"] = stamp
            rows.append(row)
        result = activity(rows, "America/New_York", bucket="hour")
        self.assertEqual([r["period"] for r in result["activity"]], ["2026-11-01T01:00:00-04:00", "2026-11-01T01:00:00-05:00"])
        self.assertEqual(activity(rows, "America/New_York")["activity"], [{"period": "2026-11-01", "message_count": 2}])

    def test_unresolved_replies_are_not_guessed(self):
        row = normalized()
        row["is_reply"] = True
        result = activity([row], user_id=UID, relationship="reply")
        self.assertEqual(result["visible_message_count"], 0)
        self.assertEqual(result["unresolved_reply_count"], 1)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.client = Clock(), Mock()
        self.client.guilds.return_value = [guild()]
        self.client.current_user.return_value = {"id": "100"}
        self.reader = DiscoveryReader(scope(), client=self.client, now=lambda: NOW, monotonic=self.clock.mono)
        self.reader.list_guilds()

    def search(self, **kwargs):
        return self.reader.search_user_messages(UID, SINCE, UNTIL, guild_id=GID, **kwargs)

    def test_short_search_page_continues_using_limit_not_length(self):
        self.client.search_messages.return_value = {"messages": [[message()]], "total_results": 80}
        first = self.search()["data"]
        self.assertEqual(first["returned_matching"], 1)
        self.assertIsNotNone(first["next_cursor"])
        self.client.search_messages.return_value = {"messages": [], "total_results": 30}
        second = self.search(cursor=first["next_cursor"])["data"]
        self.assertEqual(second["offset"], 25)
        self.assertIsNone(second["next_cursor"])
        self.assertFalse(second["exhaustive"])

    def test_search_offset_limit_is_honest_and_bounded(self):
        self.client.search_messages.return_value = {"messages": [], "total_results": 10001}
        page = self.search()["data"]
        cursor = page["next_cursor"]
        self.reader.search_cursors[cursor]["offset"] = 9975
        final = self.search(cursor=cursor)["data"]
        self.assertTrue(final["search_offset_limit_reached"])
        self.assertIsNone(final["next_cursor"])
        self.assertFalse(final["exhaustive"])

    def test_search_filters_results_by_exact_identity_and_half_open_dates(self):
        wrong_author = message(sequence=2)
        wrong_author["author"]["id"] = "999"
        end = message(sequence=3)
        end["timestamp"] = UNTIL
        webhook = message(sequence=4)
        webhook["webhook_id"] = UID
        self.client.search_messages.return_value = {"messages": [[message()], [wrong_author], [end], [webhook]], "total_results": 4}
        result = self.search()["data"]
        self.assertEqual(result["returned_matching"], 1)
        self.assertEqual(result["excluded_unverified_or_outside_window"], 3)

    def test_search_cursor_rejects_changed_filters_without_network(self):
        self.client.search_messages.return_value = {"messages": [], "total_results": 100}
        cursor = self.search()["data"]["next_cursor"]
        with self.assertRaises(ReaderError):
            self.search(cursor=cursor, relationship="mention")
        self.client.search_messages.assert_called_once()

    def test_search_supports_explicit_old_date_without_live_seven_day_cap(self):
        self.client.search_messages.return_value = {"messages": [], "total_results": 0}
        result = self.reader.search_user_messages(UID, "2016-01-01T00:00:00Z", UNTIL, guild_id=GID)
        self.assertFalse(result["is_error"])

    def test_current_dm_membership_matches_exact_recipient_id(self):
        self.client.direct_channels.return_value = [{"id": DM, "type": 1, "recipients": [{"id": UID, "username": "Ari"}]},
            {"id": "44", "type": 1, "recipients": [{"id": "99", "username": "Ari"}]}]
        result = self.reader.find_user_conversations(UID)["data"]
        self.assertEqual([c["id"] for c in result["conversations"]], [DM])
        self.assertFalse(result["message_history_fetched"])
        self.client.messages.assert_not_called()

    def test_search_indexing_error_is_explicit(self):
        self.client.search_messages.side_effect = LiveError("search_indexing", "Indexing", 2)
        result = self.search()
        self.assertTrue(result["is_error"])
        self.assertEqual(result["data"]["messages"], [])


class SearchTransportTests(unittest.TestCase):
    def client(self, responses):
        from tests.test_discovery import DiscoveryClientTests
        return DiscoveryClientTests().client(responses)

    def test_202_cooldown_then_same_page_can_return_200(self):
        client, transport, _ = self.client([(202, {}, {"retry_after": 2.5}), (200, {}, {"messages": [], "total_results": 0})])
        client.register_guilds([GID])
        with self.assertRaises(LiveError) as error:
            client.search_messages(GID, True, UID, "author", "1", "999", 0, 20)
        self.assertEqual(error.exception.code, "search_indexing")
        self.assertEqual(error.exception.retry_after, 2.5)
        self.assertEqual(client.search_messages(GID, True, UID, "author", "1", "999", 0, 20)["total_results"], 0)
        self.assertEqual(transport.calls[0][1]["author_id"], UID)
        self.assertEqual(transport.calls[0][1], transport.calls[1][1])

    def test_search_dm_must_already_be_discovered(self):
        client, _, credential = self.client([])
        with self.assertRaises(LiveError):
            client.search_messages(DM, False, UID, "author", "1", "999", 0, 20)
        credential.assert_not_called()
