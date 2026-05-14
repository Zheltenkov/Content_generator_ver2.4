"""
content_gen/agents/translator.py

Агент для перевода README на целевой язык с сохранением структуры.

Переводит сгенерированный markdown на целевой язык (ru/en/ky/tg/uz).
Сохраняет структуру, форматирование и технические термины.

Ключевые механизмы отказоустойчивости:
- Секционный сплит: заголовок всегда остаётся со своим телом.
- Контекстный хедер для чанков без собственного заголовка.
- Языковой gate: посекционное сравнение перевода с оригиналом.
- Repair-mode: точечная перетрансляция непереведённых секций.
- Обработка finish_reason="length" — авторазбиение чанка.
"""

import re
import sys
from collections.abc import Callable
from difflib import SequenceMatcher

from .base.llm_client import LLMClientProtocol
from ..models.schemas import ProjectSeed
from ..utils.protected_blocks import protect_blocks, restore_blocks
from .translation_refiner import TranslationCombinerAgent, TranslationRefinerAgent

SYSTEM = """Ты — профессиональный переводчик технических документов.
Твоя задача — перевести README файл учебного проекта на {target_language}, сохраняя:
- Структуру Markdown (заголовки, списки, таблицы, код)
- Форматирование формул (LaTeX)
- Ссылки и изображения
- Технические термины (используй стандартные переводы)
- Определения терминов (используй стандартные определения на целевом языке)
- Стиль и тон (дружелюбный, на «ты»)
- Текст в кавычках («...») оставляй обычным инлайн-текстом, не превращай в заголовки (##) и не выделяй жирным (**).
- Письменность: весь переводимый текст пиши латиницей. Кириллицу оставляй только в неизменяемых именах собственных, коде, путях, ссылках и защищенных блоках.

Для английского: используй американский вариант (American English), простые конструкции, хорошая читаемость; избегай тяжёлых формальных британских оборотов.

Язык перевода: {target_language}.
"""

USER_TMPL = """Переведи следующий фрагмент README файла на {target_language}.

ВАЖНЫЕ ТРЕБОВАНИЯ:
1. Сохрани ВСЮ структуру Markdown:
   - Заголовки (# ## ###) — переведи КАЖДЫЙ заголовок на {target_language}, НЕ оставляй на исходном языке
   - НЕ добавляй заголовки типа "# README", "# Translation" или другие мета-заголовки
   - НЕ добавляй никаких заголовков, которых нет в оригинале
   - Списки (- * 1.)
   - Кодовые блоки (```)
   - Ссылки [текст](url)
   - Изображения ![alt](path)

2. Формулы LaTeX:
   - НЕ переводи формулы внутри $$...$$ или \\[...\\]
   - Сохрани все математические выражения как есть
   - Переведи только определения параметров после формул

3. ЗАЩИТА БЛОКОВ (КРИТИЧЕСКИ ВАЖНО):
   - НЕ изменяй и НЕ удаляй маркеры [[[BLOCK_N]]] — они защищают код, формулы и диаграммы
   - НЕ изменяй HTML-комментарии <!-- PROTECTED_BLOCK id=N type=... -->
   - Эти маркеры должны остаться ТОЧНО такими же, как в оригинале

4. ТАБЛИЦЫ (КРИТИЧЕСКИ ВАЖНО — ОБЯЗАТЕЛЬНО ПЕРЕВЕДИ):
   - Сохрани разметку таблиц: символы | и строки-разделители (---)
   - ОБЯЗАТЕЛЬНО переведи текст ВНУТРИ КАЖДОЙ ЯЧЕЙКИ на {target_language}
   - Переведи заголовки колонок И содержимое строк
   - НЕ оставляй текст ячеек на исходном языке
   - НЕ изменяй количество колонок и строк
   - НЕ удаляй таблицы

5. Определения терминов:
   - Используй латиницу для текста на целевом языке ({target_language})
   - Используй стандартные определения терминов на целевом языке
   - Сохрани структуру определений: "<термин> — это <определение>"

6. Технические термины:
   - Используй стандартные переводы технических терминов
   - Если термин не имеет устоявшегося перевода, используй транслитерацию

7. Стиль:
   - Сохрани дружелюбный тон
   - Используй обращение на «ты»
   - Сохрани структуру предложений

8. КРИТИЧЕСКИ ВАЖНО:
   - Переведи ВЕСЬ текст на {target_language}, включая жирные определения (**...**), подписи к рисункам, подзаголовки
   - НЕ оставляй НИ ОДНОГО предложения или фразы на исходном языке
   - НЕ используй кириллицу в переводимом тексте; пиши результат латиницей
   - Начни перевод сразу с первого элемента фрагмента, без вводных фраз
   - СОХРАНИ все маркеры [[[BLOCK_N]]] БЕЗ ИЗМЕНЕНИЙ

9. Цитаты и выделенный текст:
   - Фразы в кавычках («...» или "...") — обычный текст, не заголовки
   - Переводи их как обычный текст; НЕ оформляй их как заголовки (## или ###)

Исходный фрагмент (на русском):
{markdown}

Переведи весь фрагмент полностью, сохраняя структуру и форматирование. Начни сразу с первого элемента."""

# Промпт для точечного перевода непереведённых секций (repair-mode)
REPAIR_USER_TMPL = """Переведи следующую секцию документа на {target_language}.
Эта секция НЕ БЫЛА переведена при предыдущей попытке — переведи её ПОЛНОСТЬЮ.

ОБЯЗАТЕЛЬНО:
- Переведи ВСЕ заголовки, весь текст, ВСЕ ячейки таблиц, все жирные определения
- НЕ оставляй НИ ОДНОГО слова на исходном языке (кроме имён собственных и технических терминов без перевода)
- Пиши переводимый текст латиницей; кириллицу оставляй только в неизменяемом коде, путях, ссылках и именах собственных
- Сохрани структуру Markdown (заголовки, списки, таблицы, ссылки)
- Сохрани маркеры [[[BLOCK_N]]] без изменений
- Начни сразу с перевода, без вводных фраз

Секция:
{markdown}"""


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"(?=^##\s+)", re.MULTILINE)

# Уникальные символы для детекции языка входного документа
_LANG_FINGERPRINTS: dict[str, set[str]] = {
    "tg": set("ғӣқӯҳҷҶҲҚӮҒӢ"),
    "kg": set("ңүөҮӨҢ"),
    "en": set(),  # детектируется по отсутствию Cyrillic
}
_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
_MARKDOWN_STRIP_RE = re.compile(
    r"\[([^\]]*)\]\([^)]*\)"   # [text](url) -> text
    r"|```[^`]*```"             # code blocks
    r"|`[^`]+`"                 # inline code
    r"|\!\[[^\]]*\]\([^)]*\)"  # images
    r"|<!--.*?-->"             # comments
    r"|\[\[\[BLOCK_\d+\]\]\]"  # protected markers
    r"|\|[-:]+\|"              # table separators
    r"|[#*_|>~\-\[\]()]",      # markdown symbols
    re.DOTALL,
)


class TranslatorAgent:
    """Агент для перевода README на целевой язык."""

    def __init__(self, llm_client: LLMClientProtocol):
        self.llm = llm_client
        self._default_max_chunk_length = 10000

    # ------------------------------------------------------------------
    # input language detection
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text_content(md: str) -> str:
        """Извлекает чистый текст из markdown, убирая структурные элементы."""
        text = _MARKDOWN_STRIP_RE.sub(" ", md)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _detect_source_language(cls, markdown: str) -> str | None:
        """Определяет язык входного документа по уникальным символам.

        Returns:
            Код языка ("ru", "tg", "kg", "en") или None если не удалось определить.
        """
        text = cls._extract_text_content(markdown)
        if not text:
            return None

        total_alpha = sum(1 for c in text if c.isalpha())
        if total_alpha < 20:
            return None

        cyrillic_count = len(_CYRILLIC_RE.findall(text))
        cyrillic_ratio = cyrillic_count / total_alpha if total_alpha else 0

        if cyrillic_ratio < 0.3:
            return "en"

        for lang_code, fingerprint_chars in _LANG_FINGERPRINTS.items():
            if not fingerprint_chars:
                continue
            fp_count = sum(1 for c in text if c in fingerprint_chars)
            if fp_count >= 5:
                return lang_code

        if cyrillic_ratio > 0.5:
            return "ru"

        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_model_prefixes(text: str) -> str:
        """Удаляет типичные служебные префиксы модели."""
        cleaned = (text or "").strip()
        for prefix in (
            "Вот перевод:\n\n",
            "Перевод:\n\n",
            "Итоговый перевод:\n\n",
            "Ниже перевод:\n\n",
            "Вот переведённый фрагмент:\n\n",
        ):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        return cleaned

    # ------------------------------------------------------------------
    # section-aware splitting (Fix 1 + Fix 2)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_logical_sections(text: str) -> list[str]:
        """Разбивает markdown на логические секции: heading + body.

        Каждая секция начинается с ``## Заголовок`` (H2) и включает весь
        текст до следующего H2 или конца документа.
        Текст до первого H2 (title, intro) — отдельная секция.
        """
        parts = _H2_SPLIT_RE.split(text)
        return [p for p in parts if p.strip()]

    def _split_section_by_paragraphs(
        self, section: str, max_length: int,
    ) -> list[str]:
        """Дробит одну длинную секцию по абзацам / грубо по длине."""
        paragraphs = [p for p in re.split(r"\n\n+", section) if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            candidate = f"{current}\n\n{para}".strip() if current else para
            if len(candidate) <= max_length:
                current = candidate
                continue
            if current.strip():
                chunks.append(current.strip())
                current = ""
            if len(para) <= max_length:
                current = para
            else:
                for i in range(0, len(para), max_length):
                    piece = para[i : i + max_length].strip()
                    if piece:
                        chunks.append(piece)
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _split_for_translation(
        self,
        protected_md: str,
        max_length: int,
        target_lang_name: str = "",
    ) -> list[str]:
        """Делит markdown на чанки, гарантируя что heading+body не разрываются.

        1. Парсим логические секции (по H2).
        2. Маленькие секции склеиваем в один чанк.
        3. Большие секции дробим по абзацам, добавляя контекстный хедер.
        """
        text = (protected_md or "").strip()
        if not text:
            return []
        if len(text) <= max_length:
            return [text]

        logical = self._parse_logical_sections(text)
        chunks: list[str] = []
        current = ""
        last_heading = ""

        for section in logical:
            heading_m = re.match(r"^(#{1,3})\s+(.+)$", section, re.MULTILINE)
            if heading_m:
                last_heading = heading_m.group(0).strip()

            if len(section) > max_length:
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                sub_chunks = self._split_section_by_paragraphs(section, max_length)
                for i, sc in enumerate(sub_chunks):
                    if i > 0 and not re.match(r"^#{1,6}\s+", sc):
                        ctx = self._make_context_header(last_heading, target_lang_name)
                        sc = f"{ctx}\n\n{sc}"
                    chunks.append(sc.strip())
                continue

            candidate = f"{current}\n\n{section}".strip() if current else section
            if len(candidate) > max_length:
                if current.strip():
                    chunks.append(current.strip())
                current = section
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return [c for c in chunks if c]

    @staticmethod
    def _make_context_header(last_heading: str, target_lang_name: str) -> str:
        """Генерирует контекстную строку для чанка без заголовка."""
        if not last_heading:
            return ""
        return (
            f"[КОНТЕКСТ: Продолжение раздела \"{last_heading}\". "
            f"Переведи ВСЁ на {target_lang_name}, включая таблицы, "
            f"заголовки и определения. Пиши перевод латиницей. Не оставляй текст на исходном языке.]"
        )

    # ------------------------------------------------------------------
    # single-chunk translation (Fix 6)
    # ------------------------------------------------------------------

    def _translate_single_chunk(
        self,
        chunk_markdown: str,
        target_lang_name: str,
        system_prompt: str,
    ) -> str:
        """Переводит один chunk. При finish_reason=length делит пополам."""
        part_prompt = USER_TMPL.format(
            target_language=target_lang_name,
            markdown=chunk_markdown,
        )
        translated = self.llm.complete(
            system=system_prompt, user=part_prompt, temperature=0.2,
        )

        if hasattr(self.llm, '_last_finish_reason') and self.llm._last_finish_reason == "length":
            print(
                "  ⚠ finish_reason=length, разбиваю чанк пополам",
                file=sys.stderr, flush=True,
            )
            mid = len(chunk_markdown) // 2
            nl = chunk_markdown.find("\n\n", mid)
            if nl == -1:
                nl = mid
            part_a = chunk_markdown[:nl].strip()
            part_b = chunk_markdown[nl:].strip()
            t_a = self._cleanup_model_prefixes(
                self.llm.complete(system=system_prompt,
                                  user=USER_TMPL.format(target_language=target_lang_name, markdown=part_a),
                                  temperature=0.2)
            )
            t_b = self._cleanup_model_prefixes(
                self.llm.complete(system=system_prompt,
                                  user=USER_TMPL.format(target_language=target_lang_name, markdown=part_b),
                                  temperature=0.2)
            )
            return f"{t_a}\n\n{t_b}"

        return self._cleanup_model_prefixes(translated)

    # ------------------------------------------------------------------
    # chunked translation
    # ------------------------------------------------------------------

    def _translate_with_chunking(
        self,
        protected_md: str,
        target_lang_name: str,
        system_prompt: str,
        max_length: int,
    ) -> str:
        """Переводит markdown по чанкам и склеивает результат."""
        chunks = self._split_for_translation(protected_md, max_length, target_lang_name)
        if len(chunks) <= 1:
            return self._translate_single_chunk(protected_md, target_lang_name, system_prompt)

        print(
            f"  README длинный ({len(protected_md)} символов), "
            f"перевод по частям: {len(chunks)}",
            file=sys.stderr, flush=True,
        )
        translated_parts: list[str] = []
        for idx, chunk in enumerate(chunks, 1):
            print(
                f"  Перевод chunk {idx}/{len(chunks)} ({len(chunk)} символов)",
                file=sys.stderr, flush=True,
            )
            translated_parts.append(
                self._translate_single_chunk(chunk, target_lang_name, system_prompt),
            )
        return "\n\n".join(translated_parts)

    # ------------------------------------------------------------------
    # language coverage validation (Fix 4)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_by_headings(md: str) -> list[tuple[str, str]]:
        """Разбивает markdown на пары (heading_line, body).

        Возвращает список ``(heading, body)`` где heading — строка заголовка
        (может быть пустой для текста до первого заголовка).
        """
        parts: list[tuple[str, str]] = []
        positions = [(m.start(), m.group(0)) for m in _HEADING_RE.finditer(md)]
        if not positions:
            return [("", md)]

        if positions[0][0] > 0:
            parts.append(("", md[: positions[0][0]].strip()))

        for i, (pos, heading) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(md)
            body = md[pos + len(heading) : end].strip()
            parts.append((heading, body))

        return parts

    def _validate_language_coverage(
        self, original: str, translated: str,
    ) -> list[tuple[int, str, float]]:
        """Находит секции, которые не были переведены.

        Сравнивает чистый текст (без markdown-разметки) каждой секции
        перевода с соответствующей секцией оригинала.

        Returns:
            Список ``(section_index, heading, similarity)`` для непереведённых секций
            (similarity > 0.70).
        """
        orig_sections = self._split_by_headings(original)
        trans_sections = self._split_by_headings(translated)

        untranslated: list[tuple[int, str, float]] = []

        for i in range(min(len(orig_sections), len(trans_sections))):
            o_heading, o_body = orig_sections[i]
            t_heading, t_body = trans_sections[i]

            if not o_body.strip():
                continue

            o_text = self._extract_text_content(o_body)
            t_text = self._extract_text_content(t_body)

            if len(o_text) < 20:
                continue

            ratio = SequenceMatcher(None, o_text, t_text).ratio()
            if ratio > 0.70:
                heading_label = t_heading or o_heading or f"(section {i})"
                untranslated.append((i, heading_label, ratio))

        return untranslated

    # ------------------------------------------------------------------
    # repair-mode: точечная перетрансляция (Fix 5)
    # ------------------------------------------------------------------

    def _repair_untranslated_sections(
        self,
        original: str,
        translated: str,
        target_lang_name: str,
    ) -> str:
        """Находит непереведённые секции и перетранслирует их точечно."""
        untranslated = self._validate_language_coverage(original, translated)
        if not untranslated:
            return translated

        print(
            f"  REPAIR: найдено {len(untranslated)} непереведённых секций",
            file=sys.stderr, flush=True,
        )

        orig_sections = self._split_by_headings(original)
        trans_sections = self._split_by_headings(translated)
        system_prompt = SYSTEM.format(target_language=target_lang_name)

        for sec_idx, heading, ratio in untranslated:
            if sec_idx >= len(orig_sections) or sec_idx >= len(trans_sections):
                continue

            o_heading, o_body = orig_sections[sec_idx]
            original_section = f"{o_heading}\n\n{o_body}".strip() if o_heading else o_body.strip()

            print(
                f"  REPAIR секции [{sec_idx}] "
                f"{heading[:60]!r} (similarity={ratio:.2f}, "
                f"{len(original_section)} символов)",
                file=sys.stderr, flush=True,
            )

            repair_prompt = REPAIR_USER_TMPL.format(
                target_language=target_lang_name,
                markdown=original_section,
            )
            try:
                repaired = self.llm.complete(
                    system=system_prompt, user=repair_prompt, temperature=0.2,
                )
                repaired = self._cleanup_model_prefixes(repaired)

                if not repaired.strip():
                    print(
                        f"  REPAIR [{sec_idx}]: пустой ответ, пропускаю",
                        file=sys.stderr, flush=True,
                    )
                    continue

                o_text = self._extract_text_content(o_body)
                r_text = self._extract_text_content(repaired)
                new_ratio = SequenceMatcher(None, o_text, r_text).ratio()
                if new_ratio < ratio:
                    t_heading, t_body = trans_sections[sec_idx]
                    old_text = f"{t_heading}\n\n{t_body}".strip() if t_heading else t_body.strip()
                    translated = translated.replace(old_text, repaired, 1)
                    print(
                        f"  REPAIR [{sec_idx}]: OK (similarity {ratio:.2f} -> {new_ratio:.2f})",
                        file=sys.stderr, flush=True,
                    )
                else:
                    print(
                        f"  REPAIR [{sec_idx}]: не улучшилось ({new_ratio:.2f}), пропускаю",
                        file=sys.stderr, flush=True,
                    )
            except Exception as e:
                print(
                    f"  REPAIR [{sec_idx}]: ошибка {e}, пропускаю",
                    file=sys.stderr, flush=True,
                )

        return translated

    # ------------------------------------------------------------------
    # full translation attempt
    # ------------------------------------------------------------------

    def _run_translation_attempt(
        self,
        protected_md: str,
        markdown_original: str,
        blocks: list,
        target_lang_name: str,
        target_language_code: str,
        translation_mode: str,
        progress_callback: Callable[[str], None] | None,
        max_length: int,
    ) -> tuple[str, bool, list[str]]:
        """Один полный цикл перевода + refine/combine + repair + валидация.

        Returns:
            (translated_md, is_valid, issues)
        """
        system_prompt = SYSTEM.format(target_language=target_lang_name)
        translated = self._translate_with_chunking(
            protected_md=protected_md,
            target_lang_name=target_lang_name,
            system_prompt=system_prompt,
            max_length=max_length,
        )
        translated = restore_blocks(translated, blocks)
        print("  Блоки восстановлены после перевода", file=sys.stderr, flush=True)
        if progress_callback:
            progress_callback("translate")

        if translation_mode == "combined":
            refiner = TranslationRefinerAgent(self.llm)
            refined = refiner.refine(translated, target_language=target_language_code)
            if progress_callback:
                progress_callback("refine")
            combiner = TranslationCombinerAgent(self.llm)
            translated = combiner.combine(translated, refined, target_language=target_language_code)
            if progress_callback:
                progress_callback("combine")

        translated = self._cleanup_translation(translated, markdown_original)

        # --- repair-mode: точечная починка непереведённых секций ---
        untranslated_before = self._validate_language_coverage(markdown_original, translated)
        if untranslated_before:
            print(
                f"  Обнаружено {len(untranslated_before)} непереведённых секций, запускаю repair",
                file=sys.stderr, flush=True,
            )
            if progress_callback:
                progress_callback("repair")
            translated = self._repair_untranslated_sections(
                markdown_original, translated, target_lang_name,
            )
            translated = self._cleanup_translation(translated, markdown_original)

        if progress_callback:
            progress_callback("validate")

        is_valid, structure_issues = self._validate_translation_structure(
            markdown_original, translated,
        )

        # Языковой gate: проверяем остаточные непереведённые секции
        remaining = self._validate_language_coverage(markdown_original, translated)
        for sec_idx, heading, ratio in remaining:
            structure_issues.append(
                f"Секция [{sec_idx}] {heading[:50]!r} не переведена (similarity={ratio:.2f})"
            )

        final_valid = is_valid and len(remaining) == 0
        return translated, final_valid, structure_issues

    # ------------------------------------------------------------------
    # cleanup & structural validation
    # ------------------------------------------------------------------

    def _cleanup_translation(self, translated: str, original: str) -> str:
        """Очищает перевод от лишних заголовков и мета-информации."""
        unwanted_headers = [
            r'^#\s+README\s*$',
            r'^#\s+Translation\s*$',
            r'^#\s+Translated\s+README\s*$',
            r'^##\s+README\s*$',
            r'^##\s+Translation\s*$',
        ]
        for pattern in unwanted_headers:
            if not re.search(pattern, original, flags=re.MULTILINE | re.IGNORECASE):
                translated = re.sub(pattern, '', translated, flags=re.MULTILINE | re.IGNORECASE)

        translated = re.sub(r'\n{3,}', '\n\n', translated)
        # Удаляем контекстные хедеры, если LLM их оставил
        translated = re.sub(
            r'^\[КОНТЕКСТ:.*?\]\s*\n?', '', translated, flags=re.MULTILINE,
        )
        return translated.strip()

    def _validate_translation_structure(
        self, original: str, translated: str,
    ) -> tuple[bool, list[str]]:
        """Проверяет соответствие структуры перевода оригиналу."""
        issues: list[str] = []

        def extract_headings(md: str) -> list[tuple[int, str]]:
            return [
                (len(m.group(1)), m.group(2).strip())
                for m in _HEADING_RE.finditer(md)
            ]

        original_headings = extract_headings(original)
        translated_headings = extract_headings(translated)

        if len(original_headings) != len(translated_headings):
            issues.append(
                f"Количество заголовков не совпадает: "
                f"оригинал {len(original_headings)}, перевод {len(translated_headings)}"
            )

        min_len = min(len(original_headings), len(translated_headings))
        for i in range(min_len):
            orig_level, orig_title = original_headings[i]
            trans_level, trans_title = translated_headings[i]
            if orig_level != trans_level:
                issues.append(
                    f"Несовпадение уровня заголовка #{i+1}: "
                    f"оригинал H{orig_level} '{orig_title[:50]}', "
                    f"перевод H{trans_level} '{trans_title[:50]}'"
                )

        unwanted_patterns = [
            (r'^#\s+README\s*$', "# README"),
            (r'^#\s+Translation\s*$', "# Translation"),
            (r'^#\s+Translated\s+README\s*$', "# Translated README"),
        ]
        for pattern, name in unwanted_patterns:
            if re.search(pattern, translated, re.MULTILINE | re.IGNORECASE):
                if not re.search(pattern, original, re.MULTILINE | re.IGNORECASE):
                    issues.append(f"Обнаружен лишний заголовок в переводе: {name}")

        original_h2 = [h for h in original_headings if h[0] == 2]
        translated_h2 = [h for h in translated_headings if h[0] == 2]
        if len(original_h2) != len(translated_h2):
            issues.append(
                f"Количество H2 не совпадает: "
                f"оригинал {len(original_h2)}, перевод {len(translated_h2)}"
            )

        orig_mermaid = len(re.findall(r'```mermaid', original, re.IGNORECASE))
        trans_mermaid = len(re.findall(r'```mermaid', translated, re.IGNORECASE))
        if orig_mermaid != trans_mermaid:
            issues.append(
                f"Количество mermaid диаграмм не совпадает: "
                f"оригинал {orig_mermaid}, перевод {trans_mermaid}"
            )

        def count_tables(md: str) -> int:
            count = 0
            in_table = False
            lines = md.split('\n')
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('|') and '|' in stripped[1:]:
                    if not in_table:
                        in_table = True
                    if i + 1 < len(lines):
                        nxt = lines[i + 1].strip()
                        if '---' in nxt or '|' in nxt:
                            count += 1
                            in_table = False
                elif in_table and not stripped.startswith('|'):
                    in_table = False
            return count

        orig_tables = count_tables(original)
        trans_tables = count_tables(translated)
        if orig_tables != trans_tables:
            issues.append(
                f"Количество таблиц не совпадает: "
                f"оригинал {orig_tables}, перевод {trans_tables}"
            )

        return len(issues) == 0, issues

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def translate(
        self,
        markdown: str,
        target_language: str,
        seed: ProjectSeed,
        translation_mode: str = "literal",
        progress_callback: Callable[[str], None] | None = None,
        strict: bool = False,
    ) -> str:
        """Переводит README на целевой язык.

        Args:
            markdown: Исходный Markdown на русском
            target_language: Целевой язык (en, kg, uz, tg и др.)
            seed: Входные данные проекта (для контекста)
            translation_mode: "literal" | "combined"
            progress_callback: вызывается с фазой для UI
            strict: при True бросает RuntimeError если перевод не валиден

        Returns:
            Переведённый Markdown
        """
        if target_language == "ru":
            return markdown

        language_names = {
            "en": "английский",
            "kg": "киргизский",
            "uz": "узбекский",
            "tg": "таджикский",
        }
        target_lang_name = language_names.get(target_language, target_language)

        detected_lang = self._detect_source_language(markdown)
        if detected_lang and detected_lang == target_language:
            msg = (
                f"Входной документ уже на целевом языке ({target_lang_name}). "
                f"Подайте оригинальный документ на русском языке."
            )
            print(f"  {msg}", file=sys.stderr, flush=True)
            if strict:
                raise RuntimeError(msg)
            return markdown

        if detected_lang and detected_lang != "ru" and detected_lang != target_language:
            print(
                f"  Внимание: язык документа определён как '{detected_lang}', "
                f"ожидался 'ru'. Перевод может быть некорректным.",
                file=sys.stderr, flush=True,
            )

        protected_md, blocks = protect_blocks(markdown)
        print(
            f"  Защищено {len(blocks)} блоков (mermaid, формулы, код) перед переводом",
            file=sys.stderr, flush=True,
        )

        try:
            print(f"  Перевод README на {target_lang_name}...", file=sys.stderr, flush=True)

            attempts = [
                (translation_mode, self._default_max_chunk_length, "primary"),
                ("literal", 7000, "repair_retry_1"),
                ("literal", 5000, "repair_retry_2"),
            ]

            last_translated = ""
            last_issues: list[str] = []

            for idx, (mode, max_len, phase_name) in enumerate(attempts, 1):
                if progress_callback and phase_name.startswith("repair_retry"):
                    progress_callback(phase_name)
                print(
                    f"  Попытка перевода {idx}/{len(attempts)} "
                    f"(mode={mode}, max_chunk={max_len})",
                    file=sys.stderr, flush=True,
                )
                translated, is_valid, issues = self._run_translation_attempt(
                    protected_md=protected_md,
                    markdown_original=markdown,
                    blocks=blocks,
                    target_lang_name=target_lang_name,
                    target_language_code=target_language,
                    translation_mode=mode,
                    progress_callback=progress_callback,
                    max_length=max_len,
                )
                last_translated = translated
                last_issues = issues

                if is_valid:
                    print(
                        f"  Перевод OK ({len(translated)} символов)",
                        file=sys.stderr, flush=True,
                    )
                    return translated.strip()

                print("  Проблемы с переводом:", file=sys.stderr, flush=True)
                for issue in issues:
                    print(f"    - {issue}", file=sys.stderr, flush=True)

            if strict:
                issues_text = "; ".join(last_issues[:5]) if last_issues else "unknown"
                raise RuntimeError(
                    f"Перевод не прошёл валидацию: {issues_text}"
                )

            print(
                "  Возвращаю лучший доступный результат",
                file=sys.stderr, flush=True,
            )
            return (last_translated or markdown).strip()

        except Exception as e:
            print(f"  Ошибка при переводе: {e}", file=sys.stderr, flush=True)
            if strict:
                raise
            return markdown
