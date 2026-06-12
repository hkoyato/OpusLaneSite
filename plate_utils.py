"""
Shared utilities for license plate text processing.
Normalization, edit distance, and similarity functions used by
both the OCR aggregator and the main deduplication logic.
"""

from __future__ import annotations

import numpy as np

# Map visually similar characters to a canonical form
_CHAR_MAP = {
    "O": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "S": "5",
    "B": "8",
    "G": "6",
    "7": "1",
}


def normalize_plate(text: str) -> str:
    """Normalize plate text by mapping OCR-confusable characters to canonical forms."""
    return "".join(_CHAR_MAP.get(ch, ch) for ch in text.upper())


def edit_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance."""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )
    return dp[m][n]


def plates_are_similar(plate_a: str, plate_b: str) -> bool:
    """
    Check if two plate texts are likely the same plate with OCR errors.

    Accounts for:
    - Common character confusions (1<->7, 0<->O, 5<->S, 8<->B, I<->1)
    - Extra leading/trailing characters from noise
    - Standard edit distance
    """
    a = plate_a.upper()
    b = plate_b.upper()

    if a == b:
        return True

    norm_a = normalize_plate(a)
    norm_b = normalize_plate(b)
    if norm_a == norm_b:
        return True

    if norm_a in norm_b or norm_b in norm_a:
        return True

    if len(a) > len(b):
        longer, shorter = norm_a, norm_b
    else:
        longer, shorter = norm_b, norm_a

    if len(longer) - len(shorter) <= 2:
        for start in range(len(longer) - len(shorter) + 1):
            substr = longer[start:start + len(shorter)]
            if substr == shorter:
                return True

    dist = edit_distance(norm_a, norm_b)
    max_len = max(len(norm_a), len(norm_b))
    if max_len == 0:
        return True

    threshold = max(2, int(max_len * 0.3))
    return dist <= threshold


def pick_best_plate(plate_texts: list[str]) -> str:
    """
    From a group of similar plate texts, pick the most likely correct one.
    Prefers shorter plates when one is a substring of another (extra chars = noise).
    """
    if len(plate_texts) == 1:
        return plate_texts[0]

    freq = {}
    for t in plate_texts:
        freq[t] = freq.get(t, 0) + 1

    unique_texts = list(set(plate_texts))
    unique_texts.sort(key=len)

    for i, shorter in enumerate(unique_texts):
        norm_short = normalize_plate(shorter)
        for j in range(i + 1, len(unique_texts)):
            longer = unique_texts[j]
            norm_long = normalize_plate(longer)
            if norm_short in norm_long:
                return shorter

    return max(unique_texts, key=lambda t: (freq.get(t, 0), -len(t)))


def align_partial_plates(readings: list[str]) -> str:
    """
    Stitch partial plate readings into a complete plate using sequence alignment.

    When a plate is partially occluded across frames, different portions may be
    visible at different times. This aligns overlapping fragments and fills gaps.

    For example:
    - ["ABC", "BC12", "C1234"] -> "ABC1234"
    - ["AB_34", "ABC_4", "A_C34"] -> "ABC34"
    """
    if not readings:
        return ""
    if len(readings) == 1:
        return readings[0]

    # Sort by length descending — start with the longest reading as anchor
    sorted_readings = sorted(readings, key=len, reverse=True)
    result = sorted_readings[0]

    for reading in sorted_readings[1:]:
        result = _merge_overlapping(result, reading)

    return result


def _merge_overlapping(base: str, fragment: str) -> str:
    """
    Merge a fragment into the base string by finding the best overlap.
    Tries all possible alignments and picks the one with the most character matches.
    """
    if not fragment:
        return base
    if not base:
        return fragment

    norm_base = normalize_plate(base)
    norm_frag = normalize_plate(fragment)

    best_score = -1
    best_result = base
    base_len = len(base)
    frag_len = len(fragment)

    # Try all offsets where fragment could align with base
    # offset: position in result where fragment starts relative to base start
    for offset in range(-(frag_len - 1), base_len):
        matches = 0
        total_overlap = 0

        for i in range(frag_len):
            base_idx = offset + i
            if 0 <= base_idx < base_len:
                total_overlap += 1
                nb = norm_base[base_idx] if base_idx < len(norm_base) else ""
                nf = norm_frag[i] if i < len(norm_frag) else ""
                if nb == nf:
                    matches += 1

        if total_overlap == 0:
            continue

        # Require at least 50% overlap agreement
        if matches / total_overlap < 0.5:
            continue

        score = matches

        if score > best_score:
            best_score = score
            # Build merged result
            start = min(0, offset)
            end = max(base_len, offset + frag_len)
            merged = list(base)

            # Extend left if needed
            if offset < 0:
                merged = list(fragment[:(-offset)]) + merged

            # Extend right if needed
            right_extend = (offset + frag_len) - base_len
            if right_extend > 0:
                merged = merged + list(fragment[frag_len - right_extend:])

            # Fill in characters from fragment where base might have gaps
            for i in range(frag_len):
                merged_idx = i + max(0, offset) + (abs(min(0, offset)))
                if offset < 0:
                    merged_idx = i
                else:
                    merged_idx = offset + i
                if 0 <= merged_idx < len(merged):
                    if not merged[merged_idx].isalnum():
                        merged[merged_idx] = fragment[i]

            best_result = "".join(merged)

    return best_result
