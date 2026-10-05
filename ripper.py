"""Resolve a public X post into downloadable video and GIF files."""

from __future__ import annotations

import collections
import html
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MEDIA_HOSTS = {"video.twimg.com"}
IMAGE_HOSTS = {"pbs.twimg.com", "abs.twimg.com"}
POST_HOSTS = {
    "x.com",
    "twitter.com",
    "mobile.twitter.com",
    "mobile.x.com",
    "fxtwitter.com",
    "vxtwitter.com",
    "fixupx.com",
    "fixvx.com",
}
STATUS_RE = re.compile(r"/status(?:es)?/(\d+)")
HANDLE_RE = re.compile(r"/([A-Za-z0-9_]{1,15})/status(?:es)?/")
SIZE_RE = re.compile(r"/(\d{2,4})x(\d{2,4})/")


class RipError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _MediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_MediaRedirectHandler)


def syndication_token(tweet_id: str) -> str:
    """Match the embed widget token: ((Number(id) / 1e15) * π).toString(36), minus zeros and dots."""
    value = (int(tweet_id) / 1e15) * math.pi
    rendered = _js_number_to_string(value, 36)
    return rendered.translate(str.maketrans("", "", "0."))


def _js_number_to_string(val: float, radix: int) -> str:
    alphabet = b"0123456789abcdefghijklmnopqrstuvwxyz.-"
    if val == 0:
        return "0"
    result: collections.deque[int] = collections.deque()
    sign = val < 0
    val = abs(val)
    fraction, integer = math.modf(val)
    delta = max(math.nextafter(0.0, math.inf), math.ulp(val) / 2)

    if fraction >= delta:
        result.append(-2)
    while fraction >= delta:
        delta *= radix
        fraction, digit = math.modf(fraction * radix)
        result.append(int(digit))
        needs_rounding = fraction > 0.5 or (fraction == 0.5 and int(digit) & 1)
        if needs_rounding and fraction + delta > 1:
            for index in reversed(range(1, len(result))):
                if result[index] + 1 < radix:
                    result[index] += 1
                    break
                result.pop()
            else:
                integer += 1
            break

    integer, digit = divmod(int(integer), radix)
    result.appendleft(digit)
    while integer > 0:
        integer, digit = divmod(integer, radix)
        result.appendleft(digit)
    if sign:
        result.appendleft(-1)
    return bytes(alphabet[digit] for digit in result).decode("ascii")


def parse_post_url(raw: str) -> dict:
    text = (raw or "").strip()
    if not text or len(text) > 500:
        raise RipError("Paste a link to a public post on X.")
    if re.fullmatch(r"\d{10,22}", text):
        return {"id": text, "handle": None}

    if not re.match(r"https?://", text, re.I):
        text = "https://" + text

    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "t.co":
        text = _resolve_short_link(text)
        parsed = urllib.parse.urlparse(text)
        host = (parsed.hostname or "").lower().removeprefix("www.")

    if host not in POST_HOSTS:
        raise RipError("Paste a link to a public post on X.")

    match = STATUS_RE.search(parsed.path)
    if not match:
        raise RipError("That link doesn't point at a post. Use a status link from X.")

    handle_match = HANDLE_RE.search(parsed.path)
    handle = handle_match.group(1) if handle_match else None
    if handle and handle.lower() in {"i", "web"}:
        handle = None
    return {"id": match.group(1), "handle": handle}


def extract(raw_url: str) -> dict:
    ref = parse_post_url(raw_url)
    syndicated = None
    syndicated_error = None
    try:
        syndicated = _from_syndication(ref["id"])
    except RipError as err:
        syndicated_error = err

    if syndicated and syndicated["items"]:
        return syndicated

    mirrored = None
    try:
        mirrored = _from_fxtwitter(ref["id"], ref.get("handle"))
    except RipError:
        mirrored = None

    if mirrored and mirrored["items"]:
        return mirrored
    if syndicated or mirrored:
        raise RipError("That post doesn't include a video or GIF.", 422)
    if syndicated_error:
        raise syndicated_error
    raise RipError("That post is private, deleted, or unavailable.", 404)


def validate_media_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in MEDIA_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise RipError("That file link isn't allowed.", 400)
    return parsed


def safe_filename(name: str) -> str:
    base = re.sub(r"\.mp4$", "", name or "", flags=re.IGNORECASE)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).strip(".-")
    base = base[:110] or "video"
    return f"{base}.mp4"


def open_media(url: str, range_header: str | None = None):
    validate_media_url(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if range_header:
        headers["Range"] = range_header
    request = urllib.request.Request(url, headers=headers)
    try:
        return OPENER.open(request, timeout=30)
    except urllib.error.HTTPError as err:
        raise RipError("The video file is no longer available.", 502) from err
    except urllib.error.URLError as err:
        raise RipError("The video file could not be reached.", 502) from err


def _resolve_short_link(url: str) -> str:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.geturl()
    except urllib.error.HTTPError as err:
        if err.headers.get("Location"):
            return urllib.parse.urljoin(url, err.headers["Location"])
        raise RipError("That short link could not be opened.", 400) from err
    except urllib.error.URLError as err:
        raise RipError("That short link could not be opened.", 400) from err


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise RipError("That post is private, deleted, or unavailable.", 404) from err
        raise RipError("X didn't respond. Try again in a moment.", 502) from err
    except urllib.error.URLError as err:
        raise RipError("X didn't respond. Try again in a moment.", 502) from err
    except json.JSONDecodeError as err:
        raise RipError("X didn't respond. Try again in a moment.", 502) from err
    if not isinstance(payload, dict):
        raise RipError("X didn't respond. Try again in a moment.", 502)
    return payload


def _from_syndication(tweet_id: str) -> dict:
    query = urllib.parse.urlencode(
        {
            "id": tweet_id,
            "lang": "en",
            "token": syndication_token(tweet_id),
        }
    )
    data = _fetch_json(f"https://cdn.syndication.twimg.com/tweet-result?{query}")
    if data.get("__typename") == "TweetTombstone" or not data.get("id_str"):
        raise RipError("That post is private, deleted, or unavailable.", 404)

    user = data.get("user") or {}
    handle = user.get("screen_name") or None
    items = []
    saw_stream_only = False
    for detail in data.get("mediaDetails") or []:
        item, stream_only = _item_from_media_detail(detail, "post")
        saw_stream_only = saw_stream_only or stream_only
        if item:
            items.append(item)

    quoted = data.get("quoted_tweet") or {}
    if isinstance(quoted, dict):
        for detail in quoted.get("mediaDetails") or []:
            item, stream_only = _item_from_media_detail(detail, "quote")
            saw_stream_only = saw_stream_only or stream_only
            if item:
                items.append(item)

    if not items and saw_stream_only:
        raise RipError(
            "This video is only available as a stream, so there isn't a single file to download.",
            422,
        )

    return _post(
        tweet_id=str(data.get("id_str") or tweet_id),
        handle=handle,
        name=user.get("name") or handle or "X",
        avatar=user.get("profile_image_url_https"),
        text=data.get("text") or "",
        created_at=data.get("created_at"),
        items=items,
    )


def _from_fxtwitter(tweet_id: str, handle: str | None) -> dict:
    urls = [f"https://api.fxtwitter.com/status/{tweet_id}"]
    if handle:
        urls.append(f"https://api.fxtwitter.com/{handle}/status/{tweet_id}")

    last_error = None
    payload = None
    for url in urls:
        try:
            payload = _fetch_json(url)
            break
        except RipError as err:
            last_error = err
    if payload is None:
        raise last_error or RipError("That post is private, deleted, or unavailable.", 404)
    if payload.get("code") not in (200, None) or not isinstance(payload.get("tweet"), dict):
        raise RipError("That post is private, deleted, or unavailable.", 404)

    tweet = payload["tweet"]
    author = tweet.get("author") or {}
    screen_name = author.get("screen_name") or handle
    items = []
    items.extend(_items_from_fx_media(tweet.get("media"), "post"))
    quote = tweet.get("quote") if isinstance(tweet.get("quote"), dict) else None
    if quote:
        items.extend(_items_from_fx_media(quote.get("media"), "quote"))
    return _post(
        tweet_id=str(tweet.get("id") or tweet_id),
        handle=screen_name,
        name=author.get("name") or screen_name or "X",
        avatar=author.get("avatar_url"),
        text=tweet.get("text") or "",
        created_at=tweet.get("created_at"),
        items=items,
    )


def _items_from_fx_media(media: dict | None, origin: str) -> list[dict]:
    if not isinstance(media, dict):
        return []
    source = media.get("all") or media.get("videos") or []
    items = []
    for entry in source:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind not in ("video", "gif"):
            continue
        raw_variants = entry.get("formats") or entry.get("variants") or []
        normalized = []
        for variant in raw_variants:
            if not isinstance(variant, dict):
                continue
            container = (variant.get("container") or "").lower()
            content_type = variant.get("content_type") or ""
            if container in ("m3u8", "hls") or "mpegurl" in content_type:
                continue
            if container and container != "mp4" and "mp4" not in content_type:
                continue
            normalized.append(
                {
                    "url": variant.get("url"),
                    "bitrate": variant.get("bitrate") or 0,
                    "content_type": content_type or "video/mp4",
                }
            )
        if not normalized and entry.get("url"):
            normalized.append(
                {
                    "url": entry.get("url"),
                    "bitrate": 0,
                    "content_type": entry.get("format") or "video/mp4",
                }
            )
        variants = prepare_variants(normalized)
        if not variants:
            continue
        duration = entry.get("duration")
        items.append(
            {
                "type": "gif" if kind == "gif" else "video",
                "origin": origin,
                "thumbnail": _clean_image(entry.get("thumbnail_url")),
                "width": entry.get("width"),
                "height": entry.get("height"),
                "duration_ms": int(float(duration) * 1000) if duration else None,
                "variants": variants,
            }
        )
    return items


def _item_from_media_detail(detail: dict, origin: str) -> tuple[dict | None, bool]:
    if not isinstance(detail, dict):
        return None, False
    kind = detail.get("type")
    if kind not in ("video", "animated_gif"):
        return None, False
    info = detail.get("video_info") or {}
    raw = [v for v in (info.get("variants") or []) if isinstance(v, dict)]
    variants = prepare_variants(raw)
    stream_only = bool(raw) and not variants
    if not variants:
        return None, stream_only
    original = detail.get("original_info") or {}
    return (
        {
            "type": "gif" if kind == "animated_gif" else "video",
            "origin": origin,
            "thumbnail": _clean_image(detail.get("media_url_https")),
            "width": original.get("width"),
            "height": original.get("height"),
            "duration_ms": info.get("duration_millis"),
            "variants": variants,
        },
        False,
    )


def prepare_variants(raw_variants: list[dict]) -> list[dict]:
    cleaned = []
    seen = set()
    for variant in raw_variants:
        content_type = variant.get("content_type") or variant.get("type") or ""
        src = variant.get("url") or variant.get("src") or ""
        if "mpegurl" in content_type or ".m3u8" in src:
            continue
        if "mp4" not in content_type and not re.search(r"\.mp4(?:$|\?)", src):
            continue
        try:
            validate_media_url(src)
        except RipError:
            continue
        if src in seen:
            continue
        seen.add(src)
        width = height = None
        size_match = SIZE_RE.search(urllib.parse.urlparse(src).path)
        if size_match:
            width = int(size_match.group(1))
            height = int(size_match.group(2))
        bitrate = variant.get("bitrate") or 0
        try:
            bitrate = int(bitrate)
        except (TypeError, ValueError):
            bitrate = 0
        cleaned.append(
            {
                "url": src,
                "bitrate": bitrate,
                "width": width,
                "height": height,
                "content_type": "video/mp4",
            }
        )

    cleaned.sort(key=lambda item: (_quality_rank(item), item["bitrate"]), reverse=True)
    labels = [_quality_label(item) for item in cleaned]
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    for item, label in zip(cleaned, labels):
        if counts[label] > 1 and item["bitrate"]:
            item["label"] = f"{label} · {_format_bitrate(item['bitrate'])}"
        else:
            item["label"] = label
    return cleaned


def _quality_rank(item: dict) -> int:
    if item["width"] and item["height"]:
        return min(item["width"], item["height"])
    return 0


def _quality_label(item: dict) -> str:
    rank = _quality_rank(item)
    if rank:
        return f"{rank}p"
    if item["bitrate"]:
        return _format_bitrate(item["bitrate"])
    return "MP4"


def _format_bitrate(bitrate: int) -> str:
    if bitrate >= 1_000_000:
        value = bitrate / 1_000_000
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"{text} Mbps"
    if bitrate >= 1000:
        return f"{round(bitrate / 1000)} kbps"
    return f"{bitrate} bps"


def _clean_image(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in IMAGE_HOSTS:
        return None
    return url.replace("_normal.", "_400x400.")


def _post(tweet_id, handle, name, avatar, text, created_at, items) -> dict:
    handle = handle or None
    permalink = (
        f"https://x.com/{handle}/status/{tweet_id}"
        if handle
        else f"https://x.com/i/status/{tweet_id}"
    )
    safe_text = html.unescape(text or "").strip()
    if len(safe_text) > 12000:
        safe_text = safe_text[:12000].rstrip() + "…"
    return {
        "id": tweet_id,
        "url": permalink,
        "text": safe_text,
        "created_at": created_at,
        "author": {
            "name": name or "X",
            "handle": handle,
            "avatar": _clean_image(avatar),
        },
        "items": items,
    }
