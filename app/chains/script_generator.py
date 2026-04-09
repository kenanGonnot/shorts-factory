"""Structured script generation with validation and deterministic fallback."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.chains.state import PipelineState, Script
from app.core.config import get_settings
from app.core.logging import log

SYSTEM_PROMPT = """You write punchy YouTube Shorts scripts.
Match the language of the topic when it is clear. Otherwise use English.
Keep every script tight, specific, and easy to narrate in about 30 seconds."""

USER_PROMPT = """Topic: {topic}

Return a structured script with:
- title: catchy and <= 60 characters
- hook: one scroll-stopping line
- body: 4 short sentences, about 30 to 100 words total
- cta: one short call to action
- tags: exactly 5 short lowercase tags
"""

SCRIPT_PROMPT = ChatPromptTemplate.from_messages(
    [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
)

BODY_SEGMENT_PATTERN = re.compile(r"[.!?]\s+|\n+")
WORD_PATTERN = re.compile(r"\b[\w'-]+\b", re.UNICODE)
NON_TAG_CHAR_PATTERN = re.compile(r"[^a-z0-9-]+")
HYPHEN_PATTERN = re.compile(r"-+")
TOPIC_WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÿ0-9']+", re.UNICODE)

LANGUAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "fr": ("pourquoi", "comment", "avec", "sans", "francais", "cafe", "concentrer"),
    "es": ("por que", "porque", "como", "con", "sin", "cafe", "enfoque"),
    "de": ("warum", "wie", "mit", "ohne", "kaffee", "fokus"),
    "it": ("perche", "come", "con", "senza", "caffe", "concentrazione"),
    "pt": ("por que", "porque", "como", "com", "sem", "cafe", "foco"),
}

LANGUAGE_STOPWORDS: dict[str, set[str]] = {
    "en": {"a", "an", "and", "for", "how", "is", "the", "to", "why", "you"},
    "fr": {"a", "au", "avec", "comment", "de", "des", "du", "et", "la", "le", "les", "pour", "pourquoi", "se", "un", "une"},
    "es": {"como", "con", "de", "el", "en", "la", "las", "los", "para", "por", "que", "sin", "un", "una"},
    "de": {"das", "der", "die", "ein", "eine", "fuer", "mit", "ohne", "und", "warum", "wie"},
    "it": {"con", "come", "e", "gli", "il", "la", "le", "per", "perche", "senza", "un", "una"},
    "pt": {"com", "como", "de", "e", "o", "os", "para", "por", "que", "sem", "um", "uma"},
}

DEFAULT_TAGS: dict[str, tuple[str, ...]] = {
    "en": ("shorts", "explainer", "video", "learn", "facts"),
    "fr": ("shorts", "explication", "video", "apprendre", "faits"),
    "es": ("shorts", "explicacion", "video", "aprender", "hechos"),
    "de": ("shorts", "erklaert", "video", "lernen", "fakten"),
    "it": ("shorts", "spiegato", "video", "impara", "fatti"),
    "pt": ("shorts", "explicacao", "video", "aprender", "fatos"),
}

FALLBACK_COPY: dict[str, dict[str, Any]] = {
    "en": {
        "title_suffix": "explained fast",
        "hook": "{topic} sounds simple, but the real reason is more interesting.",
        "body_lines": (
            "{topic} gets easier when you focus on the core mechanism first.",
            "That cuts through the myth people usually repeat.",
            "Once the main idea clicks, the rest feels much easier to remember.",
            "In one short explanation, you get the part that actually matters.",
        ),
        "cta": "Follow for more quick explainers.",
    },
    "fr": {
        "title_suffix": "explique rapidement",
        "hook": "{topic} semble simple, mais l'explication est plus interessante.",
        "body_lines": (
            "{topic} devient plus clair quand on part de l'idee centrale.",
            "Ca evite de repeter le mythe que tout le monde retient.",
            "Une fois le mecanisme compris, le sujet devient plus facile a memoriser.",
            "En quelques secondes, tu comprends enfin ce qui compte vraiment.",
        ),
        "cta": "Abonne-toi pour plus d'explications rapides.",
    },
    "es": {
        "title_suffix": "explicado rapido",
        "hook": "{topic} parece simple, pero la razon real es mas interesante.",
        "body_lines": (
            "{topic} se entiende mejor cuando miras primero la idea central.",
            "Asi dejas de repetir el mito que suele confundir a todos.",
            "Cuando el mecanismo encaja, el resto del tema se recuerda mejor.",
            "En pocos segundos te quedas con la parte que de verdad importa.",
        ),
        "cta": "Sigue para mas explicaciones rapidas.",
    },
    "de": {
        "title_suffix": "kurz erklaert",
        "hook": "{topic} wirkt simpel, aber der eigentliche Grund ist spannender.",
        "body_lines": (
            "{topic} wird klarer, wenn du zuerst auf den Kernmechanismus schaust.",
            "So vermeidest du den Mythos, den viele einfach wiederholen.",
            "Wenn die Hauptidee sitzt, bleibt der Rest viel leichter haengen.",
            "In wenigen Sekunden bleibt genau das Wesentliche bei dir.",
        ),
        "cta": "Folge fuer mehr schnelle Erklaerstuecke.",
    },
    "it": {
        "title_suffix": "spiegato veloce",
        "hook": "{topic} sembra semplice, ma la vera ragione e piu interessante.",
        "body_lines": (
            "{topic} diventa piu chiaro quando parti dall'idea centrale.",
            "Cosi eviti il mito che di solito tutti ripetono.",
            "Quando capisci il meccanismo, il resto si ricorda molto meglio.",
            "In pochi secondi ti resta la parte che conta davvero.",
        ),
        "cta": "Segui per altre spiegazioni rapide.",
    },
    "pt": {
        "title_suffix": "explicado rapido",
        "hook": "{topic} parece simples, mas a razao real e mais interessante.",
        "body_lines": (
            "{topic} fica mais claro quando voce olha primeiro para a ideia central.",
            "Isso corta o mito que muita gente repete sem pensar.",
            "Quando o mecanismo faz sentido, o resto fica bem mais facil de lembrar.",
            "Em poucos segundos voce guarda a parte que realmente importa.",
        ),
        "cta": "Siga para mais explicacoes rapidas.",
    },
}


class StructuredScript(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=60)
    hook: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=600)
    cta: str = Field(min_length=1, max_length=160)
    tags: list[str] = Field(min_length=5, max_length=5)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized_tags: list[str] = []
        for tag in tags:
            normalized_tag = _slugify_tag(tag)
            if normalized_tag and normalized_tag not in normalized_tags:
                normalized_tags.append(normalized_tag)

        if len(normalized_tags) != 5:
            raise ValueError("tags must contain exactly 5 distinct values")

        return normalized_tags

    @model_validator(mode="after")
    def validate_body_shape(self) -> "StructuredScript":
        segments = _split_body_segments(self.body)
        word_count = len(WORD_PATTERN.findall(self.body))

        if not 4 <= len(segments) <= 6:
            raise ValueError("body must contain 4 to 6 short sentences")
        if not 30 <= word_count <= 100:
            raise ValueError("body must contain about 30 to 100 words")

        return self

    def to_public_script(self) -> Script:
        return {
            "title": self.title,
            "hook": self.hook,
            "body": self.body,
            "cta": self.cta,
            "tags": list(self.tags),
        }


@dataclass(slots=True)
class ScriptGenerator:
    structured_output_factory: Callable[[], Runnable[Any, Any]] | None = None

    def generate_script(self, topic: str) -> Script:
        clean_topic = _clean_topic(topic)
        settings = get_settings()

        if not settings.openai_api_key:
            log.info("script_generator.fallback", reason="missing_openai_api_key", topic=clean_topic)
            return self._build_fallback_script(clean_topic)

        try:
            raw_script = self._build_chain(settings.llm_model, settings.openai_api_key).invoke(
                {"topic": clean_topic}
            )
        except ValidationError:
            raise
        except Exception as exc:
            log.warning(
                "script_generator.fallback",
                reason="llm_invocation_error",
                topic=clean_topic,
                error=str(exc),
            )
            return self._build_fallback_script(clean_topic)

        structured_script = StructuredScript.model_validate(raw_script)
        return structured_script.to_public_script()

    def enrich_state(self, state: PipelineState) -> PipelineState:
        return {**state, "script": self.generate_script(state["topic"])}

    def as_runnable(self) -> Runnable[PipelineState, PipelineState]:
        return RunnableLambda(self.enrich_state, name="ScriptChain")

    def _build_chain(self, model_name: str, api_key: str) -> Runnable[Any, Any]:
        structured_output = (
            self.structured_output_factory()
            if self.structured_output_factory is not None
            else ChatOpenAI(model=model_name, temperature=0.4, api_key=api_key).with_structured_output(
                StructuredScript,
                method="json_schema",
                strict=True,
            )
        )
        return SCRIPT_PROMPT | structured_output

    def _build_fallback_script(self, topic: str) -> Script:
        language = _detect_language(topic)
        copy = FALLBACK_COPY[language]
        structured_script = StructuredScript(
            title=_build_title(topic, copy["title_suffix"]),
            hook=copy["hook"].format(topic=topic),
            body=" ".join(line.format(topic=topic) for line in copy["body_lines"]),
            cta=copy["cta"],
            tags=_build_tags(topic, language),
        )
        return structured_script.to_public_script()


def _build_title(topic: str, suffix: str) -> str:
    separator = " - "
    topic_limit = max(12, 60 - len(separator) - len(suffix))
    short_topic = _truncate(topic, topic_limit)
    return _truncate(f"{short_topic}{separator}{suffix}", 60)


def _build_tags(topic: str, language: str) -> list[str]:
    tags: list[str] = []
    stopwords = LANGUAGE_STOPWORDS.get(language, LANGUAGE_STOPWORDS["en"])

    for raw_word in TOPIC_WORD_PATTERN.findall(topic.lower()):
        if raw_word in stopwords:
            continue
        tag = _slugify_tag(raw_word)
        if tag and tag not in tags:
            tags.append(tag)

    for fallback_tag in DEFAULT_TAGS.get(language, DEFAULT_TAGS["en"]):
        normalized_tag = _slugify_tag(fallback_tag)
        if normalized_tag and normalized_tag not in tags:
            tags.append(normalized_tag)
        if len(tags) == 5:
            return tags

    while len(tags) < 5:
        tags.append(f"tag-{len(tags) + 1}")

    return tags[:5]


def _clean_topic(topic: str) -> str:
    cleaned_topic = re.sub(r"\s+", " ", topic).strip()
    return cleaned_topic or "Untitled topic"


def _detect_language(topic: str) -> str:
    normalized_topic = _normalize_text(topic)
    for language, markers in LANGUAGE_MARKERS.items():
        if any(marker in normalized_topic for marker in markers):
            return language
    return "en"


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _slugify_tag(tag: str) -> str:
    normalized = _normalize_text(str(tag))
    normalized = NON_TAG_CHAR_PATTERN.sub("-", normalized)
    normalized = HYPHEN_PATTERN.sub("-", normalized).strip("-")
    return normalized


def _split_body_segments(body: str) -> list[str]:
    segments = [
        segment.strip(" \n\t.,!?;:-")
        for segment in BODY_SEGMENT_PATTERN.split(body)
        if segment.strip(" \n\t.,!?;:-")
    ]
    return segments


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    truncated = text[: limit - 3].rstrip(" -:,.")
    return f"{truncated}..."
