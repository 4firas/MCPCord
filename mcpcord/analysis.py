"""Deterministic visible-message analysis; no presence or personal-attribute inference."""
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .reader import ReaderError, snowflake, text_field, timestamp


def matches_user(message, user_id, relationship="author", lookup=None):
    snowflake(user_id)
    if relationship == "author":
        return message["author"]["id"] == user_id and message.get("author_kind") != "webhook"
    if relationship == "mention":
        return user_id in message.get("mention_ids", [])
    if relationship != "reply":
        raise ReaderError("Select author, mention or reply matching.")
    if not message.get("is_reply"):
        return False
    if message.get("reply_to_user_id") is not None:
        return message["reply_to_user_id"] == user_id
    ref = message.get("reference")
    if ref and lookup:
        original = lookup(ref.get("channelId") or message["channel_id"], ref.get("messageId"))
        return bool(original and matches_user(original, user_id, "author"))
    return False


def activity(rows, timezone_name="UTC", user_id=None, relationship="author", bucket="day"):
    text_field(timezone_name, 128)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ReaderError("Use an installed IANA timezone, such as UTC or America/New_York.") from None
    if bucket not in ("day", "hour") or relationship not in ("author", "mention", "reply"):
        raise ReaderError("Choose a day/hour bucket and author/mention/reply relationship.")
    if user_id is not None:
        snowflake(user_id)
    counts: Counter[str] = Counter()
    authors: Counter[tuple[str, str]] = Counter()
    channels: Counter[str] = Counter()
    total = unavailable = unresolved_replies = 0
    samples: list[str] = []
    first = last = None
    for row in rows:
        if user_id is not None and not matches_user(row, user_id, relationship):
            unresolved_replies += bool(row.get("is_reply") and row.get("reply_to_user_id") is None and relationship == "reply")
            continue
        local = datetime.fromisoformat(timestamp(row["timestamp"]).replace("Z", "+00:00")).astimezone(zone)
        # Include offset to distinguish repeated hours when daylight saving time ends.
        key = local.date().isoformat() if bucket == "day" else local.replace(minute=0, second=0, microsecond=0).isoformat()
        counts[key] += 1
        authors[(row["author"]["id"], row.get("author_kind", "user"))] += 1
        channels[row["channel_id"]] += 1
        total += 1
        unavailable += row.get("content_state") != "present"
        first = min(first, row["timestamp"]) if first else row["timestamp"]
        last = max(last, row["timestamp"]) if last else row["timestamp"]
        if len(samples) < 10:
            samples.append(row["source_url"])
        if len(counts) > 20000 or len(authors) > 100000 or len(channels) > 10000:
            raise ReaderError("Analysis group limit reached; narrow the date or channel scope.")
    return {"timezone": timezone_name, "bucket": bucket, "user_id": user_id, "relationship": relationship,
            "visible_message_count": total, "content_empty_or_unavailable_count": unavailable,
            "unresolved_reply_count": unresolved_replies, "first_message_at": first, "last_message_at": last,
            "activity": [{"period": key, "message_count": value} for key, value in sorted(counts.items())],
            "authors": [{"user_id": key[0], "author_kind": key[1], "message_count": count}
                        for key, count in authors.most_common(50)], "authors_truncated": len(authors) > 50,
            "channels": [{"channel_id": key, "message_count": count} for key, count in channels.most_common(100)],
            "channels_truncated": len(channels) > 100, "example_source_urls": samples,
            "interpretation": "Counts describe observed messages only, not online presence, private location, availability, relationships or sensitive attributes. Empty/redacted content still counts as message activity. Missing periods do not prove inactivity."}
