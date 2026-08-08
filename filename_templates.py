import os
import re


TOKENS = ("KEY", "LOOP NAME", "BPM", "PROD NAME")
# Accept the producer naming variants used in real loop packs: ``145``,
# ``145 BPM`` and the compact ``145bpm`` form.  Keep the numeric value in a
# dedicated group so the optional suffix never leaks into rendered names.
BPM_RE = re.compile(
    r"(?i)(?<!\d)(?P<value>[6-9]\d|1\d{2}|2[0-4]\d)(?:\s*bpm\b|\b)(?!\d)"
)
KEY_AT_START_RE = re.compile(
    r"(?i)^(?P<key>[A-G](?:#|b)?m|[A-G](?:#|b)?(?:\s+(?:major|minor))?)(?:\s+|$)"
)


def parse_loop_filename(filename):
    stem, extension = os.path.splitext(os.path.basename(filename))
    bpm_match = BPM_RE.search(stem)
    if not bpm_match:
        return {
            "KEY": "",
            "BPM": "",
            "LOOP NAME": re.sub(r"(?i)^L\s+", "", stem).strip(),
            "PROD NAME": "",
            "extension": extension or ".mp3",
        }

    before = stem[: bpm_match.start()].strip()
    after = stem[bpm_match.end() :].strip()
    loop_name = re.sub(r"(?i)^L\s+", "", before).strip()
    key = ""
    key_match = KEY_AT_START_RE.match(after)
    if key_match:
        key = key_match.group("key").strip()
        after = after[key_match.end() :].strip()
    return {
        "KEY": key,
        "BPM": bpm_match.group("value"),
        "LOOP NAME": loop_name,
        "PROD NAME": after,
        "extension": extension or ".mp3",
    }


def render_name(parts, token_order, detected_key=None, layer_index=None):
    values = dict(parts)
    if detected_key:
        values["KEY"] = detected_key
    ordered = [values.get(token, "").strip() for token in token_order]
    stem = " ".join(value for value in ordered if value)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = stem.replace("/", "-").replace(":", "-")
    if layer_index is not None:
        stem += f"_L{layer_index}"
    return stem + parts.get("extension", ".mp3")
