"""Hindi answers for Hindi questions: official English passages shown in Hindi, with their facts checked.

The records are English. When a question is answered in Hindi, the answer's own wording already comes from Hindi
templates (``i18n``); the official passages quoted inside it — FAQ questions and answers, application steps, document
excerpts, scheme descriptions — are translated here, in one batched model call per answer (``groq.translate_to_hindi``).

Names stay as the records write them (IS numbers, standard and product titles, QCO names, laboratories, AHCs), and a
translation is used only when it keeps every fact of the original: each number or amount, IS / S.O. / G.S.R. number,
URL and e-mail address must appear unchanged, and the text must actually be Hindi. Anything that fails, or any
passage when no model is configured, stays in the official English. The evidence drawer always keeps the official
English text, and the answer carries the ``machine_translation`` note whenever a translation is shown.
"""

import re

from manakmarg.core.config import Settings
from manakmarg.normalize.aliases import clean_script
from manakmarg.reasoning import groq

_FACTS = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+|\d+(?:[.,:/]\d+)*")
_DEVANAGARI_LETTER = re.compile("[ऀ-ॣॱ-ॿ]")
_LATIN_LETTER = re.compile("[A-Za-z]")


def _facts(text: str) -> list[str]:
    return [fact.rstrip(".,;)") for fact in _FACTS.findall(clean_script(text))]


def keeps_facts(original: str, translated: str | None) -> bool:
    """True when ``translated`` is Hindi and contains every number, identifier, URL and e-mail of ``original``."""
    if not translated:
        return False
    translated = clean_script(translated)
    devanagari, latin = len(_DEVANAGARI_LETTER.findall(translated)), len(_LATIN_LETTER.findall(translated))
    if devanagari == 0 or devanagari < latin / 3:
        return False
    compact = translated.replace(" ", "")
    return all(fact in translated or fact.replace(" ", "") in compact for fact in _facts(original))


def to_hindi(texts: list[str], settings: Settings) -> dict[str, str]:
    """Checked Hindi translations of ``texts`` (only those that passed); an empty dict without a model."""
    unique = list(dict.fromkeys(text for text in texts if text and _LATIN_LETTER.search(text)))
    if not unique or not settings.groq_api_key:
        return {}
    translated = groq.translate_to_hindi(unique, settings)
    return {original: hindi for original, hindi in zip(unique, translated) if keeps_facts(original, hindi)}
