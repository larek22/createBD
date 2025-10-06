# -*- coding: utf-8 -*-
"""
ГК РФ — GUI-индексатор (RTF/PDF/DOCX/TXT) → Qdrant + OpenAI
Версия v4.0 (release):
- Полностью обновлённый интерфейс на PySide6 с современным тёмным стилем и боковой навигацией.
- Подсказки и пояснения к каждой настройке: от импорта до поиска и Vector Lab.
- Расширенный анализ исходных документов, визуальные карточки результатов и Vector Lab для экспериментов.
- Stream upsert (батчами) без роста RAM; кэш эмбеддингов (SQLite).
- Переключатель HyDE; адаптивный вес title для «ст. NNN».
- Ленивая прогревка кэша + индикатор; кнопка «Очистить кэш».
- Квантизация (int8) — опционально; по умолчанию OFF ради точности.
- Строгий as-of (двойной OR-фильтр) сохранён; клиентский префильтр опционален.
- Валидация dim эмбеддинга vs VECTOR_SIZE; понятные подсказки об ошибках.
- Логи с ротацией; защита от дублирования хендлеров.
- CLI-режим для headless индексации (--cli).

Примечание по ключам:
- Рекомендуется задавать OPENAI_API_KEY через переменную окружения.
- Для тестов можно вписать плейсхолдер (реальный ключ не коммитить).
"""

import os
import sys
import uuid
import hashlib
import json
import html
import re
import importlib
import logging
from logging.handlers import TimedRotatingFileHandler
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

# ---- Qt ----
from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtCore import Qt

# ---- RTF parsers (robust import) ----
try:
    from striprtf import rtf_to_text as _rtf_to_text
    def rtf_to_text(s: str) -> str:
        return _rtf_to_text(s)
except Exception:
    try:
        spec = importlib.util.find_spec("striprtf.striprtf")
        if spec:
            from striprtf.striprtf import rtf_to_text as _rtf_to_text2
            def rtf_to_text(s: str) -> str:
                return _rtf_to_text2(s)
        else:
            raise ImportError
    except Exception:
        def rtf_to_text(s: str) -> str:
            s = s.replace("\r", "\n")
            s = re.sub(r"\\par[d]?", "\n", s)
            s = re.sub(r"\\[a-zA-Z]+-?\d* ?|\\'[0-9a-fA-F]{2}", "", s)
            s = re.sub(r"[{}]", "", s)
            s = re.sub(r"[ \t]+", " ", s)
            return s.strip()

import fitz  # PyMuPDF
from docx import Document as DocxDocument

# ---- Qdrant & OpenAI ----
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct
)
from openai import OpenAI

# ---- Utils ----
from dateutil import parser as dtparser
import sqlite3, pickle, threading, time, argparse, gc
from random import random
from functools import lru_cache

# ============================
# Константы и паттерны
# ============================
APP_DIR = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
QDRANT_PATH = os.path.join(APP_DIR, "qdrant_local")  # замените при необходимости

# Впиши свой ключ при желании (или вводи в GUI/ENV)
OPENAI_API_KEY_DEFAULT = ""  # пример: "sk-..."

EMBED_MODEL = "text-embedding-3-large"  # 3072-мерный вектор
EMB_CLAMP_VERSION = "v1"  # менять при изменении стратегии усечки
CHAT_RERANK_MODEL_CANDIDATES = ["gpt-5-mini", "gpt-5-nano", "gpt-4.1-mini", "gpt-4o-mini"]
ENRICH_MODEL = "gpt-5-nano"  # для обогащения summary

VECTOR_SIZE = 3072
BASE_COLLECTION = "gk_full"
COLL_ARTICLES = f"{BASE_COLLECTION}_articles"  # named vectors (title_vec + body_vec)
COLL_CHUNKS   = f"{BASE_COLLECTION}_chunks"    # named vectors (title_vec + body_vec)

APP_STYLESHEET = """
* {
    font-family: 'Inter', 'Segoe UI', 'SF Pro Display', sans-serif;
    font-size: 14px;
}
QWidget {
    background-color: #0b1120;
    color: #e2e8f0;
}
QScrollArea {
    background: transparent;
    border: none;
}
QLabel#Headline {
    font-size: 30px;
    font-weight: 700;
    letter-spacing: 0.5px;
    padding-bottom: 10px;
}
QLabel#SubHeadline {
    font-size: 16px;
    color: #94a3b8;
}
QLabel#SectionTitle {
    font-size: 19px;
    font-weight: 600;
    color: #f8fafc;
    margin-bottom: 8px;
}
QLabel#OptionLabel {
    font-weight: 600;
    color: #f1f5f9;
}
QLabel#OptionHint {
    color: #9ca3af;
    line-height: 1.45em;
}
QFrame#Card {
    background-color: rgba(15, 23, 42, 0.68);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 16px;
    padding: 20px;
}
QFrame#HeroCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1d4ed8,
        stop:1 #0ea5e9);
    border-radius: 22px;
    padding: 26px;
    color: #f8fafc;
}
QListWidget#NavigationList {
    background-color: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 18px;
    padding: 12px;
}
QListWidget#NavigationList::item {
    margin: 4px 2px;
    padding: 12px 14px;
    border-radius: 12px;
}
QListWidget#NavigationList::item:selected {
    background-color: rgba(59, 130, 246, 0.25);
    color: #f8fafc;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #2563eb,
        stop:1 #1d4ed8);
    border-radius: 12px;
    padding: 10px 18px;
    font-weight: 600;
    color: #f8fafc;
    border: none;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #3b82f6,
        stop:1 #2563eb);
}
QPushButton:disabled {
    background-color: #1e293b;
    color: #64748b;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox,
QDoubleSpinBox, QDateEdit {
    background-color: rgba(15, 23, 42, 0.82);
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: rgba(59, 130, 246, 0.45);
}
QTextBrowser {
    background-color: rgba(9, 14, 26, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    padding: 14px;
}
QTableWidget {
    background-color: rgba(9, 14, 26, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 14px;
    gridline-color: rgba(148, 163, 184, 0.18);
}
QHeaderView::section {
    background-color: rgba(30, 41, 59, 0.95);
    color: #e2e8f0;
    padding: 8px;
    border: none;
}
QProgressBar {
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 12px;
    background-color: rgba(15, 23, 42, 0.7);
    text-align: center;
    color: #cbd5f5;
}
QProgressBar::chunk {
    border-radius: 12px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #3b82f6,
        stop:1 #38bdf8);
}
"""

ARTICLE_HDR_RE = re.compile(r"(?m)^\s*Статья\s+(\d+(?:\.\d+)*)\s*\.?\s*(.+)?$")
CHAPTER_HDR_RE = re.compile(r"(?m)^\s*Глава\s+(\d+(?:\.\d+)*)\s*\.?\s*(.+)?$")

# Расширенная ссылка: пункт/часть/абзац + статья, диапазоны, «и», перечисления
REF_RE = re.compile(
    r"(?ix)"
    r"(?:(?:абз\.|абзац)\s*\d+\s*)?"
    r"(?:(?:пп?\.|пункты?)\s*\d+(?:\.\d+)?(?:\s*(?:,|и)\s*\d+(?:\.\d+)?)*\s*)?"
    r"(?:(?:ч\.|част[ьи])\s*\d+\s*)?"
    r"(?:ст\.?|стать[ьяе])\s*"
    r"(\d+(?:\.\д+)*)(?:\s*[-–]\s*(\д+(?:\.\д+)*))?"
)

# Embedding safety
MAX_EMB_TOKENS = 8000  # безопасный лимит для text-embedding-3-large

# ============================
# Логгер
# ============================
LOG_DIR = os.path.join(APP_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "app.log")

logger = logging.getLogger("gk_indexer")
logger.setLevel(logging.INFO)
if not logger.handlers:  # защита от дублирования хендлеров
    fh = TimedRotatingFileHandler(LOG_PATH, when="midnight", backupCount=7, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

# ============================
# Текстовые утилиты
# ============================
def norm_text(s: str) -> str:
    s = s.replace("\u00A0", " ").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def clean_for_embedding(s: str) -> str:
    s = re.sub(r"(?m)^\s*Статья\s+\d+(?:\.\d+)?\s*\.? .*$", "", s)
    s = re.sub(r"\([^)()]{0,120}?\d{4}[^()]{0,120}?\)", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def extract_keywords(text: str, topn=8) -> List[str]:
    words = [w.lower() for w in re.findall(r"[А-Яа-яA-Za-z]{4,}", text)]
    stop = {"российской","федерации","настоящего","кодекса","статья","глава","часть",
            "согласно","который","которые","иной","других","является","вправе",
            "предусмотренных","установленных","настоящей","закона"}
    freq: Dict[str,int] = {}
    for w in words:
        if w in stop: continue
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq, key=freq.get, reverse=True)[:topn]


def analyze_text_content(text: str) -> Dict[str, Any]:
    """Вычисляет ключевые метрики для документа, чтобы подсказать пользователю,
    насколько текст готов к векторизации."""
    clean = norm_text(text)
    length_chars = len(clean)
    words = re.findall(r"[А-Яа-яA-Za-z]{2,}", clean)
    word_count = len(words)
    unique_words = len(set(w.lower() for w in words))
    paragraphs = [p for p in clean.split("\n") if p.strip()]
    para_count = len(paragraphs)
    avg_para_len = round(word_count / max(1, para_count), 1)
    references = extract_references(clean)
    keywords = extract_keywords(clean, topn=10)
    rough_tokens_val = CorpusBuilder.rough_tokens(clean) if word_count else 0

    warnings: List[str] = []
    if rough_tokens_val > MAX_EMB_TOKENS:
        warnings.append(
            f"Текст превышает безопасный лимит токенов ({rough_tokens_val}>{MAX_EMB_TOKENS})."
        )
    if para_count < 3:
        warnings.append("Мало абзацев — возможно, потребуется ручная разбивка.")
    if not references:
        warnings.append("Не обнаружены ссылки на статьи — проверьте корректность исходника.")

    return {
        "length_chars": length_chars,
        "word_count": word_count,
        "unique_words": unique_words,
        "paragraphs": para_count,
        "avg_paragraph_words": avg_para_len,
        "rough_tokens": rough_tokens_val,
        "references": references,
        "keywords": keywords,
        "warnings": warnings,
    }


def make_summary(text: str) -> str:
    t = text.strip()
    line = t.split("\n", 1)[0]
    return (line[:200] + "…") if len(line) > 200 else line


def expand_range(a: str, b: Optional[str]) -> List[str]:
    if not b: return [a]
    if "." in a or "." in b:
        return [a, b]
    try:
        x, y = int(a), int(b)
        if y < x: x, y = y, x
        return [str(i) for i in range(x, y + 1)]
    except:
        return [a, b] if b else [a]


def extract_references(text: str) -> List[str]:
    refs = []
    for a, b in REF_RE.findall(text):
        refs.extend(expand_range(a, b))
    for m in re.findall(r"статьями?\s+(\d+(?:\.\d+)?)(?:\s*(?:,|и)\s*(\d+(?:\.\д+)?))+", text, flags=re.IGNORECASE):
        extra = re.findall(r"(?:,|и)\s*(\d+(?:\.\д+)?)", m[0], flags=re.IGNORECASE)
        if extra:
            refs.append(m[0])
            refs.extend(extra)
    return sorted(set(refs), key=lambda x: (len(x.split(".")), x))


def auto_detect_part(filename: str) -> Optional[str]:
    name = os.path.basename(filename).lower()
    if "перва" in name: return "часть первая"
    if "втора" in name: return "часть вторая"
    if "треть" in name: return "часть третья"
    if "четверт" in name: return "часть четвертая"
    return None


def safe_html(s):
    return html.escape(str(s or ""))


# ---------- Embedding safety helpers ----------
def _rough_tokens(s: str) -> int:
    return int(len(s.split()) * 1.2)


def clamp_for_embedding(s: str, max_tokens: int = MAX_EMB_TOKENS) -> str:
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    s = s.replace("\x00", " ").strip()
    rough = _rough_tokens(s)
    if rough <= max_tokens:
        return s
    target_words = max(1, int(max_tokens / 1.2))
    trimmed = " ".join(s.split()[:target_words]).strip()
    try:
        logger.debug(f"[EMB-CLAMP] tokens≈{rough} → {max_tokens}, cut_words={target_words}")
    except Exception:
        pass
    return trimmed


def to_iso_dt_start(d: Optional[str]) -> Optional[str]:
    if not d: return None
    try:
        x = dtparser.parse(d).date()
        return f"{x.isoformat()}T00:00:00Z"
    except:
        return None


def to_iso_dt_end(d: Optional[str]) -> Optional[str]:
    if not d: return None
    try:
        x = dtparser.parse(d).date()
        return f"{x.isoformat()}T23:59:59Z"
    except:
        return None

# ============================
# File parsers
# ============================
def parse_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_rtf_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return rtf_to_text(f.read())


def parse_pdf(path: str) -> str:
    parts = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def parse_docx(path: str) -> str:
    doc = DocxDocument(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text_from_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".rtf":  return parse_rtf_file(path)
    if ext == ".pdf":  return parse_pdf(path)
    if ext == ".docx": return parse_docx(path)
    if ext == ".txt":  return parse_txt(path)
    raise ValueError(f"Неподдерживаемый формат: {ext}")


# ============================
# Data model
# ============================
@dataclass
class LawDoc:
    id: str
    level: str                 # "article" | "chunk"
    code: str
    part: Optional[str]
    chapter: Optional[str]
    article: Optional[str]
    title: str
    semantic_summary: str
    topics: List[str]
    references: List[str]
    formatted_text: str
    title_text: str
    text: str
    source: str
    anchor: str
    created_at: str
    text_sha256: str
    effective_from: Optional[str] = None   # ISO 8601
    effective_to: Optional[str] = None     # ISO 8601
    status: Optional[str] = "действует"


# ============================
# Corpus builder
# ============================
class CorpusBuilder:
    def __init__(self, chunk_tokens=800, overlap=120):
        self.chunk_tokens = chunk_tokens
        self.overlap = overlap

    @staticmethod
    def rough_tokens(s: str) -> int:
        return int(len(s.split()) * 1.2)

    def sliding_chunks(self, s: str) -> List[str]:
        paras = [p.strip() for p in s.split("\n") if p.strip()]
        chunks, buf, tokens = [], [], 0
        for para in paras:
            pt = self.rough_tokens(para)
            if tokens + pt > self.chunk_tokens and buf:
                chunks.append("\n".join(buf).strip())
                if self.overlap > 0:
                    rev, tk = [], 0
                    for x in reversed(buf):
                        tk += self.rough_tokens(x)
                        rev.append(x)
                        if tk >= self.overlap: break
                    buf = list(reversed(rev))
                    tokens = sum(self.rough_tokens(x) for x in buf)
                else:
                    buf, tokens = [], 0
            buf.append(para)
            tokens += pt
        if buf:
            chunks.append("\n".join(buf).strip())
        return chunks

    @staticmethod
    def split_articles(text: str) -> List[Tuple[str, str, str]]:
        text = norm_text(text)
        txt = re.sub(r"(?m)^\s*СТАТЬЯ\s+(\d+(?:\.\д+)*)\s*(.+)?$", lambda m: "Статья " + m.group(1) + " " + (m.group(2) or ""), text)
        matches = list(ARTICLE_HDR_RE.finditer(txt))
        if not matches:
            return [("", "", text)]
        out = []
        for i, m in enumerate(matches):
            a_num = m.group(1)
            header_line = m.group(0).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(txt)
            body = txt[start:end].strip()
            if len(body) < 80 and len(header_line) < 120:
                continue
            out.append((a_num, header_line, (header_line + "\n" + body).strip()))
        return out

    def prepare_docs(
        self, *, full_text: str, code_name: str, part_name: Optional[str], title: str, source_path: str,
        effective_from: Optional[str]=None, effective_to: Optional[str]=None, status: Optional[str]="действует"
    ) -> Tuple[List[LawDoc], List[LawDoc]]:
        text = norm_text(full_text)
        created = datetime.utcnow().isoformat() + "Z"
        chunks: List[LawDoc] = []
        articles: List[LawDoc] = []

        eff_from_iso = to_iso_dt_start(effective_from)
        eff_to_iso   = to_iso_dt_end(effective_to)
        status_val   = status

        chapter_splits = list(CHAPTER_HDR_RE.finditer(text))
        def mk_title_text(part, chap, art, ttl):
            left = []
            if ttl: left.append(ttl)
            if part: left.append(part)
            if chap: left.append(f"Глава {chap}")
            if art: left.append(f"Статья {art}")
            return " · ".join(left)

        def mk_docs_for_article(a_num, ch_num, art_clean, art_refs):
            art_sum  = make_summary(art_clean)
            art_topics = extract_keywords(art_clean)
            title_text = mk_title_text(part_name, ch_num, a_num or None, title)
            fmt = f"📘 {title}\n{part_name or ''}\n" + (f"Глава {ch_num}, " if ch_num else "") + f"Статья {a_num or '—'}\n\n{art_clean}"
            art_sha = sha256_text(art_clean)
            articles.append(LawDoc(
                id=str(uuid.uuid4()), level="article",
                code=code_name, part=part_name, chapter=ch_num, article=a_num or None,
                title=title, semantic_summary=art_sum, topics=art_topics, references=art_refs,
                formatted_text=fmt, title_text=title_text, text=art_clean, source=source_path,
                anchor=(f"chapter:{ch_num}|" if ch_num else "") + f"article:{a_num or 'NA'}",
                created_at=created, text_sha256=art_sha,
                effective_from=eff_from_iso, effective_to=eff_to_iso, status=status_val
            ))
            for i, ch in enumerate(self.sliding_chunks(art_clean)):
                ch_sum = make_summary(ch)
                ch_topics = extract_keywords(ch)
                ch_fmt = f"📘 {title}\n{part_name or ''}\n" + (f"Глава {ch_num}, " if ch_num else "") + f"Статья {a_num or '—'}\n\n{ch}"
                ch_sha = sha256_text(ch)
                chunks.append(LawDoc(
                    id=str(uuid.uuid4()), level="chunk",
                    code=code_name, part=part_name, chapter=ch_num, article=a_num or None,
                    title=title, semantic_summary=ch_sum, topics=ch_topics, references=art_refs,
                    formatted_text=ch_fmt, title_text=title_text, text=ch, source=source_path,
                    anchor=((f"chapter:{ch_num}|" if ch_num else "") + f"article:{a_num or 'NA'}#chunk:{i+1}"),
                    created_at=created, text_sha256=ch_sha,
                    effective_from=eff_from_iso, effective_to=eff_to_iso, status=status_val
                ))

        if not chapter_splits:
            for a_num, header, art_text in self.split_articles(text):
                art_clean = clean_for_embedding(art_text)
                art_refs = extract_references(art_text)
                mk_docs_for_article(a_num, None, art_clean, art_refs)
        else:
            for idx, m in enumerate(chapter_splits):
                start = m.start()
                end = chapter_splits[idx+1].start() if idx+1 < len(chapter_splits) else len(text)
                ch_text = text[start:end]
                ch_num = m.group(1)
                arts = self.split_articles(ch_text)
                for a_num, header, art_text in arts:
                    art_clean = clean_for_embedding(art_text)
                    art_refs = extract_references(art_text)
                    mk_docs_for_article(a_num, ch_num, art_clean, art_refs)

        return chunks, articles

# ============================
# Embedding cache (SQLite) + retry helpers
# ============================
_EMB_DB = os.path.join(QDRANT_PATH, "emb_cache.sqlite3")
_emb_lock = threading.Lock()


def _emb_init():
    os.makedirs(QDRANT_PATH, exist_ok=True)
    with sqlite3.connect(_EMB_DB) as db:
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA synchronous=NORMAL;")
        db.execute("CREATE TABLE IF NOT EXISTS emb (sha TEXT PRIMARY KEY, vec BLOB)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_emb_sha ON emb(sha)")
_emb_init()


def emb_get(sha: str):
    with _emb_lock, sqlite3.connect(_EMB_DB) as db:
        cur = db.execute("SELECT vec FROM emb WHERE sha=?", (sha,))
        row = cur.fetchone()
        return pickle.loads(row[0]) if row else None


def emb_put(sha: str, vec):
    with _emb_lock, sqlite3.connect(_EMB_DB) as db:
        db.execute("INSERT OR REPLACE INTO emb(sha,vec) VALUES(?,?)", (sha, pickle.dumps(vec)))


def backoff_retry(fn, *, tries=5, base=0.6, jitter=0.3, cancel_flag=None):
    last = None
    for i in range(tries):
        if cancel_flag and cancel_flag():
            raise RuntimeError("Cancelled")
        try:
            return fn()
        except Exception as e:
            last = e
            if cancel_flag and cancel_flag():
                raise RuntimeError("Cancelled")
            sleep = base * (2 ** i) + jitter * random()
            time.sleep(min(sleep, 8.0))
    raise last


# ============================
# OpenAI wrappers
# ============================
class Embedder:
    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("Введите OpenAI API Key.")
        self.client = OpenAI(api_key=api_key, timeout=20.0)

    def embed(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        vecs: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            raw_batch = texts[i:i+batch_size]
            batch = [clamp_for_embedding(t) for t in raw_batch]
            batch = [(t if t is not None else "") for t in batch]

            def _call():
                return self.client.embeddings.create(model=EMBED_MODEL, input=batch)

            try:
                r = backoff_retry(_call)
            except Exception as e:
                bad_len = max((len(x) for x in batch), default=0)
                raise RuntimeError(
                    f"Embeddings failed (batch {i//batch_size+1}). Max char len={bad_len}. Original err: {e}"
                ) from e

            vecs.extend([d.embedding for d in r.data])
        return vecs

    def embed_one(self, text: str) -> List[float]:
        r = self.client.embeddings.create(model=EMBED_MODEL, input=[clamp_for_embedding(text)])
        return r.data[0].embedding


class GPTMini:
    """Модель для HyDE-подсказок (подбираем первую доступную)."""
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, timeout=20.0)
        self.model = None
        for m in CHAT_RERANK_MODEL_CANDIDATES:
            try:
                _ = self.client.chat.completions.create(
                    model=m, messages=[{"role":"user","content":"ping"}], temperature=0
                )
                self.model = m
                break
            except Exception:
                continue
        if not self.model:
            self.model = CHAT_RERANK_MODEL_CANDIDATES[0]

    def hyde_expand(self, query: str) -> str:
        try:
            def _call():
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role":"user","content":
                        "Сгенерируй краткую выдержку (2–3 предложения) в стиле ГК РФ, только юридические формулировки, без рассуждений. Запрос:\n" + query}],
                    temperature=0
                )
            r = backoff_retry(_call)
            return (r.choices[0].message.content or "").strip()[:1200]
        except Exception as e:
            logger.warning(f"HyDE fallback: {e}")
            return query


class Enricher:
    """Обогащение summary через GPT-5-nano (Responses API → фоллбэк Chat)."""
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, timeout=20.0)
        self.model = ENRICH_MODEL

    def summarize(self, raw_text: str) -> str:
        prompt = (
            "Сделай ультра-короткую выжимку сути правовой нормы (≤160 символов), без вводных слов, без рассуждений, без кавычек. "
            "Фокус: что регулирует норма или какое последствие устанавливает."
        )
        content = raw_text[:1800]
        try:
            r = self.client.responses.create(
                model=self.model,
                input=[
                    {"role":"developer","content":prompt},
                    {"role":"user","content":content}
                ],
                reasoning={"effort":"minimal"},
                verbosity="low"
            )
            out = getattr(r, "output_text", None)
            if not out:
                try:
                    arr = getattr(r, "output", []) or []
                    if arr and hasattr(arr[0], "content") and arr[0].content:
                        maybe = arr[0].content[0]
                        if hasattr(maybe, "text"):
                            out = maybe.text
                except Exception:
                    out = None
            if not out:
                out = str(r)
            return out.strip()[:200]
        except Exception as e1:
            logger.debug(f"Responses API enrich fallback to Chat: {e1}")
            try:
                r = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role":"system","content":prompt},
                        {"role":"user","content":content}
                    ],
                    temperature=0
                )
                return (r.choices[0].message.content or "").strip()[:200]
            except Exception as e2:
                logger.warning(f"Enrich failed: {e2}")
                return make_summary(raw_text)

# ============================
# Qdrant wrapper (named vectors) + Cache
# ============================
def stable_point_id(d: LawDoc) -> str:
    """
    Детерминированный UUIDv5 из устойчивой строки-основания.
    Это гарантирует валидный формат id, которого требует Qdrant (UUID/int).
    """
    base = f"{d.text_sha256 or ''}|{d.anchor or ''}|{d.code or ''}|{d.article or 'NA'}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, base))


class QdrantIndex:
    def __init__(self, path: str = QDRANT_PATH):
        os.makedirs(path, exist_ok=True)
        self.client = QdrantClient(path=path)

    def ensure_named_collection(self, name: str, use_quantization: bool = False):
        if not self.client.collection_exists(name):
            vectors_config = {
                "title_vec": VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                "body_vec":  VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            }
            quant = None
            if use_quantization:
                quant = qm.ScalarQuantization(scalar=qm.ScalarQuantizationConfig(type="int8", always_ram=False))
            self.client.create_collection(
                collection_name=name,
                vectors_config=vectors_config,
                optimizers_config=qm.OptimizersConfigDiff(default_segment_number=2),
                hnsw_config=qm.HnswConfigDiff(m=32, ef_construct=128),
                quantization_config=quant
            )
        # Создаём payload индексы только если их нет
        try:
            info = self.client.get_collection(name)
            existing = set((info.payload_schema or {}).keys())
        except Exception:
            existing = set()
        def mk(field, schema):
            if field not in existing:
                try:
                    self.client.create_payload_index(name, field_name=field, field_schema=schema)
                except Exception as e:
                    logger.debug(f"payload index create {field}: {e}")
        mk("article", qm.PayloadSchemaType.KEYWORD)
        mk("chapter", qm.PayloadSchemaType.KEYWORD)
        mk("status", qm.PayloadSchemaType.KEYWORD)
        mk("effective_from", qm.PayloadSchemaType.DATETIME)
        mk("effective_to", qm.PayloadSchemaType.DATETIME)
        mk("code", qm.PayloadSchemaType.KEYWORD)
        mk("part", qm.PayloadSchemaType.KEYWORD)
        mk("topics", qm.PayloadSchemaType.KEYWORD)

    def upsert_docs_named(self, collection: str, docs: List[LawDoc],
                          title_vecs: List[List[float]], body_vecs: List[List[float]], batch: int = 2000):
        points = []
        for d, tv, bv in zip(docs, title_vecs, body_vecs):
            payload = asdict(d)
            vectors = {"title_vec": tv, "body_vec": bv}
            pid = stable_point_id(d)
            points.append(PointStruct(id=pid, vector=vectors, payload=payload))
        for i in range(0, len(points), batch):
            self.client.upsert(collection_name=collection, points=points[i:i+batch], wait=True)

    def upsert_batch_stream(self, collection: str, docs: List[LawDoc],
                            emb: 'Embedder', batch_embed: int, cancel_flag,
                            progress_cb=None):
        """
        Потоковый режим: эмбеддим и сразу upsert'им батчи в Qdrant.
        Кэш эмбеддингов (SQLite) используется; RAM не растёт линейно.
        """
        total = len(docs)
        pos = 0
        while pos < total:
            if cancel_flag and cancel_flag():
                raise RuntimeError("Cancelled")
            sub = docs[pos:pos+batch_embed]
            titles = []
            bodies = []
            for d in sub:
                titles.append((f"{d.text_sha256}_{EMBED_MODEL}_{EMB_CLAMP_VERSION}_ttl", clamp_for_embedding(d.title_text)))
                bodies.append((f"{d.text_sha256}_{EMBED_MODEL}_{EMB_CLAMP_VERSION}_bdy", clamp_for_embedding(d.text)))
            # эмбеддинги с кэшем
            def _embed_with_cache(pairs: List[Tuple[str,str]]) -> List[List[float]]:
                out: List[Optional[List[float]]] = [None]*len(pairs)
                miss_idx, miss_texts = [], []
                for i, (sha, t) in enumerate(pairs):
                    v = emb_get(sha)
                    if v is None:
                        miss_idx.append(i); miss_texts.append(t)
                    else:
                        out[i] = v
                if miss_texts:
                    if cancel_flag and cancel_flag(): raise RuntimeError("Cancelled")
                    vecs = backoff_retry(lambda: emb.embed(miss_texts, batch_size=min(16, len(miss_texts))),
                                         cancel_flag=cancel_flag)
                    for i2, v in zip(miss_idx, vecs):
                        out[i2] = v
                        emb_put(pairs[i2][0], v)
                if any(v is None for v in out):
                    raise RuntimeError("Embedding cache/generation inconsistency")
                return [v for v in out]  # type: ignore

            title_vecs = _embed_with_cache(titles)
            body_vecs  = _embed_with_cache(bodies)

            # upsert текущего батча
            points = []
            for d, tv, bv in zip(sub, title_vecs, body_vecs):
                payload = asdict(d)
                vectors = {"title_vec": tv, "body_vec": bv}
                pid = stable_point_id(d)  # детерминированный UUIDv5
                points.append(PointStruct(id=pid, vector=vectors, payload=payload))
            self.client.upsert(collection_name=collection, points=points, wait=True)

            pos += len(sub)
            if progress_cb:
                progress_cb(pos, total)

            del title_vecs, body_vecs, points, titles, bodies, sub
            gc.collect()

    def scroll_payload(self, collection: str, limit=20000, offset=None) -> Tuple[List, Optional[str]]:
        res, next_page = self.client.scroll(
            collection_name=collection,
            with_payload=True, with_vectors=False,
            limit=min(512, limit),
            offset=offset
        )
        return res, next_page


class SearchCache:
    def __init__(self, qdr: QdrantIndex):
        self.qdr = qdr
        self.cache: Dict[str, List] = {}
        self.id2point: Dict[str, any] = {}
        self.next_offsets: Dict[str, Optional[str]] = {}

    def warm_step(self, collection: str, limit_step: int = 5000):
        offset = self.next_offsets.get(collection)
        got_all = self.cache.get(collection, [])
        if got_all is None:
            got_all = []
        need = limit_step
        while need > 0:
            try:
                pts, offset = self.qdr.scroll_payload(collection, limit=need, offset=offset)
            except Exception as e:
                logger.debug(f"warm_step skip {collection}: {e}")
                self.next_offsets[collection] = None
                self.cache[collection] = got_all
                return len(got_all), True
            for p in pts:
                # 1) прямой id точки из Qdrant (UUID) — главный ключ
                qid = None
                try:
                    qid = str(getattr(p, "id", "") or "")
                except Exception:
                    qid = None
                if qid:
                    self.id2point[qid] = p
                # 2) дополнительные ключи по payload — на всякий
                pl = p.payload or {}
                hay = " ".join([
                    str(pl.get("title","")),
                    str(pl.get("anchor","")),
                    " ".join(pl.get("topics",[]) or []),
                    str(pl.get("semantic_summary","")),
                    str(pl.get("article") or "")
                ]).lower()
                setattr(p, "_hay", hay)
                try:
                    sid = stable_point_id(LawDoc(**pl))
                except Exception:
                    sid = pl.get("id")
                if sid and p:
                    self.id2point[sid] = p
                pid_old = pl.get("id")
                if pid_old and p:
                    self.id2point[pid_old] = p
            got_all.extend(pts)
            need -= len(pts)
            if not offset:
                break
        self.cache[collection] = got_all
        self.next_offsets[collection] = offset
        return len(got_all), offset is None

# ============================
# Prefilter / Fusion / Helpers
# ============================
def keyword_prefilter(payload_points: List, query: str, topk: int = 300) -> List[str]:
    q = query.lower()
    keys = set(re.findall(r"[А-Яа-яA-Za-z]{3,}", q))
    m = re.search(r"ст\.?\s*(\d+(?:\.\d+)*)", q)
    target_art = m.group(1) if m else None

    scored = []
    for p in payload_points:
        pl = p.payload or {}
        hay = getattr(p, "_hay", None)
        if not hay:
            hay = " ".join([
                str(pl.get("title","")),
                str(pl.get("anchor","")),
                " ".join(pl.get("topics",[]) or []),
                str(pl.get("semantic_summary","")),
                str(pl.get("article") or "")
            ]).lower()
        match_count = sum(1 for k in keys if k in hay)
        bonus = 3 if (target_art and target_art == (pl.get("article") or "")) else 0
        score = match_count * 2 + bonus
        try:
            sid = stable_point_id(LawDoc(**pl))
        except Exception:
            sid = pl.get("id")
        if sid:
            scored.append((score, sid))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [pid for _, pid in scored[:topk]]


def dedup_limit(points: List, k: int) -> List:
    seen, out = set(), []
    for p in points:
        pl = p.payload or {}
        key = (pl.get("level"), pl.get("article") or "", pl.get("anchor") or "")
        if key in seen:
            continue
        out.append(p)
        seen.add(key)
        if len(out) >= k: break
    return out


def boost_exact_article(scores_map: Dict[str,float], pts_map: Dict[str,dict], target_art: Optional[str]) -> None:
    if not target_art: return
    for pid, sc in list(scores_map.items()):
        pl = pts_map.get(pid) or {}
        if (pl.get("article") or "") == target_art:
            scores_map[pid] = sc + 0.15


def fetch_by_article(qdr: QdrantIndex, collection: str, art_value: str, limit=3) -> List:
    res, next_page = qdr.client.scroll(
        collection_name=collection,
        limit=limit,
        with_payload=True,
        with_vectors=False,
        scroll_filter=qm.Filter(
            must=[qm.FieldCondition(key="article", match=qm.MatchValue(value=art_value))]
        )
    )
    return res


def make_asof_filters_strict(as_of_iso: Optional[str]) -> List[Optional[qm.Filter]]:
    if not as_of_iso:
        return [None]
    must_common = [qm.FieldCondition(key="status", match=qm.MatchExcept(except_values=["утратил силу"]))]  # status != 'утратил силу'
    f1 = qm.Filter(must=must_common + [
        qm.IsNullCondition(is_null=qm.IsNull(key="effective_to")),
        qm.FieldCondition(key="effective_from", range=qm.Range(lte=as_of_iso)),
    ])
    f2 = qm.Filter(must=must_common + [
        qm.FieldCondition(key="effective_to", range=qm.Range(gte=as_of_iso)),
        qm.FieldCondition(key="effective_from", range=qm.Range(lte=as_of_iso)),
    ])
    return [f1, f2]


def rrf_scores(ranks: Dict[str,int], k=60) -> Dict[str,float]:
    return {pid: 1.0/(k + rank) for pid, rank in ranks.items()}


def combine_rrf_weighted(title_rrf: Dict[str,float], body_rrf: Dict[str,float], w_title: float, w_body: float) -> Dict[str,float]:
    keys = set(title_rrf) | set(body_rrf)
    return {pid: w_title*title_rrf.get(pid, 0.0) + w_body*body_rrf.get(pid, 0.0) for pid in keys}

# ============================
# Поток индексации (stream)
# ============================
class IndexWorker(QtCore.QThread):
    progressChanged = QtCore.Signal(int, str)  # percent, message
    finishedOk = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, api_key: str, articles: List[LawDoc], chunks: List[LawDoc],
                 do_articles: bool, do_chunks: bool, batch: int,
                 use_quant: bool, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.articles = articles
        self.chunks = chunks
        self.do_articles = do_articles
        self.do_chunks = do_chunks
        self.batch = batch
        self.use_quant = use_quant
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _ensure_not_cancelled(self):
        if self._cancel:
            raise RuntimeError("Cancelled")

    def run(self):
        try:
            emb = Embedder(self.api_key)
            dim = len(emb.embed_one("probe"))
            if dim != VECTOR_SIZE:
                raise RuntimeError(f"Несовпадение размерности эмбеддинга: модель дала dim={dim}, а VECTOR_SIZE={VECTOR_SIZE}. "
                                   f"Обновите VECTOR_SIZE до {dim} и пересоздайте коллекции.")
            q = QdrantIndex(QDRANT_PATH)
            if self.do_articles: q.ensure_named_collection(COLL_ARTICLES, use_quantization=self.use_quant)
            if self.do_chunks:   q.ensure_named_collection(COLL_CHUNKS,   use_quantization=self.use_quant)

            total_all = (len(self.articles) if self.do_articles else 0) + (len(self.chunks) if self.do_chunks else 0)
            done = 0

            if self.do_articles and self.articles:
                def _cb(pos, tot):
                    nonlocal done
                    done = pos
                    pct = int((done / max(1, total_all)) * 50)
                    self.progressChanged.emit(min(49, pct), f"Статьи: {pos}/{tot}")
                self._ensure_not_cancelled()
                q.upsert_batch_stream(COLL_ARTICLES, self.articles, emb, self.batch, cancel_flag=lambda: self._cancel, progress_cb=_cb)
                self.progressChanged.emit(50, f"Статьи: индексировано {len(self.articles)}")

            if self.do_chunks and self.chunks:
                start_done = done
                def _cb2(pos, tot):
                    nonlocal done
                    done = start_done + pos
                    base = 50
                    pct = base + int((pos / max(1, tot)) * 50)
                    self.progressChanged.emit(min(99, pct), f"Чанки: {pos}/{tot}")
                self._ensure_not_cancelled()
                q.upsert_batch_stream(COLL_CHUNKS, self.chunks, emb, self.batch, cancel_flag=lambda: self._cancel, progress_cb=_cb2)
                self.progressChanged.emit(100, f"Чанки: индексировано {len(self.chunks)}")

            self.finishedOk.emit("Индексация завершена.")
        except Exception as e:
            logger.exception("IndexWorker error")
            self.failed.emit(str(e))


# ============================
# LRU-кэш эмбеддингов запроса (RAM)
# ============================
def _vec_to_tuple(v: List[float]) -> tuple:
    return tuple(v)


class QueryEmbedder:
    def __init__(self, emb: Embedder, gpt: Optional[GPTMini], use_hyde: bool):
        self.emb = emb
        self.gpt = gpt
        self.use_hyde = use_hyde

    @lru_cache(maxsize=512)
    def embed_title_cached(self, qtxt: str) -> tuple:
        return _vec_to_tuple(self.emb.embed([qtxt], batch_size=1)[0])

    @lru_cache(maxsize=512)
    def embed_body_hyde_cached(self, qtxt: str) -> tuple:
        hyde_text = self.gpt.hyde_expand(qtxt) if (self.gpt and self.use_hyde) else qtxt
        return _vec_to_tuple(self.emb.embed([hyde_text], batch_size=1)[0])

# ============================
# GUI
# ============================
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ГК РФ — Индексатор v4 · Vector Studio")
        self.resize(1480, 960)
        self.setMinimumSize(1280, 840)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(APP_STYLESHEET)

        self.selected_files: List[str] = []
        self.chunks: List[LawDoc] = []
        self.articles: List[LawDoc] = []
        self.analysis_per_file: Dict[str, Dict[str, Any]] = {}
        self.search_cache: Optional[SearchCache] = None
        self._last_vector: Optional[List[float]] = None
        self._last_rag_blocks: List[str] = []

        central = QtWidgets.QWidget()
        central_layout = QtWidgets.QVBoxLayout(central)
        central_layout.setContentsMargins(24, 20, 24, 24)
        central_layout.setSpacing(18)
        self.setCentralWidget(central)

        central_layout.addWidget(self.create_hero_banner())

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(18)
        body.setContentsMargins(0, 0, 0, 0)
        central_layout.addLayout(body, 1)

        self.nav_list = QtWidgets.QListWidget()
        self.configure_nav_list()
        body.addWidget(self.nav_list)

        self.page_container = QtWidgets.QFrame()
        page_layout = QtWidgets.QVBoxLayout(self.page_container)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(16)
        body.addWidget(self.page_container, 1)

        self.page_hint = QtWidgets.QLabel()
        self.page_hint.setObjectName("SubHeadline")
        self.page_hint.setWordWrap(True)
        page_layout.addWidget(self.page_hint)

        self.stack = QtWidgets.QStackedWidget()
        page_layout.addWidget(self.stack, 1)

        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav_list.currentRowChanged.connect(self.on_page_changed)

        import_page = self.build_import_page()
        self.register_page("1️⃣ Импорт", "Шаг 1. Соберите документы и посмотрите автоматическую аналитику перед векторизацией.", import_page)

        index_page = self.build_index_page()
        self.register_page("2️⃣ Индексация", "Шаг 2. Укажите ключ OpenAI и отправьте статьи и чанки в Qdrant.", index_page)

        search_page = self.build_search_page()
        self.register_page("3️⃣ Поиск", "Шаг 3. Проверяйте базу: задавайте вопросы и просматривайте найденные нормы.", search_page)

        vector_page = self.build_vector_lab_page()
        self.register_page("🔬 Лаборатория", "Необязательный модуль для экспериментов с эмбеддингами и отладкой Qdrant.", vector_page)

        help_page = self.build_help_page()
        self.register_page("ℹ️ Справка", "Пояснения к каждому шагу, ответы на частые вопросы и советы по устранению ошибок.", help_page)

        log_page = self.build_log_page()
        self.register_page("📝 Журнал", "Все действия приложения фиксируются здесь — удобно контролировать индексацию.", log_page)

        self.nav_list.setCurrentRow(0)

        self.status = self.statusBar()
        self.cache_progress_lbl = QtWidgets.QLabel("Кэш не прогрет")
        self.status.addWidget(self.cache_progress_lbl)

        self.index_thread: Optional[IndexWorker] = None

    # ---------- UI helpers ----------
    def create_hero_banner(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("HeroCard")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(8)
        title = QtWidgets.QLabel("Vector Studio для ГК РФ")
        title.setObjectName("Headline")
        subtitle = QtWidgets.QLabel(
            "Пошаговый помощник: загрузите файлы, подготовьте корпус, отправьте в Qdrant и протестируйте выдачу."
        )
        subtitle.setObjectName("SubHeadline")
        subtitle.setWordWrap(True)
        steps = QtWidgets.QLabel(
            "<ol style='margin:4px 0 0 18px'>"
            "<li><b>Импорт</b> — добавьте документы и проверьте автоматическую аналитику.</li>"
            "<li><b>Индексация</b> — введите ключ OpenAI и отправьте статьи в Qdrant.</li>"
            "<li><b>Поиск</b> — задайте вопрос и изучите найденные нормы.</li>"
            "<li><b>Справка</b> — откройте подсказки, если что-то неочевидно.</li>"
            "</ol>"
        )
        steps.setObjectName("OptionHint")
        steps.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(steps)
        return frame

    def configure_nav_list(self):
        self.nav_list.setObjectName("NavigationList")
        self.nav_list.setFixedWidth(260)
        self.nav_list.setSpacing(6)
        self.nav_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.nav_list.setAlternatingRowColors(False)

    def register_page(self, title: str, subtitle: str, widget: QtWidgets.QWidget):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        wrapper = QtWidgets.QWidget()
        wrapper_layout = QtWidgets.QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(4, 0, 20, 40)
        wrapper_layout.setSpacing(18)
        wrapper_layout.addWidget(widget)
        wrapper_layout.addStretch(1)
        scroll.setWidget(wrapper)

        self.stack.addWidget(scroll)

        item = QtWidgets.QListWidgetItem(title)
        item.setData(Qt.UserRole, subtitle)
        item.setToolTip(subtitle)
        self.nav_list.addItem(item)

    def on_page_changed(self, row: int):
        if row < 0:
            self.page_hint.clear()
            return
        item = self.nav_list.item(row)
        hint = item.data(Qt.UserRole) if item else ""
        self.page_hint.setText(hint)

    def section_header(self, title: str, subtitle: str) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        lbl = QtWidgets.QLabel(title)
        lbl.setObjectName("SectionTitle")
        sub = QtWidgets.QLabel(subtitle)
        sub.setObjectName("SubHeadline")
        sub.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addWidget(sub)
        return container

    def create_card(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        return frame

    def add_option_row(self, grid: QtWidgets.QGridLayout, row: int, label: str,
                        widget: QtWidgets.QWidget, description: str) -> int:
        title = QtWidgets.QLabel(label)
        title.setObjectName("OptionLabel")
        title.setAlignment(Qt.AlignTop)
        grid.addWidget(title, row, 0)
        grid.addWidget(widget, row, 1)
        hint = QtWidgets.QLabel(description)
        hint.setObjectName("OptionHint")
        hint.setWordWrap(True)
        grid.addWidget(hint, row + 1, 0, 1, 2)
        widget.setToolTip(description)
        return row + 2

    def add_toggle_row(self, grid: QtWidgets.QGridLayout, row: int, title: str,
                        checkbox: QtWidgets.QCheckBox, description: str) -> int:
        label = QtWidgets.QLabel(title)
        label.setObjectName("OptionLabel")
        label.setAlignment(Qt.AlignTop)
        grid.addWidget(label, row, 0)
        grid.addWidget(checkbox, row, 1)
        hint = QtWidgets.QLabel(description)
        hint.setObjectName("OptionHint")
        hint.setWordWrap(True)
        grid.addWidget(hint, row + 1, 0, 1, 2)
        checkbox.setToolTip(description)
        return row + 2

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        if hasattr(self, "log_box"):
            self.log_box.appendPlainText(f"[{ts}] {msg}")
        logger.info(msg)

    def update_analysis_view(self, path: str):
        data = self.analysis_per_file.get(path)
        if not data:
            self.analysis_table.setRowCount(0)
            self.analysis_summary.setText("Аналитика недоступна для выбранного документа.")
            return
        metrics = [
            ("Символов", str(data.get("length_chars", 0))),
            ("Слов", str(data.get("word_count", 0))),
            ("Уникальных слов", str(data.get("unique_words", 0))),
            ("Абзацев", str(data.get("paragraphs", 0))),
            ("Средний размер абзаца", str(data.get("avg_paragraph_words", 0))),
            ("Оценка токенов", str(data.get("rough_tokens", 0))),
            ("Найденные ссылки", ", ".join(data.get("references", [])[:10]) or "—"),
            ("Ключевые слова", ", ".join(data.get("keywords", [])) or "—"),
        ]
        self.analysis_table.setRowCount(len(metrics))
        for row, (name, value) in enumerate(metrics):
            self.analysis_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
            self.analysis_table.setItem(row, 1, QtWidgets.QTableWidgetItem(value))
        warnings = data.get("warnings", [])
        if warnings:
            txt = "\n".join(f"⚠️ {w}" for w in warnings)
        else:
            txt = "Документ выглядит готовым к векторизации."
        if data.get("keywords"):
            txt += "\n\nТоп ключевых слов: " + ", ".join(data.get("keywords"))
        self.analysis_summary.setText(txt)

    # ---------- Import ----------
    def build_import_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Импорт документов",
            "Шаг первый: соберите исходники. Приложение само подскажет, где слишком много токенов, где нет ссылок и какие ключевые темы внутри."
        ))

        hero_card = self.create_card()
        hero_layout = hero_card.layout()
        intro = QtWidgets.QLabel(
            "<b>Как работает импорт:</b><br>"
            "1. Добавьте RTF/PDF/DOCX/TXT с текстами кодекса.<br>"
            "2. При необходимости скорректируйте название и параметры чанкинга.<br>"
            "3. Нажмите «Подготовить корпус», чтобы получить статьи и чанки."
        )
        intro.setWordWrap(True)
        intro.setObjectName("OptionHint")
        hero_layout.addWidget(intro)
        layout.addWidget(hero_card)

        options_card = self.create_card()
        options_layout = options_card.layout()

        buttons_row = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton("Добавить файлы…")
        self.btn_add.clicked.connect(self.add_files)
        self.btn_add.setToolTip("Откроет диалог выбора документов. Поддерживаются форматы RTF, PDF, DOCX и TXT.")
        self.btn_clear = QtWidgets.QPushButton("Очистить список")
        self.btn_clear.clicked.connect(self.clear_files)
        self.btn_clear.setToolTip("Удаляет все выбранные документы из списка, чтобы начать заново.")
        self.btn_parse = QtWidgets.QPushButton("Подготовить корпус")
        self.btn_parse.clicked.connect(self.parse_and_chunk)
        self.btn_parse.setToolTip("Разбирает документы на статьи и чанки, вычисляет метаданные и готовит корпус к индексации.")
        buttons_row.addWidget(self.btn_add)
        buttons_row.addWidget(self.btn_clear)
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.btn_parse)
        options_layout.addLayout(buttons_row)

        hint = QtWidgets.QLabel(
            "Если вы добавляете несколько файлов, приложение автоматически угадает часть кодекса и объединит статьи."
        )
        hint.setObjectName("OptionHint")
        hint.setWordWrap(True)
        options_layout.addWidget(hint)

        params_widget = QtWidgets.QWidget()
        params_grid = QtWidgets.QGridLayout(params_widget)
        params_grid.setColumnStretch(1, 1)
        params_grid.setHorizontalSpacing(18)
        params_grid.setVerticalSpacing(10)

        self.ed_code = QtWidgets.QLineEdit("ГК РФ")
        row = 0
        row = self.add_option_row(
            params_grid,
            row,
            "Кодекс (payload code)",
            self.ed_code,
            "Короткое имя пойдёт в поле payload['code']. Используется для фильтрации в Qdrant и в заголовках."
        )

        self.ed_title = QtWidgets.QLineEdit("Гражданский кодекс Российской Федерации")
        row = self.add_option_row(
            params_grid,
            row,
            "Полное название",
            self.ed_title,
            "Будет показано в карточках результатов и сохранено в payload['title']. Помогает понимать, какой документ перед нами."
        )

        self.spin_chunk = QtWidgets.QSpinBox()
        self.spin_chunk.setRange(200, 4000)
        self.spin_chunk.setValue(800)
        row = self.add_option_row(
            params_grid,
            row,
            "Размер чанка",
            self.spin_chunk,
            "Примерное количество токенов в одном фрагменте. Большие чанки сохраняют контекст, а меньшие повышают точность поиска."
        )

        self.spin_overlap = QtWidgets.QSpinBox()
        self.spin_overlap.setRange(0, 1200)
        self.spin_overlap.setValue(120)
        row = self.add_option_row(
            params_grid,
            row,
            "Перекрытие чанков",
            self.spin_overlap,
            "Чем больше overlap, тем плавнее фрагменты передают контекст между собой. Ноль отключает перекрытие."
        )

        self.chk_gpt_summ = QtWidgets.QCheckBox("Включить обогащение")
        self.chk_summ_articles_only = QtWidgets.QCheckBox("Только для статей")
        self.chk_summ_articles_only.setChecked(True)
        row = self.add_toggle_row(
            params_grid,
            row,
            "GPT-резюме",
            self.chk_gpt_summ,
            "Если включить, для каждого фрагмента будет сделан краткий summary через GPT-5-nano. Это быстрее понимается в поиске, но стоит дороже."
        )
        row = self.add_toggle_row(
            params_grid,
            row,
            "Ограничить обогащение",
            self.chk_summ_articles_only,
            "Когда включено, summary строятся только для статей. Снимите флаг, если нужно обогащать и короткие чанки."
        )

        self.eff_from = QtWidgets.QDateEdit()
        self.eff_from.setCalendarPopup(True)
        self.eff_from.setDisplayFormat("yyyy-MM-dd")
        self.eff_from.setDate(QtCore.QDate(2000, 1, 1))
        self.eff_from.setSpecialValueText("")
        row = self.add_option_row(
            params_grid,
            row,
            "Дата начала действия",
            self.eff_from,
            "Укажите, с какого дня норма действует. Это попадёт в payload['effective_from'] и поможет фильтрам по дате."
        )

        self.eff_to = QtWidgets.QDateEdit()
        self.eff_to.setCalendarPopup(True)
        self.eff_to.setDisplayFormat("yyyy-MM-dd")
        self.eff_to.setDate(QtCore.QDate(2100, 1, 1))
        self.eff_to.setSpecialValueText("")
        row = self.add_option_row(
            params_grid,
            row,
            "Дата окончания",
            self.eff_to,
            "Заполните, если норма утрачивает силу к конкретной дате. Незаполненное поле значит 'действует бессрочно'."
        )

        self.eff_status = QtWidgets.QComboBox()
        self.eff_status.addItems(["действует", "утратил силу", "не вступил в силу"])
        row = self.add_option_row(
            params_grid,
            row,
            "Статус нормы",
            self.eff_status,
            "Помогает отслеживать актуальность нормы. Статус пишется в payload['status'] и используется в фильтрах поиска."
        )

        options_layout.addWidget(params_widget)
        layout.addWidget(options_card)

        analysis_card = self.create_card()
        analysis_layout = analysis_card.layout()
        analysis_layout.addWidget(self.section_header(
            "Анализ источников",
            "Слева список файлов, справа — метрики, найденные ссылки и предпросмотр. Даже ребёнок увидит, что происходит."
        ))

        splitter = QtWidgets.QSplitter(Qt.Horizontal)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        lbl_files = QtWidgets.QLabel("Выбранные документы")
        lbl_files.setObjectName("OptionLabel")
        left_layout.addWidget(lbl_files)
        files_hint = QtWidgets.QLabel("Выбирайте файл, чтобы увидеть его статистику и фрагмент текста.")
        files_hint.setObjectName("OptionHint")
        files_hint.setWordWrap(True)
        left_layout.addWidget(files_hint)
        self.files_list = QtWidgets.QListWidget()
        self.files_list.currentItemChanged.connect(self.on_current_file_changed)
        left_layout.addWidget(self.files_list, 1)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)

        self.analysis_table = QtWidgets.QTableWidget(0, 2)
        self.analysis_table.setHorizontalHeaderLabels(["Метрика", "Значение"])
        self.analysis_table.horizontalHeader().setStretchLastSection(True)
        self.analysis_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.analysis_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        right_layout.addWidget(self.analysis_table, 2)

        self.analysis_summary = QtWidgets.QTextBrowser()
        self.analysis_summary.setPlaceholderText("Здесь появятся инсайты по выбранному документу.")
        right_layout.addWidget(self.analysis_summary, 2)

        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setPlaceholderText("Предпросмотр текста…")
        self.preview.setReadOnly(True)
        self.preview.setMaximumBlockCount(6000)
        right_layout.addWidget(self.preview, 3)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        analysis_layout.addWidget(splitter)

        layout.addWidget(analysis_card, 1)
        layout.addStretch(1)

        return page

    def add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Выберите документы",
            "",
            "Документы (*.rtf *.pdf *.docx *.txt)"
        )
        if not files:
            return
        for f in files:
            self.selected_files.append(f)
            self.files_list.addItem(f)
        self.log(f"Добавлено файлов: {len(files)}")
        if self.files_list.count() and not self.files_list.currentItem():
            self.files_list.setCurrentRow(0)

    def clear_files(self):
        self.selected_files.clear()
        self.files_list.clear()
        self.chunks, self.articles = [], []
        self.analysis_per_file.clear()
        self.analysis_table.setRowCount(0)
        self.analysis_summary.clear()
        self.preview.clear()

    def on_current_file_changed(self, cur, prev):
        if not cur:
            return
        path = cur.text()
        try:
            text = extract_text_from_file(path)
            self.preview.setPlainText(text[:25000])
            if path not in self.analysis_per_file:
                self.analysis_per_file[path] = analyze_text_content(text)
            self.update_analysis_view(path)
        except Exception as e:
            self.preview.setPlainText(f"Ошибка предпросмотра: {e}")
            self.analysis_summary.setText(f"Не удалось проанализировать документ: {e}")

    def parse_and_chunk(self):
        if not self.selected_files:
            QtWidgets.QMessageBox.warning(self, "Нет файлов", "Добавьте хотя бы один документ, чтобы продолжить.")
            return
        code = self.ed_code.text().strip() or "ГК РФ"
        title = self.ed_title.text().strip() or "Гражданский кодекс Российской Федерации"
        builder = CorpusBuilder(chunk_tokens=self.spin_chunk.value(), overlap=self.spin_overlap.value())

        eff_from = self.eff_from.date().toString("yyyy-MM-dd")
        eff_to = self.eff_to.date().toString("yyyy-MM-dd")
        eff_from = None if eff_from == "2000-01-01" else eff_from
        eff_to = None if eff_to == "2100-01-01" else eff_to
        status = self.eff_status.currentText()

        all_chunks: List[LawDoc] = []
        all_articles: List[LawDoc] = []
        tot_c = tot_a = 0
        for path in self.selected_files:
            try:
                raw = extract_text_from_file(path)
                self.analysis_per_file[path] = analyze_text_content(raw)
                part = auto_detect_part(path)
                chunks, arts = builder.prepare_docs(
                    full_text=raw,
                    code_name=code,
                    part_name=part,
                    title=title,
                    source_path=path,
                    effective_from=eff_from,
                    effective_to=eff_to,
                    status=status,
                )
                all_chunks.extend(chunks)
                all_articles.extend(arts)
                tot_c += len(chunks)
                tot_a += len(arts)
                self.log(f"OK: {os.path.basename(path)} → статей: {len(arts)}; чанков: {len(chunks)}")
                warnings = self.analysis_per_file[path].get("warnings", [])
                if warnings:
                    for w in warnings:
                        self.log(f"   ⚠️ {w}")
                if self.files_list.currentItem() and self.files_list.currentItem().text() == path:
                    self.update_analysis_view(path)
            except Exception as e:
                self.log(f"Ошибка парсинга {path}: {e}")
        if self.chk_gpt_summ.isChecked():
            key = os.environ.get("OPENAI_API_KEY", "") or OPENAI_API_KEY_DEFAULT
            if key:
                enr = Enricher(key)

                def enrich(doc: LawDoc) -> None:
                    try:
                        doc.semantic_summary = enr.summarize(doc.text) or doc.semantic_summary
                        doc.semantic_summary = doc.semantic_summary[:200]
                    except Exception as exc:
                        logger.warning(f"summary enrich fallback: {exc}")

                if self.chk_summ_articles_only.isChecked():
                    for d in all_articles:
                        enrich(d)
                else:
                    for d in all_articles:
                        enrich(d)
                    for d in all_chunks:
                        enrich(d)
        self.chunks, self.articles = all_chunks, all_articles
        self.log(f"Итого: статей={tot_a}, чанков={tot_c}")
        QtWidgets.QMessageBox.information(
            self,
            "Корпус готов",
            f"Статей: {tot_a}\nЧанков: {tot_c}\nТеперь можно переходить к вкладке индексации."
        )

    # ---------- Index ----------
    def build_index_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Индексация в Qdrant",
            "Здесь настраиваем подключение к OpenAI и решаем, какие документы отправлять в векторное хранилище."
        ))

        info_card = self.create_card()
        info_layout = info_card.layout()
        info_text = QtWidgets.QLabel(
            "<b>Памятка:</b> индексация идёт батчами, поэтому можно безопасно отменить процесс — уже отправленные порции сохранятся."
        )
        info_text.setWordWrap(True)
        info_text.setObjectName("OptionHint")
        info_layout.addWidget(info_text)
        layout.addWidget(info_card)

        options_card = self.create_card()
        options_layout = options_card.layout()

        params_widget = QtWidgets.QWidget()
        params_grid = QtWidgets.QGridLayout(params_widget)
        params_grid.setColumnStretch(1, 1)
        params_grid.setHorizontalSpacing(18)
        params_grid.setVerticalSpacing(10)

        self.ed_api_key = QtWidgets.QLineEdit(os.environ.get("OPENAI_API_KEY", OPENAI_API_KEY_DEFAULT))
        self.ed_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        row = 0
        row = self.add_option_row(
            params_grid,
            row,
            "OpenAI API Key",
            self.ed_api_key,
            "Нужен для эмбеддингов и подсказок GPT. Ключ хранится только в оперативной памяти и используется для вызовов API."
        )

        self.spin_batch = QtWidgets.QSpinBox()
        self.spin_batch.setRange(1, 128)
        self.spin_batch.setValue(32)
        row = self.add_option_row(
            params_grid,
            row,
            "Размер батча",
            self.spin_batch,
            "Сколько текстов отправляем на эмбеддинг за один запрос. Большой батч ускоряет работу, но требует стабильного соединения."
        )

        self.chk_idx_articles = QtWidgets.QCheckBox("Включить")
        self.chk_idx_articles.setChecked(True)
        row = self.add_toggle_row(
            params_grid,
            row,
            "Индексировать статьи",
            self.chk_idx_articles,
            "Отправляет полноценные статьи в коллекцию {COLL_ARTICLES}. Полезно для быстрых ответов на уровне норм."
        )

        self.chk_idx_chunks = QtWidgets.QCheckBox("Включить")
        self.chk_idx_chunks.setChecked(True)
        row = self.add_toggle_row(
            params_grid,
            row,
            "Индексировать чанки",
            self.chk_idx_chunks,
            "Добавляет более мелкие фрагменты в коллекцию {COLL_CHUNKS}. Они дают точные подсказки и улучшают поиск по деталям."
        )

        self.chk_quant = QtWidgets.QCheckBox("Активировать")
        self.chk_quant.setChecked(False)
        row = self.add_toggle_row(
            params_grid,
            row,
            "Int8-квантизация",
            self.chk_quant,
            "Сжимает вектора для экономии места. Скорость выше, но немного падает точность. Используйте, если дисков мало."
        )

        options_layout.addWidget(params_widget)

        buttons_row = QtWidgets.QHBoxLayout()
        self.btn_check_openai = QtWidgets.QPushButton("Проверить OpenAI")
        self.btn_check_openai.clicked.connect(self.check_openai)
        self.btn_check_openai.setToolTip("Выполняет пробный запрос к OpenAI, чтобы убедиться, что ключ верный и модель доступна.")
        self.btn_check_qdrant = QtWidgets.QPushButton("Проверить Qdrant")
        self.btn_check_qdrant.clicked.connect(self.check_qdrant)
        self.btn_check_qdrant.setToolTip("Создаёт коллекции (если их нет) и показывает текущие счётчики точек.")
        self.btn_export_jsonl = QtWidgets.QPushButton("Экспорт JSONL…")
        self.btn_export_jsonl.clicked.connect(self.export_jsonl)
        self.btn_export_jsonl.setToolTip("Сохраняет подготовленные документы в один JSONL, чтобы загрузить их вне приложения.")
        self.btn_export_split = QtWidgets.QPushButton("Экспорт JSONL (отдельно)")
        self.btn_export_split.clicked.connect(self.export_jsonl_split)
        self.btn_export_split.setToolTip("Сохраняет статьи и чанки в разные файлы — удобно для ручного анализа.")
        self.btn_index = QtWidgets.QPushButton("Запустить индексацию")
        self.btn_index.clicked.connect(self.do_index)
        self.btn_index.setToolTip("Стартует потоковую индексацию: эмбеддинг → upsert в Qdrant без лишней нагрузки на память.")
        self.btn_cancel = QtWidgets.QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.cancel_index)
        self.btn_cancel.setToolTip("Останавливает текущую индексацию. Уже отправленные данные остаются в коллекции.")

        for btn in [
            self.btn_check_openai,
            self.btn_check_qdrant,
            self.btn_export_jsonl,
            self.btn_export_split,
            self.btn_index,
            self.btn_cancel,
        ]:
            buttons_row.addWidget(btn)
        buttons_row.addStretch(1)
        options_layout.addLayout(buttons_row)
        layout.addWidget(options_card)

        progress_card = self.create_card()
        progress_layout = progress_card.layout()
        progress_layout.addWidget(QtWidgets.QLabel("Ход индексации"))
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        progress_layout.addWidget(self.progress)
        progress_hint = QtWidgets.QLabel(
            "После завершения индексации можно сразу перейти на вкладку поиска и проверить качество выдачи."
        )
        progress_hint.setObjectName("OptionHint")
        progress_hint.setWordWrap(True)
        progress_layout.addWidget(progress_hint)
        layout.addWidget(progress_card)

        layout.addStretch(1)
        return page

    def check_openai(self):
        key = self.ed_api_key.text().strip()
        try:
            emb = Embedder(key)
            vec = emb.embed_one("probe")
            dim = len(vec)
            msg = f"OpenAI OK: {EMBED_MODEL}, dim={dim}"
            if dim != VECTOR_SIZE:
                msg += f"\nВНИМАНИЕ: VECTOR_SIZE={VECTOR_SIZE} → обновите до {dim} и пересоздайте коллекции."
            try:
                gpt_test = GPTMini(key)
                msg += f"\nМодель для HyDE: {gpt_test.model}"
            except Exception:
                pass
            self.log(msg)
            QtWidgets.QMessageBox.information(self, "OpenAI", msg)
            if key:
                os.environ["OPENAI_API_KEY"] = key
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "OpenAI", str(e))

    def check_qdrant(self):
        q = QdrantIndex(QDRANT_PATH)
        use_quant = self.chk_quant.isChecked()
        q.ensure_named_collection(COLL_ARTICLES, use_quantization=use_quant)
        q.ensure_named_collection(COLL_CHUNKS, use_quantization=use_quant)
        names = [c.name for c in q.client.get_collections().collections]
        msg = (
            f"Коллекции: {names}\n"
            f"{COLL_ARTICLES}: {q.client.count(COLL_ARTICLES).count}\n"
            f"{COLL_CHUNKS}: {q.client.count(COLL_CHUNKS).count}\n"
            f"Путь: {QDRANT_PATH}\nКвантизация: {'ON' if use_quant else 'OFF'}"
        )
        self.log(msg)
        QtWidgets.QMessageBox.information(self, "Qdrant", msg)

    def export_jsonl(self):
        if not (self.chunks or self.articles):
            QtWidgets.QMessageBox.warning(self, "Нет данных", "Сначала подготовьте документы на вкладке 'Импорт'.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить JSONL",
            "gk_full.jsonl",
            "JSON Lines (*.jsonl)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for d in (self.articles + self.chunks):
                f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
        manifest = {
            "version": "4.0",
            "embed_model": EMBED_MODEL,
            "vector_size": VECTOR_SIZE,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "counts": {"articles": len(self.articles), "chunks": len(self.chunks)},
        }
        with open(path + ".manifest.json", "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, ensure_ascii=False, indent=2)
        self.log(f"Экспортировано: {path}")
        QtWidgets.QMessageBox.information(
            self,
            "Экспорт",
            f"Сохранено: {path}\nМанифест: {os.path.basename(path)}.manifest.json"
        )

    def export_jsonl_split(self):
        if not (self.chunks or self.articles):
            QtWidgets.QMessageBox.warning(self, "Нет данных", "Сначала подготовьте документы на вкладке 'Импорт'.")
            return
        base_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Выбрать папку для экспорта")
        if not base_dir:
            return
        p_art = os.path.join(base_dir, "articles.jsonl")
        p_chk = os.path.join(base_dir, "chunks.jsonl")
        with open(p_art, "w", encoding="utf-8") as f:
            for d in self.articles:
                f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
        with open(p_chk, "w", encoding="utf-8") as f:
            for d in self.chunks:
                f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
        manifest = {
            "version": "4.0",
            "embed_model": EMBED_MODEL,
            "vector_size": VECTOR_SIZE,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "counts": {"articles": len(self.articles), "chunks": len(self.chunks)},
        }
        with open(os.path.join(base_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        self.log(f"Экспортировано: {p_art} и {p_chk}")
        QtWidgets.QMessageBox.information(
            self,
            "Экспорт",
            f"Сохранено: {p_art}\n{p_chk}"
        )

    def do_index(self):
        if not (self.chunks or self.articles):
            QtWidgets.QMessageBox.warning(self, "Нет данных", "Сначала подготовьте документы на вкладке 'Импорт'.")
            return
        key = self.ed_api_key.text().strip() or OPENAI_API_KEY_DEFAULT
        if key:
            os.environ["OPENAI_API_KEY"] = key
        self.index_thread = IndexWorker(
            api_key=key,
            articles=self.articles,
            chunks=self.chunks,
            do_articles=self.chk_idx_articles.isChecked(),
            do_chunks=self.chk_idx_chunks.isChecked(),
            batch=int(self.spin_batch.value()),
            use_quant=self.chk_quant.isChecked(),
        )
        self.index_thread.progressChanged.connect(self.on_index_progress)
        self.index_thread.finishedOk.connect(self.on_index_ok)
        self.index_thread.failed.connect(self.on_index_failed)
        self.index_thread.start()

    def cancel_index(self):
        if self.index_thread and self.index_thread.isRunning():
            self.index_thread.cancel()
            self.log("Запрошена отмена индексации... (батч upsert атомарен; частично добавленные батчи не откатываются)")

    def on_index_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.log(msg)

    def on_index_ok(self, msg: str):
        self.progress.setValue(100)
        self.log(msg)
        QtWidgets.QMessageBox.information(self, "Готово", msg)

    def on_index_failed(self, err: str):
        hint = ""
        if "'$.input' is invalid" in err or "invalid_request_error" in err:
            hint = (
                "\n\nВозможная причина: один из текстов был слишком длинным для модели эмбеддингов. "
                "Входы автоматически подрезаются (≤8000 ток.). Повторите запуск. "
                "Если ошибка сохраняется — проверьте соединение и ключ."
            )
        if "Несовпадение размерности эмбеддинга" in err:
            hint = (
                "\n\nОткройте вкладку индексации и выполните 'Проверить OpenAI', посмотрите фактический dim и обновите VECTOR_SIZE."
            )
        if "Cancelled" in err:
            hint = "\n\nИндексация отменена пользователем (данные консистентны, upsert батчевый)."
        self.log(f"[Индексация: ошибка] {err}{hint}")
        QtWidgets.QMessageBox.critical(self, "Индексация", f"Ошибка: {err}{hint}")

    # ---------- Search ----------
    def build_search_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Поиск по векторной базе",
            "Формулируйте запрос, при необходимости включайте HyDE-подсказку и сразу смотрите найденные нормы."
        ))

        query_card = self.create_card()
        query_layout = query_card.layout()

        query_row = QtWidgets.QHBoxLayout()
        self.ed_query = QtWidgets.QLineEdit()
        self.ed_query.setPlaceholderText("Например: ст. 395 проценты за пользование чужими денежными средствами")
        self.ed_query.setToolTip("Введите вопрос или ссылку на статью. Приложение само подстроит вес заголовков и найдёт релевантные фрагменты.")
        self.btn_search = QtWidgets.QPushButton("Старт поиска")
        self.btn_search.clicked.connect(self.do_search)
        self.btn_search.setToolTip("Запускает поиск по Qdrant, учитывая выбранные настройки и возможные фильтры по дате.")
        query_row.addWidget(self.ed_query, 1)
        query_row.addWidget(self.btn_search)
        query_layout.addLayout(query_row)

        params_widget = QtWidgets.QWidget()
        params_grid = QtWidgets.QGridLayout(params_widget)
        params_grid.setColumnStretch(1, 1)
        params_grid.setHorizontalSpacing(18)
        params_grid.setVerticalSpacing(10)

        self.ed_asof = QtWidgets.QDateEdit()
        self.ed_asof.setCalendarPopup(True)
        self.ed_asof.setDisplayFormat("yyyy-MM-dd")
        self.ed_asof.setSpecialValueText("")
        self.ed_asof.setDate(QtCore.QDate.currentDate())
        row = 0
        row = self.add_option_row(
            params_grid,
            row,
            "Дата as-of",
            self.ed_asof,
            "Если нужно видеть нормы на конкретную дату, установите её здесь. Пустое значение означает 'сейчас'."
        )

        self.spin_k = QtWidgets.QSpinBox()
        self.spin_k.setRange(1, 10)
        self.spin_k.setValue(5)
        row = self.add_option_row(
            params_grid,
            row,
            "Количество ответов",
            self.spin_k,
            "Сколько лучших фрагментов показать в выдаче. Большее число — шире контекст."
        )

        self.spin_fuse_title = QtWidgets.QDoubleSpinBox()
        self.spin_fuse_title.setRange(0.0, 1.0)
        self.spin_fuse_title.setSingleStep(0.05)
        self.spin_fuse_title.setValue(0.35)
        row = self.add_option_row(
            params_grid,
            row,
            "Вес заголовка",
            self.spin_fuse_title,
            "Определяет вклад заголовка статьи при смешивании результатов. Для запросов вида 'ст. N' лучше повышать значение."
        )

        self.chk_hyde = QtWidgets.QCheckBox("Использовать HyDE")
        self.chk_hyde.setChecked(True)
        row = self.add_toggle_row(
            params_grid,
            row,
            "HyDE-подсказка",
            self.chk_hyde,
            "HyDE генерирует гипотетический ответ и эмбеддит его. Это помогает поймать смыслы, даже если формулировка запроса редкая."
        )

        self.chk_client_pref = QtWidgets.QCheckBox("Включить префильтр")
        self.chk_client_pref.setChecked(True)
        row = self.add_toggle_row(
            params_grid,
            row,
            "Клиентский префильтр",
            self.chk_client_pref,
            "Быстро отсеивает нерелевантные документы на стороне клиента. Отключайте, если хотите увидеть абсолютно все кандидаты."
        )

        query_layout.addWidget(params_widget)
        layout.addWidget(query_card)

        results_card = self.create_card()
        results_layout = results_card.layout()
        results_layout.addWidget(QtWidgets.QLabel("Результаты"))
        self.results = QtWidgets.QTextBrowser()
        self.results.setPlaceholderText("Здесь появятся фрагменты из Qdrant вместе с подсказками и контекстом.")
        results_layout.addWidget(self.results)
        layout.addWidget(results_card, 1)

        context_card = self.create_card()
        context_layout = context_card.layout()
        btns = QtWidgets.QHBoxLayout()
        self.btn_copy_ctx = QtWidgets.QPushButton("Скопировать контекст")
        self.btn_copy_ctx.clicked.connect(self.copy_context)
        self.btn_copy_ctx.setToolTip("Копирует подобранные фрагменты в буфер обмена — удобно передавать их в GPT.")
        self.btn_save_ctx = QtWidgets.QPushButton("Сохранить в файл")
        self.btn_save_ctx.clicked.connect(self.save_context)
        self.btn_save_ctx.setToolTip("Сохраняет блоки контекста в обычный текстовый файл.")
        self.btn_clear_cache = QtWidgets.QPushButton("Очистить кэш")
        self.btn_clear_cache.clicked.connect(self.clear_search_cache)
        self.btn_clear_cache.setToolTip("Удаляет прогретые данные Qdrant, чтобы заново прогрузить актуальное состояние коллекций.")
        btns.addWidget(self.btn_copy_ctx)
        btns.addWidget(self.btn_save_ctx)
        btns.addWidget(self.btn_clear_cache)
        btns.addStretch(1)
        context_layout.addLayout(btns)
        context_hint = QtWidgets.QLabel(
            "Контекст можно скопировать в любую LLM или использовать как проверку найденных норм вручную."
        )
        context_hint.setObjectName("OptionHint")
        context_hint.setWordWrap(True)
        context_layout.addWidget(context_hint)
        layout.addWidget(context_card)

        layout.addStretch(1)
        return page

    def copy_context(self):
        if not self._last_rag_blocks:
            QtWidgets.QMessageBox.information(self, "Копирование", "Сначала выполните поиск, чтобы появился контекст.")
            return
        text = "\n\n---\n\n".join(self._last_rag_blocks)
        QtWidgets.QApplication.clipboard().setText(text)
        self.log("Контекст скопирован в буфер обмена.")

    def save_context(self):
        if not self._last_rag_blocks:
            QtWidgets.QMessageBox.information(self, "Сохранить", "Нет контекста для сохранения — выполните поиск.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить контекст",
            "context.txt",
            "Text (*.txt)"
        )
        if not path:
            return
        sep = "\n\n---\n\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(sep.join(self._last_rag_blocks))
        self.log(f"Контекст сохранён: {path}")

    def clear_search_cache(self):
        self.search_cache = None
        self.cache_progress_lbl.setText("Кэш очищен")
        self.log("Поисковый кэш очищен.")

    def _compat_named_search(self, client: QdrantClient, collection: str, vector_name: str, vector: List[float], limit: int):
        attempts = [
            {"query_vector": (vector_name, vector)},
            {"query_vector": {"name": vector_name, "vector": vector}},
        ]
        for base in attempts:
            for filter_key in ("query_filter", "filter"):
                kwargs = dict(
                    collection_name=collection,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                kwargs.update(base)
                try:
                    return client.search(**kwargs)
                except TypeError:
                    continue
        raise RuntimeError("Эта версия qdrant-client не поддерживает совместимый поиск по named-векторам.")

    def build_help_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Справка и подсказки",
            "Короткие ответы на вопросы «зачем нужна каждая опция» и что делать при ошибках."
        ))

        quick_card = self.create_card()
        quick_layout = quick_card.layout()
        quick_title = QtWidgets.QLabel("План действий")
        quick_title.setObjectName("SectionTitle")
        quick_layout.addWidget(quick_title)
        quick_text = QtWidgets.QLabel(
            "<ol style='margin-left:18px'>"
            "<li><b>Импорт.</b> Добавьте файлы и убедитесь, что анализ не показывает предупреждений по токенам.</li>"
            "<li><b>Индексация.</b> Введите ключ OpenAI, проверьте размерность и запустите потоковую загрузку в Qdrant.</li>"
            "<li><b>Поиск.</b> Сформулируйте вопрос, при необходимости задайте дату as-of и получите контекст.</li>"
            "<li><b>Лаборатория.</b> Используйте только если нужна ручная проверка эмбеддингов или точечный upsert.</li>"
            "</ol>"
        )
        quick_text.setObjectName("OptionHint")
        quick_text.setWordWrap(True)
        quick_layout.addWidget(quick_text)
        layout.addWidget(quick_card)

        faq_card = self.create_card()
        faq_layout = faq_card.layout()
        faq_layout.addWidget(QtWidgets.QLabel("Частые вопросы"))
        faq_text = QtWidgets.QLabel(
            "<ul style='margin-left:16px'>"
            "<li><b>Зачем ключ OpenAI?</b> Он нужен, чтобы считать эмбеддинги и, при желании, обогащать summary.</li>"
            "<li><b>Что такое HyDE?</b> Это генерация чернового ответа перед поиском. Если запросы простые, можно отключить.</li>"
            "<li><b>Нужен ли Qdrant-сервер?</b> Локальная папка создаётся автоматически. Для production используйте удалённый инстанс.</li>"
            "<li><b>Как понять, что документ готов?</b> На вкладке импорта смотрите на предупреждения и количество токенов.</li>"
            "</ul>"
        )
        faq_text.setObjectName("OptionHint")
        faq_text.setWordWrap(True)
        faq_layout.addWidget(faq_text)
        layout.addWidget(faq_card)

        tips_card = self.create_card()
        tips_layout = tips_card.layout()
        tips_layout.addWidget(QtWidgets.QLabel("Если что-то пошло не так"))
        tips_text = QtWidgets.QLabel(
            "<ul style='margin-left:16px'>"
            "<li><b>Нет ключа.</b> Введите тестовый плейсхолдер или задайте переменную окружения OPENAI_API_KEY.</li>"
            "<li><b>Несовпадение размерности.</b> Откройте вкладку индексации и нажмите «Проверить OpenAI» — приложение подскажет верное значение.</li>"
            "<li><b>Слишком длинный текст.</b> Сократите документ или разбейте его — приложение покажет предупреждение в аналитике.</li>"
            "<li><b>Ничего не находится.</b> Убедитесь, что коллекции проиндексированы и прогрели кэш кнопкой «Очистить кэш» на вкладке поиска.</li>"
            "</ul>"
        )
        tips_text.setObjectName("OptionHint")
        tips_text.setWordWrap(True)
        tips_layout.addWidget(tips_text)
        layout.addWidget(tips_card)

        layout.addStretch(1)
        return page

    # ---------- Vector Lab ----------
    def build_vector_lab_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Vector Lab",
            "Опциональная лаборатория: создавайте эмбеддинги, смотрите ключевые метрики и проверяйте их в Qdrant, когда нужны дополнительные проверки."
        ))

        top_card = self.create_card()
        top_layout = top_card.layout()
        top_layout.addWidget(QtWidgets.QLabel("Текст для анализа"))
        self.vlab_input = QtWidgets.QPlainTextEdit()
        self.vlab_input.setPlaceholderText("Вставьте фрагмент нормы или пользовательский запрос…")
        top_layout.addWidget(self.vlab_input)

        controls = QtWidgets.QHBoxLayout()
        self.btn_vlab_embed = QtWidgets.QPushButton("Получить эмбеддинг")
        self.btn_vlab_embed.clicked.connect(self.run_vector_probe)
        self.btn_vlab_embed.setToolTip("Вычисляет эмбеддинг для текста и показывает, сколько токенов и ссылок внутри.")
        self.btn_vlab_copy = QtWidgets.QPushButton("Копировать вектор")
        self.btn_vlab_copy.clicked.connect(self.copy_vector_to_clipboard)
        self.btn_vlab_copy.setToolTip("Сохраняет последний эмбеддинг в буфер обмена в формате JSON.")
        controls.addWidget(self.btn_vlab_embed)
        controls.addWidget(self.btn_vlab_copy)
        controls.addStretch(1)
        top_layout.addLayout(controls)

        self.vlab_info = QtWidgets.QTextBrowser()
        self.vlab_info.setPlaceholderText("Результаты по эмбеддингу и диагностике появятся здесь.")
        top_layout.addWidget(self.vlab_info)
        layout.addWidget(top_card, 1)

        bottom_card = self.create_card()
        bottom_layout = bottom_card.layout()
        bottom_layout.addWidget(QtWidgets.QLabel("Проверка в Qdrant"))

        controls2 = QtWidgets.QHBoxLayout()
        self.vlab_collection = QtWidgets.QComboBox()
        self.vlab_collection.setToolTip("Выберите коллекцию Qdrant для поиска. Список обновляется по кнопке слева.")
        self.vlab_vector_type = QtWidgets.QComboBox()
        self.vlab_vector_type.addItems(["title_vec", "body_vec"])
        self.vlab_vector_type.setToolTip("Какой вектор использовать при поиске: заголовок или тело документа.")
        self.vlab_limit = QtWidgets.QSpinBox()
        self.vlab_limit.setRange(1, 50)
        self.vlab_limit.setValue(10)
        self.vlab_limit.setToolTip("Сколько ближайших результатов запросить у Qdrant.")
        self.btn_vlab_refresh = QtWidgets.QPushButton("Обновить коллекции")
        self.btn_vlab_refresh.clicked.connect(self.refresh_vector_lab_collections)
        self.btn_vlab_refresh.setToolTip("Подтягивает актуальный список коллекций из локального Qdrant.")
        self.btn_vlab_search = QtWidgets.QPushButton("Искать в Qdrant")
        self.btn_vlab_search.clicked.connect(self.run_vector_probe)
        self.btn_vlab_search.setToolTip("Использует последний эмбеддинг и находит похожие элементы в выбранной коллекции.")
        controls2.addWidget(QtWidgets.QLabel("Коллекция:"))
        controls2.addWidget(self.vlab_collection, 1)
        controls2.addWidget(QtWidgets.QLabel("Вектор:"))
        controls2.addWidget(self.vlab_vector_type)
        controls2.addWidget(QtWidgets.QLabel("Top-N:"))
        controls2.addWidget(self.vlab_limit)
        controls2.addWidget(self.btn_vlab_refresh)
        controls2.addWidget(self.btn_vlab_search)
        bottom_layout.addLayout(controls2)

        self.vlab_results = QtWidgets.QTableWidget(0, 5)
        self.vlab_results.setHorizontalHeaderLabels(["Score", "ID", "Статья", "Глава", "Фрагмент"])
        self.vlab_results.horizontalHeader().setStretchLastSection(True)
        self.vlab_results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.vlab_results.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        bottom_layout.addWidget(self.vlab_results, 1)

        layout.addWidget(bottom_card, 1)
        layout.addStretch(1)
        self.refresh_vector_lab_collections()
        return page

    def refresh_vector_lab_collections(self):
        try:
            qdr = QdrantIndex(QDRANT_PATH)
            cols = qdr.client.get_collections().collections or []
            names = [c.name for c in cols]
        except Exception as e:
            self.vlab_collection.clear()
            self.vlab_collection.addItem("Нет подключения")
            self.vlab_collection.setEnabled(False)
            self.vlab_results.setRowCount(0)
            self.vlab_info.setText(f"Не удалось получить список коллекций: {e}")
            return
        self.vlab_collection.setEnabled(True)
        self.vlab_collection.clear()
        if not names:
            self.vlab_collection.addItem("Коллекции отсутствуют")
            self.vlab_collection.setEnabled(False)
        else:
            self.vlab_collection.addItems(names)

    def copy_vector_to_clipboard(self):
        if not self._last_vector:
            QtWidgets.QMessageBox.information(self, "Vector Lab", "Сначала сгенерируйте эмбеддинг.")
            return
        cb = QtWidgets.QApplication.clipboard()
        cb.setText(json.dumps(self._last_vector)[:15000])
        self.log("Вектор сохранён в буфер обмена.")

    def run_vector_probe(self):
        text = self.vlab_input.toPlainText().strip()
        key = self.ed_api_key.text().strip() or os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY_DEFAULT
        if not key:
            QtWidgets.QMessageBox.warning(self, "Vector Lab", "Укажите OpenAI API Key на вкладке 'Индексация'.")
            return
        vector: Optional[List[float]] = None
        info_chunks: List[str] = []
        try:
            emb = Embedder(key)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Vector Lab", f"Не удалось создать Embedder: {e}")
            return

        if text:
            try:
                vector = emb.embed_one(text)
                self._last_vector = vector
                info = analyze_text_content(text)
                info_chunks.append(
                    "\n".join([
                        f"Размер эмбеддинга: {len(vector)}",
                        f"Оценка токенов: {info.get('rough_tokens')}",
                        f"Ключевые слова: {', '.join(info.get('keywords', [])) or '—'}",
                        f"Найденные ссылки: {', '.join(info.get('references', [])) or '—'}",
                    ])
                )
                if info.get("warnings"):
                    info_chunks.append("Предупреждения:\n" + "\n".join(f"• {w}" for w in info["warnings"]))
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Vector Lab", f"Ошибка генерации эмбеддинга: {e}")
                return
        else:
            vector = self._last_vector

        if vector is None:
            QtWidgets.QMessageBox.information(self, "Vector Lab", "Введите текст или используйте ранее вычисленный вектор.")
            return

        if info_chunks:
            self.vlab_info.setText("\n\n".join(info_chunks))

        collection_name = self.vlab_collection.currentText()
        if not collection_name or not self.vlab_collection.isEnabled():
            return
        try:
            qdr = QdrantIndex(QDRANT_PATH)
            res = self._compat_named_search(
                qdr.client,
                collection_name,
                self.vlab_vector_type.currentText(),
                vector,
                self.vlab_limit.value(),
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Vector Lab", f"Ошибка поиска в Qdrant: {e}")
            return

        self.vlab_results.setRowCount(len(res))
        for row, point in enumerate(res):
            self.vlab_results.setItem(row, 0, QtWidgets.QTableWidgetItem(f"{point.score:.4f}"))
            self.vlab_results.setItem(row, 1, QtWidgets.QTableWidgetItem(str(point.id)))
            payload = point.payload or {}
            self.vlab_results.setItem(row, 2, QtWidgets.QTableWidgetItem(str(payload.get("article", "—"))))
            self.vlab_results.setItem(row, 3, QtWidgets.QTableWidgetItem(str(payload.get("chapter", "—"))))
            snippet = (payload.get("text") or "")[:140].replace("\n", " ")
            self.vlab_results.setItem(row, 4, QtWidgets.QTableWidgetItem(snippet))

    # ---------- Log ----------
    def build_log_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self.section_header(
            "Журнал событий",
            "Все ключевые сообщения приложения — от импорта до поиска — собираются здесь для удобного контроля."
        ))

        card = self.create_card()
        card_layout = card.layout()
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Сообщения появятся во время работы приложения.")
        card_layout.addWidget(self.log_box)
        layout.addWidget(card, 1)
        layout.addStretch(1)
        return page

    def _warm_cache_if_needed(self, step_each=8000):
        if self.search_cache is None:
            qdr = QdrantIndex(QDRANT_PATH)
            self.search_cache = SearchCache(qdr)
            self.search_cache.cache[COLL_ARTICLES] = []
            self.search_cache.cache[COLL_CHUNKS] = []
            self.search_cache.next_offsets[COLL_ARTICLES] = None
            self.search_cache.next_offsets[COLL_CHUNKS] = None
            self.log("Кеш поисковой выдачи инициализирован.")
        total_a, done_a = self.search_cache.warm_step(COLL_ARTICLES, limit_step=step_each)
        total_c, done_c = self.search_cache.warm_step(COLL_CHUNKS, limit_step=step_each)
        status = f"Кэш: articles={total_a}{'✓' if done_a else ''}, chunks={total_c}{'✓' if done_c else ''}"
        self.cache_progress_lbl.setText(status)
        self.log(status)

    def do_search(self):
        qtxt = self.ed_query.text().strip()
        if not qtxt:
            return
        k = int(self.spin_k.value())
        use_hyde = self.chk_hyde.isChecked()
        use_client_pref = self.chk_client_pref.isChecked()

        m_art = re.search(r"ст\.?\s*(\d+(?:\.\d+)*)", qtxt.lower())
        if m_art and self.spin_fuse_title.value() < 0.55:
            self.spin_fuse_title.setValue(0.55)

        w_title = float(self.spin_fuse_title.value())
        w_body = 1.0 - w_title

        as_of = self.ed_asof.date().toString("yyyy-MM-dd")
        today = QtCore.QDate.currentDate().toString("yyyy-MM-dd")
        if not as_of or as_of == today:
            as_of_iso = None
        else:
            try:
                _ = dtparser.parse(as_of)
                as_of_iso = f"{as_of}T23:59:59Z"
            except Exception:
                QtWidgets.QMessageBox.warning(self, "as_of", f"Дата as_of не распознана: {as_of}. Поиск без фильтра.")
                self.log(f"as_of parse failed: {as_of}")
                as_of_iso = None

        key = os.environ.get("OPENAI_API_KEY", "") or OPENAI_API_KEY_DEFAULT
        try:
            emb = Embedder(key)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "OpenAI", f"Embedder: {e}")
            return

        gpt_for_hyde = GPTMini(key) if key else None
        qemb = QueryEmbedder(emb, gpt_for_hyde, use_hyde=use_hyde)

        self._warm_cache_if_needed(step_each=8000)

        qdr = self.search_cache.qdr

        def prefilter(collection: str) -> Tuple[List[str], List]:
            payload_pts = list(self.search_cache.cache.get(collection, []))
            if as_of_iso and use_client_pref:
                try:
                    cut = dtparser.parse(as_of_iso).date()
                    def to_date(x):
                        try:
                            return dtparser.parse(x).date()
                        except Exception:
                            return None
                    def alive(pl: Dict) -> bool:
                        ef = to_date(pl.get("effective_from"))
                        et = to_date(pl.get("effective_to"))
                        st = (pl.get("status") or "").lower()
                        if ef and cut < ef:
                            return False
                        if et and cut > et:
                            return False
                        if "утрат" in st and (not et or cut >= et):
                            return False
                        return True
                    payload_pts = [p for p in payload_pts if alive(p.payload or {})]
                except Exception as e:
                    logger.warning(f"as_of parse in prefilter: {e}")
            ids = keyword_prefilter(payload_pts, qtxt, topk=300) if use_client_pref else []
            return ids, payload_pts

        ids_a, _ = prefilter(COLL_ARTICLES)
        ids_c, _ = prefilter(COLL_CHUNKS)

        q_title = list(qemb.embed_title_cached(qtxt))
        q_body = list(qemb.embed_body_hyde_cached(qtxt))

        def search_ids_rrf(collection, vector_name_title, vector_name_body, qvec_title, qvec_body, ids_prefilter, limit_each, as_of_iso):
            ranks_title: Dict[str, int] = {}
            ranks_body: Dict[str, int] = {}
            filters = make_asof_filters_strict(as_of_iso)

            def _list(val):
                return list(val) if val else []

            def combine_filters(base: Optional[qm.Filter], extra: Optional[qm.Filter]) -> Optional[qm.Filter]:
                if not base and not extra:
                    return None
                if not base:
                    return extra
                if not extra:
                    return base
                return qm.Filter(
                    must=_list(base.must) + _list(extra.must),
                    should=_list(base.should) + _list(extra.should),
                    must_not=_list(base.must_not) + _list(extra.must_not),
                )

            def _call_search(vector_name: str, vector_payload: List[float], flt: Optional[qm.Filter]) -> List[Any]:
                attempts = [
                    {"query_vector": (vector_name, vector_payload)},
                    {"query_vector": {"name": vector_name, "vector": vector_payload}},
                ]
                results: List[Any] = []
                for base in attempts:
                    for filter_key in ("query_filter", "filter"):
                        kwargs = dict(
                            collection_name=collection,
                            limit=limit_each,
                            with_payload=False,
                            with_vectors=False,
                        )
                        kwargs.update(base)
                        if flt is not None:
                            kwargs[filter_key] = flt
                        try:
                            res = qdr.client.search(**kwargs)
                        except TypeError:
                            continue
                        else:
                            if res:
                                results.extend(res)
                            return results
                return results

            def run_one(using_name: str, qvec: List[float]) -> List[str]:
                out_ids: List[str] = []
                base_filter = qm.Filter(must=[qm.HasIdCondition(has_id=ids_prefilter)]) if ids_prefilter else None
                for flt in filters:
                    merged = combine_filters(base_filter, flt)
                    res = _call_search(using_name, qvec, merged)
                    if res:
                        out_ids.extend([str(p.id) for p in res])
                return list(dict.fromkeys(out_ids))[:limit_each]

            ids_t = run_one(vector_name_title, qvec_title)
            ids_b = run_one(vector_name_body, qvec_body)

            ranks_title.update({pid: i + 1 for i, pid in enumerate(ids_t)})
            ranks_body.update({pid: i + 1 for i, pid in enumerate(ids_b)})

            return rrf_scores(ranks_title), rrf_scores(ranks_body)

        limit_each = max(20, k * 3)

        title_rrf_a, body_rrf_a = search_ids_rrf(
            COLL_ARTICLES, "title_vec", "body_vec", q_title, q_body, ids_a, limit_each, as_of_iso
        )
        fused_a = combine_rrf_weighted(title_rrf_a, body_rrf_a, w_title, w_body)

        title_rrf_c, body_rrf_c = search_ids_rrf(
            COLL_CHUNKS, "title_vec", "body_vec", q_title, q_body, ids_c, limit_each, as_of_iso
        )
        fused_c = combine_rrf_weighted(title_rrf_c, body_rrf_c, w_title, w_body)

        fused_all: Dict[str, float] = {}
        for dct in (fused_a, fused_c):
            for pid, sc in dct.items():
                fused_all[pid] = fused_all.get(pid, 0.0) + sc

        ranked_ids = [pid for pid, _ in sorted(fused_all.items(), key=lambda x: x[1], reverse=True)]
        id2payload = {}
        for pid in ranked_ids:
            p = self.search_cache.id2point.get(pid)
            if p:
                id2payload[pid] = p.payload or {}
        m = re.search(r"ст\.?\s*(\d+(?:\.\d+)*)", qtxt.lower())
        target_art = m.group(1) if m else None
        boost_exact_article(fused_all, id2payload, target_art)
        ranked_ids = [pid for pid, _ in sorted(fused_all.items(), key=lambda x: x[1], reverse=True)]

        def pick_points_from_cache(ids_sorted: List[str]) -> List:
            out = []
            for pid in ids_sorted:
                p = self.search_cache.id2point.get(pid)
                if p is not None:
                    out.append(p)
            return out

        prelim_points = pick_points_from_cache(ranked_ids)[:max(20, k * 4)]

        points = prelim_points[:k]

        follow_articles = []
        for p in points:
            refs = (p.payload or {}).get("references") or []
            for a in refs[:3]:
                follow_articles.append(a)
        follow_articles = list(dict.fromkeys(follow_articles))[:5]

        extra_points = []
        for a in follow_articles:
            try:
                extra_points += fetch_by_article(qdr, COLL_ARTICLES, a, limit=1)
            except Exception as e:
                logger.warning(f"xref fetch: {e}")

        all_points = points + extra_points
        final_points = dedup_limit(all_points, k)

        out = [
            "<style>",
            "body {background:transparent;color:#e2e8f0;font-family:'Inter','Segoe UI',sans-serif;}",
            ".result-card {background:rgba(15,23,42,0.72);border:1px solid rgba(148,163,184,0.25);border-radius:18px;padding:18px;margin:12px 0;box-shadow:0 18px 36px rgba(15,23,42,0.45);}",
            ".result-card h4 {margin:0 0 8px;font-size:18px;color:#38bdf8;}",
            ".result-meta {display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;font-size:12px;color:#cbd5f5;}",
            ".badge {background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.4);border-radius:999px;padding:2px 10px;}",
            ".result-summary {font-style:italic;color:#f8fafc;margin-bottom:10px;}",
            "pre {background:rgba(15,23,42,0.9);border-radius:12px;padding:12px;white-space:pre-wrap;font-family:'JetBrains Mono','Fira Code',monospace;font-size:13px;color:#e2e8f0;}",
            "</style><h3>Результаты</h3>",
        ]
        self._last_rag_blocks = []
        if not final_points:
            out.append("<i>Пусто.</i>")
        else:
            for p in final_points:
                pl = p.payload or {}
                title = pl.get("title") or ""
                part = pl.get("part") or "—"
                ch = pl.get("chapter") or "—"
                art = pl.get("article") or "—"
                anchor = pl.get("anchor") or ""
                src = pl.get("source") or ""
                summ = pl.get("semantic_summary") or ""
                snippet = safe_html((pl.get("text") or "")[:900])
                out.append(
                    "<div class='result-card'>"
                    f"<h4>{safe_html(title)}</h4>"
                    f"<div class='result-meta'><span class='badge'>Часть: {safe_html(str(part))}</span>"
                    f"<span class='badge'>Глава: {safe_html(str(ch))}</span>"
                    f"<span class='badge'>Статья: {safe_html(str(art))}</span></div>"
                    f"<div class='result-summary'>{safe_html(summ)}</div>"
                    f"<div style='font-size:12px;color:#94a3b8;margin-bottom:8px;'>{safe_html(anchor)} · {safe_html(src)}</div>"
                    f"<pre>{snippet}…</pre>"
                    "</div>"
                )
                self._last_rag_blocks.append(pl.get("formatted_text") or pl.get("text", ""))

            out.append("<h4>Контекст для GPT</h4>")
            sep = "\n\n---\n\n"
            joined_ctx = sep.join(self._last_rag_blocks)
            out.append("<pre style='white-space:pre-wrap;font-family:inherit;background:rgba(15,23,42,0.85);border-radius:12px;padding:14px;'>" + safe_html(joined_ctx) + "</pre>")

        self.results.setHtml("\n".join(out))


# ============================
# CLI (headless) режим
# ============================
def cli_main(args):
    files = []
    for p in args.files:
        if os.path.isdir(p):
            for root, _, fnames in os.walk(p):
                for n in fnames:
                    if os.path.splitext(n)[1].lower() in (".rtf",".pdf",".docx",".txt"):
                        files.append(os.path.join(root, n))
        else:
            files.append(p)
    if not files:
        print("Нет входных файлов."); return 2

    key = os.environ.get("OPENAI_API_KEY","") or OPENAI_API_KEY_DEFAULT
    if not key:
        print("Установите переменную OPENAI_API_KEY или пропишите ключ в коде."); return 2

    builder = CorpusBuilder(chunk_tokens=args.chunk, overlap=args.overlap)
    eff_from = args.eff_from
    eff_to   = args.eff_to
    status   = args.status

    all_chunks: List[LawDoc] = []; all_articles: List[LawDoc] = []
    for path in files:
        raw = extract_text_from_file(path)
        part = auto_detect_part(path)
        chunks, arts = builder.prepare_docs(
            full_text=raw, code_name=args.code, part_name=part, title=args.title, source_path=path,
            effective_from=eff_from, effective_to=eff_to, status=status
        )
        all_chunks.extend(chunks); all_articles.extend(arts)
        print(f"OK: {os.path.basename(path)} → статей: {len(arts)}; чанков: {len(chunks)}")
    print(f"Итого: статей={len(all_articles)}, чанков={len(all_chunks)}")

    emb = Embedder(key)
    dim = len(emb.embed_one("probe"))
    if dim != VECTOR_SIZE:
        print(f"Несовпадение размерности эмбеддинга: модель дала dim={dim}, а VECTOR_SIZE={VECTOR_SIZE}. Обновите VECTOR_SIZE и пересоздайте коллекции.")
        return 2

    q = QdrantIndex(QDRANT_PATH)
    if args.articles: q.ensure_named_collection(COLL_ARTICLES, use_quantization=args.quant)
    if args.chunks:   q.ensure_named_collection(COLL_CHUNKS,   use_quantization=args.quant)

    def cancel_flag():
        return False

    if args.articles and all_articles:
        def cb(pos, tot):
            pct = int((pos/max(1,tot))*50)
            sys.stdout.write(f"\rСтатьи: {pos}/{tot} ({pct}%)"); sys.stdout.flush()
        q.upsert_batch_stream(COLL_ARTICLES, all_articles, emb, args.batch, cancel_flag=cancel_flag, progress_cb=cb)
        print("\nСтатьи индексированы.")

    if args.chunks and all_chunks:
        def cb2(pos, tot):
            pct = 50 + int((pos/max(1,tot))*50)
            sys.stdout.write(f"\rЧанки: {pos}/{tot} ({pct}%)"); sys.stdout.flush()
        q.upsert_batch_stream(COLL_CHUNKS, all_chunks, emb, args.batch, cancel_flag=cancel_flag, progress_cb=cb2)
        print("\nЧанки индексированы.")

    print("Готово.")
    return 0


# ============================
# main
# ============================
def main():
    parser = argparse.ArgumentParser(description="ГК РФ — Индексатор (GUI/CLI)")
    parser.add_argument("--cli", action="store_true", help="запустить в headless режиме (без GUI)")
    parser.add_argument("--files", nargs="*", default=[], help="файлы/папки для индексации (CLI)")
    parser.add_argument("--code", default="ГК РФ", help="краткое имя кодекса (payload: code)")
    parser.add_argument("--title", default="Гражданский кодекс Российской Федерации", help="полное название кодекса (payload: title)")
    parser.add_argument("--chunk", type=int, default=800, help="примерный размер чанка (в токенах, грубо)")
    parser.add_argument("--overlap", type=int, default=120, help="оверлап между чанками (в токенах, грубо)")
    parser.add_argument("--batch", type=int, default=32, help="размер батча для эмбеддингов/stream upsert")
    parser.add_argument("--articles", dest="articles", action="store_true", help="индексировать статьи")
    parser.add_argument("--no-articles", dest="articles", action="store_false", help="не индексировать статьи")
    parser.set_defaults(articles=True)
    parser.add_argument("--chunks", dest="chunks", action="store_true", help="индексировать чанки")
    parser.add_argument("--no-chunks", dest="chunks", action="store_false", help="не индексировать чанки")
    parser.set_defaults(chunks=True)
    parser.add_argument("--quant", action="store_true", help="включить int8-квантизацию (точность ниже)")
    parser.add_argument("--eff-from", dest="eff_from", default=None, help="effective_from (YYYY-MM-DD)")
    parser.add_argument("--eff-to", dest="eff_to", default=None, help="effective_to (YYYY-MM-DD)")
    parser.add_argument("--status", default="действует", help="статус нормы: действует|утратил силу|не вступил в силу")

    args = parser.parse_args()

    if args.cli:
        rc = cli_main(args)
        sys.exit(rc)
    else:
        app = QtWidgets.QApplication(sys.argv)
        app.setApplicationName("ГК РФ — Индексатор v4 · Vector Studio")
        app.setStyleSheet(APP_STYLESHEET)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()

