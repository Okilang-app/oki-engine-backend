"""SponsorBlock-ML transformer-based sponsor detection.

Loads Xenova/sponsorblock-small from HuggingFace and runs extractive
sponsor detection on Whisper transcript segments.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any, NamedTuple

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

logger = logging.getLogger(__name__)

_CUSTOM_TOKENS = [
    "EXTRACT_SEGMENTS: ",
    "URL_TOKEN",
    "HASHTAG_TOKEN",
    "AT_TOKEN",
    "MUSIC_TOKEN",
    "APPLAUSE_TOKEN",
    "LAUGHTER_TOKEN",
    "NO_SEGMENT_TOKEN",
    "START_SPONSOR_TOKEN",
    "END_SPONSOR_TOKEN",
    "START_SELFPROMO_TOKEN",
    "END_SELFPROMO_TOKEN",
    "START_INTERACTION_TOKEN",
    "END_INTERACTION_TOKEN",
    "BETWEEN_SEGMENTS_TOKEN",
]

_PREFIX = "EXTRACT_SEGMENTS: "

# T5 small has ~512 tokens context
_MODEL_MAX_LEN = 512
_SAFETY_PCT = 0.9765625  # from sponsorblock-ml
_MAX_INPUT_TOKENS = round(_MODEL_MAX_LEN * _SAFETY_PCT)  # ~500
_OVERLAP_PCT = 0.5


class _SponsorMatch(NamedTuple):
    start: float
    end: float
    category: str
    text: str


class SponsorBlockMLDetector:
    """Detect sponsor segments using the SponsorBlock-ML transformer model."""

    def __init__(self, model_name: str = "Xenova/sponsorblock-small", device: str | None = None) -> None:
        self._model_name = model_name
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._tokenizer: AutoTokenizer | None = None
        self._model: AutoModelForSeq2SeqLM | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        logger.info("Loading SponsorBlock-ML model %s on %s", self._model_name, self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self._model_name)
        self._model.to(self._device)
        self._model.eval()
        logger.info("SponsorBlock-ML model loaded (vocab=%s)", len(self._tokenizer))

    @property
    def tokenizer(self) -> AutoTokenizer:
        self._load()
        return self._tokenizer  # type: ignore[return-value]

    @property
    def model(self) -> AutoModelForSeq2SeqLM:
        self._load()
        return self._model  # type: ignore[return-value]

    @property
    def device(self) -> str:
        return self._device

    def detect(
        self,
        segments: list[dict[str, Any]],
        *,
        min_probability: float = 0.5,
    ) -> list[_SponsorMatch]:
        """Run sponsor detection on Whisper transcript segments.

        Args:
            segments: List of dicts with ``start``, ``end``, ``text`` keys.
            min_probability: Minimum confidence threshold (not currently used
                by the base model; reserved for classifier additions).

        Returns:
            List of sponsor matches with ``start``, ``end``, ``category``, ``text``.
        """
        del min_probability  # Base model doesn't return probabilities

        words = _segments_to_words(segments)
        if not words:
            return []

        # Build word batches that fit within the model's token budget
        batches = _build_word_batches(words, self.tokenizer)

        predictions: list[dict[str, Any]] = []
        for batch_words in batches:
            batch_text = " ".join(w["text"] for w in batch_words)
            preds = self._predict_text(batch_text)
            for pred in preds:
                # Map predicted text back to timestamps within the full word list
                matched = _find_text_in_words(words, pred["text"])
                if matched:
                    predictions.append({
                        "start": matched[0]["start"],
                        "end": matched[-1]["end"],
                        "category": pred["category"],
                        "text": pred["text"],
                    })

        # Merge overlapping or adjacent same-category segments
        merged = _merge_predictions(predictions)
        return [_SponsorMatch(**m) for m in merged]

    def _predict_text(self, text: str) -> list[dict[str, str]]:
        input_text = _PREFIX + text
        inputs = self.tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=_MODEL_MAX_LEN,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                inputs.input_ids,
                max_new_tokens=256,
                num_beams=1,
                early_stopping=False,
            )

        decoded = self.tokenizer.decode(outputs[0], skip_special_tokens=False)

        if "NO_SEGMENT_TOKEN" in decoded:
            return []

        # Pattern: START_CATEGORY_TOKEN ... text ... END_CATEGORY_TOKEN
        pattern = r"START_(SPONSOR|SELFPROMO|INTERACTION)_TOKEN\s*(.*?)\s*END_(?:SPONSOR|SELFPROMO|INTERACTION)_TOKEN"
        matches = re.findall(pattern, decoded, re.DOTALL)

        results: list[dict[str, str]] = []
        for category, sponsor_text in matches:
            sponsor_text = sponsor_text.strip()
            if sponsor_text:
                results.append({"category": category.lower(), "text": sponsor_text})
        return results


def _segments_to_words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert segment-level transcript to word-level with estimated timestamps."""
    words: list[dict[str, Any]] = []
    for seg in segments:
        text = seg.get("text", "")
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start))
        word_list = text.split()
        if not word_list:
            continue
        duration = end - start
        word_dur = duration / len(word_list)
        for i, word in enumerate(word_list):
            w_start = start + i * word_dur
            w_end = start + (i + 1) * word_dur
            words.append({"text": word, "start": w_start, "end": w_end})
    return words


def _build_word_batches(
    words: list[dict[str, Any]],
    tokenizer: AutoTokenizer,
) -> list[list[dict[str, Any]]]:
    """Split words into batches that fit within the token budget."""
    # Tokenize each word individually to estimate token counts
    cleaned = [w["text"] for w in words]
    token_info = tokenizer(
        cleaned,
        add_special_tokens=False,
        truncation=True,
        return_attention_mask=False,
        return_length=True,
    )
    num_tokens_list = token_info.length if isinstance(token_info.length, list) else list(token_info.length)

    max_q = round(_SAFETY_PCT * tokenizer.model_max_length)
    buffer_size = round(_OVERLAP_PCT * max_q)

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0

    for word, n_tokens in zip(words, num_tokens_list):
        if current_tokens + n_tokens > max_q and current:
            batches.append(current)
            # Keep overlap buffer
            while current and current_tokens > buffer_size:
                removed = current.pop(0)
                removed_tokens = tokenizer(removed["text"], add_special_tokens=False, return_length=True).length
                if isinstance(removed_tokens, list):
                    removed_tokens = removed_tokens[0]
                current_tokens -= removed_tokens
            current = list(current)  # copy
        current.append(word)
        current_tokens += n_tokens

    if current:
        batches.append(current)

    return batches


def _find_text_in_words(
    words: list[dict[str, Any]],
    target_text: str,
) -> list[dict[str, Any]] | None:
    """Find target text in the word array via fuzzy substring matching.

    The model may slightly paraphrase, so we look for the best matching
    contiguous span of words rather than requiring an exact full-string match.
    """
    target_words = target_text.lower().split()
    if not target_words:
        return None

    word_texts = [w["text"].lower() for w in words]
    n = len(word_texts)
    m = len(target_words)

    best_start = -1
    best_end = -1
    best_score = 0.0

    # Sliding window: try every possible span in words
    for i in range(n):
        for j in range(i + 1, min(i + m + 8, n + 1)):
            span = word_texts[i:j]
            score = _match_score(span, target_words)
            if score > best_score:
                best_score = score
                best_start = i
                best_end = j

    if best_start < 0 or best_score < 0.3:
        return None

    return words[best_start:best_end]


def _match_score(span: list[str], target: list[str]) -> float:
    """Return fuzzy match score between two word lists (0-1)."""
    # Simple overlap ratio: count of shared words / max length
    span_set = set(span)
    target_set = set(target)
    if not span_set or not target_set:
        return 0.0
    overlap = len(span_set & target_set)
    return overlap / max(len(span_set), len(target_set))


def _merge_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge overlapping or same-category adjacent predictions."""
    if not predictions:
        return []

    # Sort by start time
    preds = sorted(predictions, key=lambda x: x["start"])
    merged: list[dict[str, Any]] = [preds[0].copy()]

    for curr in preds[1:]:
        prev = merged[-1]
        # Merge if overlapping or same category within 8 seconds
        if curr["start"] <= prev["end"] or (
            curr["category"] == prev["category"] and curr["start"] - prev["end"] <= 8.0
        ):
            prev["end"] = max(prev["end"], curr["end"])
            prev["text"] += " " + curr["text"]
        else:
            merged.append(curr.copy())

    return merged
