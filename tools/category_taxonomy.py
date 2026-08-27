#!/usr/bin/env python3
"""Canonical research taxonomy for the post-review layer-role model."""

from __future__ import annotations


TRAINABLE_CATEGORIES = (
    "Arp",
    "Bass",
    "Bells",
    "Chords",
    "Counter",
    "Guitar Chords",
    "Keys",
    "Lead",
    "Pad",
    "Piano",
    "Pluck",
    "Strings",
    "Texture",
    "Vocal Chop",
)

FOLDER_LABEL_ALIASES = {
    "Rhythmic Pluck": "Pluck",
    "Perc:drums": "OUT_OF_SCOPE_PERC_DRUMS",
    "Perc Drums": "OUT_OF_SCOPE_PERC_DRUMS",
}

OUT_OF_SCOPE_LABELS = ("OUT_OF_SCOPE_PERC_DRUMS",)


def canonical_folder_label(folder_name: str) -> str:
    return FOLDER_LABEL_ALIASES.get(folder_name, folder_name)
