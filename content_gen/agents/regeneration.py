"""
content_gen/agents/regeneration.py

Агент для перегенерации README на основе комментариев.

Перегенерирует части контента на основе комментариев пользователя.
Используется в Streamlit UI для инкрементальных изменений.
"""

import re
from dataclasses import dataclass

from ..didactics.composer import compose_didactics_context
from ..llm.client import LLMClient
from ..utils.patch_format import (
    apply_patches,
    parse_patches_from_response,
)
from ..utils.protected_blocks import fix_common_latex_issues_in_md, protect_blocks, restore_blocks


@dataclass
class RegenerationResult:
    """Результат перегенерации README."""
    changes: list[str]  # Список изменений
    regenerated_md: str  # Перегенерированный README
    original_md: str  # Оригинальный README


SYSTEM_BASE = """Ты — эксперт по редактированию учебных проектов. Твоя задача — МИНИМАЛЬНО и точечно изменять README на основе комментариев, сохраняя структуру документа и все метрики.

КРИТИЧЕСКИ ВАЖНО - МИНИМАЛЬНЫЕ ИЗМЕНЕНИЯ:
1. Изменяй ТОЛЬКО то, что явно указано в комментариях - ничего лишнего
2. Сохраняй ВСЮ структуру Markdown (заголовки, списки, форматирование, таблицы, диаграммы, формулы)
3. НЕ переписывай разделы целиком - изменяй только конкретные фразы или предложения
4. Сохраняй стиль, тон и длину текста (не сокращай и не расширяй без необходимости)
5. НЕ меняй структуру разделов, заголовки, оглавление, нумерацию
6. НЕ трогай разделы, которые не упомянуты в комментариях
7. Сохраняй все технические детали, формулы, таблицы, диаграммы, код
8. Если комментарий касается конкретного раздела — изменяй ТОЛЬКО этот раздел, остальное не трогай
9. ОБЯЗАТЕЛЬНО используй ёлочки « » для кавычек вместо прямых кавычек " "
10. Цель — исправить указанные проблемы, НЕ улучшать документ в целом

УДАЛЕНИЕ vs ПЕРЕФОРМУЛИРОВКА (различай строго):
- «Удалить» / «убрать» / «исключить» указанный блок, раздел или абзац = УДАЛИТЬ этот фрагмент целиком. Не заменяй его новым текстом, не пересказывай другими словами. Результат: фрагмента нет (склей контекст или оставь пустое место по смыслу).
- «Переформулировать» / «переписать» / «изменить формулировку» = заменить текст, сохраняя смысл и объём. Результат: тот же блок на месте, но с новой формулировкой.
- Если пользователь просит «убрать кусок про X» — в патче new_text для этого куска должен быть пустой или только склеенный контекст, без нового описания «X».

ОСОБЫЕ ПРАВИЛА ДЛЯ ЗАЩИЩЁННЫХ БЛОКОВ:

- В тексте README некоторые формулы, диаграммы и блоки кода заменены на маркеры:
  - HTML-комментарий: <!-- PROTECTED_BLOCK id=N type=... preview="..." -->
  - Строка-маркер: [[[BLOCK_N]]]
- Содержимое этих блоков хранится отдельно, поэтому:
  - НЕЛЬЗЯ изменять текст маркера [[[BLOCK_N]]] (его формат должен оставаться идентичным).
  - НЕЛЬЗЯ менять номер id в маркере.
  - НЕЛЬЗЯ придумывать новые маркеры [[[BLOCK_*]]] самостоятельно.
- Если комментарий просит ИЗМЕНИТЬ текст вокруг формулы/диаграммы — меняй только обычный текст, маркеры и комментарии PROTECTED_BLOCK копируй без изменений.
- Если комментарий ПРОСИТ УДАЛИТЬ конкретную формулу или диаграмму:
  - удали строку с соответствующим маркером [[[BLOCK_N]]],
  - по возможности удали и соседний комментарий <!-- PROTECTED_BLOCK id=N ... -->.
  Это единственный допустимый способ удалить формулу/диаграмму.
- Если комментариев про удаление блока нет, ВСЕ маркеры и комментарии PROTECTED_BLOCK должны остаться.

Язык вывода: {language}."""

USER_TMPL = """Ниже представлен README учебного проекта и комментарии по его изменению.

Твоя задача:
1. Проанализировать комментарии
2. Составить набор МИНИМАЛЬНЫХ правок (патчей)
3. Описать эти правки ТОЛЬКО в виде JSON-патчей.

Исходный README (с маркерами защищённых блоков):

{original_md}

Комментарии по изменению:
{comments}

КРИТИЧЕСКИ ВАЖНО:
- Разрешено МЕНЯТЬ только обычный текст. Маркеры [[[BLOCK_N]]] и HTML-комментарии PROTECTED_BLOCK трогать нельзя.
- НЕЛЬЗЯ возвращать весь README целиком.
- НЕЛЬЗЯ использовать Markdown, ```json и любой другой текст вокруг JSON.
- Ответ должен быть ЧИСТЫМ JSON-объектом.
- Различай «удалить» и «переформулировать»: при просьбе УДАЛИТЬ блок/раздел — в патче old_text укажи удаляемый фрагмент, в new_text — пустую строку или соседний контекст (без нового текста на эту тему). При просьбе переформулировать — new_text содержит новую формулировку.

Формат ответа (ОДИНСТВЕННЫЙ допустимый):

{{
  "changes": [
    {{
      "location_hint": "краткое описание места изменения (для человека)",
      "old_text": "ТОЧНЫЙ фрагмент из исходного README (без маркеров [[[BLOCK_N]]])",
      "new_text": "новый текст вместо old_text"
    }}
  ]
}}

Если по комментариям не нужно менять документ — верни:

{{ "changes": [] }}
"""

REWRITE_USER_TMPL = """Ниже представлен README учебного проекта и комментарии по его изменению.

Твоя задача:
1. Внести только те изменения, которые явно запрошены в комментариях.
2. Сохранить структуру README, заголовки, оглавление, нумерацию глав и общий стиль.
3. Не менять разделы, которых комментарии не касаются.
4. Вернуть ПОЛНЫЙ обновлённый README целиком, без пояснений и без JSON.

Исходный README (с маркерами защищённых блоков):

{original_md}

Комментарии по изменению:
{comments}

КРИТИЧЕСКИ ВАЖНО:
- Маркеры [[[BLOCK_N]]] и комментарии PROTECTED_BLOCK нельзя менять, переименовывать или удалять, если об этом прямо не попросили.
- Если комментарий просит убрать фрагмент, удали этот фрагмент, а не переписывай его заново.
- Если комментарий просит улучшить формулировку, измени только проблемный фрагмент.
- Не добавляй новых разделов и не перестраивай документ целиком.

Верни только обновлённый README в Markdown.
"""


class RegenerationAgent:
    """Агент для перегенерации README на основе комментариев."""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        try:
            self.didactics_context, self.didactics_trace = compose_didactics_context("regeneration")
        except Exception:
            self.didactics_context, self.didactics_trace = "", {}

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Убирает случайные markdown fences вокруг полного README."""
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _detect_target_scope(comments: str) -> str:
        """Пытается понять, какой раздел README пользователь хочет переписать."""
        text = (comments or "").lower()
        task_match = re.search(r"(?:задач[ауеиы]?|task)\s*(\d+)", text)
        if task_match:
            return f"Задача {task_match.group(1)}"
        if "аннотац" in text:
            return "Аннотация"
        if "введен" in text:
            return "Введение"
        if "инструкц" in text:
            return "Инструкция"
        if "глава 2" in text or "теори" in text:
            return "Глава 2. Теоретический блок"
        if "глава 3" in text or "практик" in text:
            return "Глава 3. Практический блок"
        return ""

    @staticmethod
    def _build_targeted_rewrite_addendum(scope: str) -> str:
        """Добавляет в fallback-режим явный фокус на один раздел."""
        if not scope:
            return ""
        return (
            "\n\nДОПОЛНИТЕЛЬНЫЙ ФОКУС:\n"
            f"- Основной объект правки: {scope}.\n"
            f"- Если можно, переписывай только {scope}, а остальные части README оставь без изменений.\n"
            "- Разрешено слегка подправить соседние фразы только для связности после правки целевого блока.\n"
        )

    def regenerate(self, original_md: str, comments: str, language: str = "ru") -> RegenerationResult:
        """
        Перегенерирует README на основе комментариев.

        Args:
            original_md: Исходный README в формате Markdown
            comments: Комментарии по изменению
            language: Язык вывода

        Returns:
            RegenerationResult с списком изменений и перегенерированным README
        """
        # Защищаем блоки (формулы, диаграммы, код) перед отправкой в LLM
        protected_md, blocks = protect_blocks(original_md)

        system_prompt = SYSTEM_BASE.format(language=language)
        if self.didactics_context:
            system_prompt = f"{system_prompt}\n\n=== DIDACTICS CONTEXT ===\n{self.didactics_context}"
        user = USER_TMPL.format(original_md=protected_md, comments=comments)

        response = self.llm.complete(
            system=system_prompt,
            user=user,
            max_completion_tokens=16000,  # Увеличено для полного README
        )

        # Пытаемся сначала распарсить патчи (patch-формат)
        patches = parse_patches_from_response(response)
        changes: list[str] = []
        regenerated_md: str

        if patches:
            patch_result = apply_patches(protected_md, patches)

            if patch_result.success or patch_result.applied_patches:
                regenerated_md = patch_result.result_md
                changes = [
                    f"{p.location_hint}: {p.old_text[:50]}... → {p.new_text[:50]}..."
                    for p in patch_result.applied_patches
                ]

                if patch_result.failed_patches:
                    changes.append(
                        f"⚠️ {len(patch_result.failed_patches)} патч(ей) не удалось применить: "
                        + "; ".join(patch_result.errors[:3])
                    )

                # Восстанавливаем защищённые блоки + чиним LaTeX
                regenerated_md = restore_blocks(regenerated_md, blocks)
                regenerated_md = fix_common_latex_issues_in_md(regenerated_md)

                if regenerated_md.strip() == original_md.strip():
                    changes.append("⚠️ Патчи формально применились, но README не изменился. Запускаю fallback-редакцию.")
                else:
                    return RegenerationResult(
                        changes=changes,
                        regenerated_md=regenerated_md,
                        original_md=original_md,
                    )

        # Fallback: если JSON-патчи не удалось применить или они не дали изменения,
        # просим модель вернуть полный README с минимальными правками.
        target_scope = self._detect_target_scope(comments)
        rewrite_user = REWRITE_USER_TMPL.format(original_md=protected_md, comments=comments)
        rewrite_user += self._build_targeted_rewrite_addendum(target_scope)
        rewritten = self.llm.complete(
            system=system_prompt,
            user=rewrite_user,
            max_completion_tokens=16000,
        )
        rewritten = self._strip_markdown_fences(rewritten)
        if rewritten:
            regenerated_md = restore_blocks(rewritten, blocks)
            regenerated_md = fix_common_latex_issues_in_md(regenerated_md)
            if regenerated_md.strip() != original_md.strip():
                return RegenerationResult(
                    changes=changes + [
                        (
                            f"Перегенерация применена через targeted fallback-редакцию: {target_scope}"
                            if target_scope else
                            "Перегенерация применена через fallback-редакцию полного README"
                        )
                    ],
                    regenerated_md=regenerated_md,
                    original_md=original_md,
                )

        # Если до сюда дошли — патчи не распознаны или не применились.
        # Ничего не меняем, просто возвращаем оригинал.
        return RegenerationResult(
            changes=["Перегенерация не применена: не удалось распарсить или применить патчи"],
            regenerated_md=original_md,
            original_md=original_md,
        )

    def _clean_duplicate_headers(self, md: str) -> str:
        """
        Очищает дублирующиеся заголовки глав.
        
        Удаляет заголовки уровня H3 (###), которые дублируют заголовки уровня H2 (##) для глав.
        Например: "## Глава 2. Теория" и "### Глава 2. Теория" -> оставляет только "## Глава 2. Теория"
        
        Args:
            md: Markdown текст
            
        Returns:
            Очищенный Markdown текст
        """
        import re

        # Паттерны для глав (русский, английский, киргизский)
        chapter_patterns = [
            (r'^##\s+(Глава\s+\d+\.\s+[^\n]+)$', r'^###\s+(Глава\s+\d+\.\s+[^\n]+)$'),  # Глава 2. Теория
            (r'^##\s+(Chapter\s+\d+\.\s+[^\n]+)$', r'^###\s+(Chapter\s+\d+\.\s+[^\n]+)$'),  # Chapter 2. Theory
            (r'^##\s+(\d+-Бөлүм\.\s+[^\n]+)$', r'^###\s+(\d+-Бөлүм\.\s+[^\n]+)$'),  # 2-Бөлүм. Теория
        ]

        lines = md.split('\n')
        cleaned_lines = []
        i = 0

        # Сначала собираем все H2 заголовки глав
        h2_chapters = {}
        for idx, line in enumerate(lines):
            if line.startswith('## ') and not line.startswith('###'):
                for h2_pattern, h3_pattern in chapter_patterns:
                    match = re.match(h2_pattern, line, re.IGNORECASE)
                    if match:
                        chapter_text = match.group(1).strip()
                        h2_chapters[chapter_text.lower()] = idx
                        break

        # Теперь проходим по строкам и удаляем дублирующиеся H3
        while i < len(lines):
            line = lines[i]
            is_duplicate = False

            # Проверяем, является ли строка заголовком H3
            if line.startswith('### '):
                header_text = line[4:].strip()  # Убираем "### "

                # Проверяем, есть ли такой же заголовок H2
                if header_text.lower() in h2_chapters:
                    is_duplicate = True
                else:
                    # Проверяем, соответствует ли заголовок паттерну главы
                    for h2_pattern, h3_pattern in chapter_patterns:
                        match = re.match(h3_pattern, line, re.IGNORECASE)
                        if match:
                            chapter_text = match.group(1).strip()
                            # Проверяем, есть ли такой же H2 заголовок в документе
                            if chapter_text.lower() in h2_chapters:
                                is_duplicate = True
                            break

            if not is_duplicate:
                cleaned_lines.append(line)

            i += 1

        return '\n'.join(cleaned_lines)

    def _clean_empty_html_blocks(self, md: str) -> str:
        """
        Очищает ТОЛЬКО пустые HTML-блоки, которые могут остаться после перегенерации.
        
        Удаляет пустые div'ы, которые были созданы для визуализаций, но остались без содержимого.
        ВАЖНО: Удаляет ТОЛЬКО блоки, которые содержат ТОЛЬКО пробелы/переносы строк между тегами.
        НЕ трогает блоки с полезным контентом (текст, mermaid блоки, таблицы и т.д.).
        
        Args:
            md: Markdown текст
            
        Returns:
            Очищенный Markdown текст
        """
        import re

        cleaned_md = md

        # КРИТИЧЕСКИ ВАЖНО: Удаляем ТОЛЬКО блоки, которые:
        # 1. Содержат ТОЛЬКО пробелы/переносы строк между тегами (не более 50 символов пробелов)
        # 2. НЕ содержат текста, mermaid блоков (```mermaid), таблиц (|), формул ($$), ссылок ([)
        # 3. НЕ содержат других HTML-тегов с контентом

        # Функция для проверки, что блок действительно пустой
        def is_empty_block(match: re.Match) -> bool:
            """Проверяет, что блок действительно пустой (только пробелы/переносы)."""
            content = match.group(0)
            # Удаляем HTML-теги
            text_only = re.sub(r'<[^>]+>', '', content)
            # Проверяем, что остались только пробелы/переносы
            if text_only.strip():
                return False
            # Проверяем, что нет полезного контента (mermaid, таблицы, формулы)
            if re.search(r'```mermaid|```|\[.*?\]|`.*?`|\$\$|\||<[^>]+>[^<]+</[^>]+>', content, re.IGNORECASE):
                return False
            # Проверяем длину пробелов (не более 50 символов)
            if len(text_only) > 50:
                return False
            return True

        # Паттерн 1: Пустые вложенные div'ы с display:flex и max-width
        # Ищем структуру и проверяем, что она пустая
        pattern1 = r'<div\s+style=["\'][^"\']*display:flex[^"\']*["\'][^>]*>\s*<div\s+style=["\'][^"\']*max-width:100%[^"\']*["\'][^>]*>\s*</div>\s*</div>'
        matches = list(re.finditer(pattern1, cleaned_md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL))
        # Удаляем в обратном порядке, чтобы не сбить индексы
        for match in reversed(matches):
            if is_empty_block(match):
                cleaned_md = cleaned_md[:match.start()] + cleaned_md[match.end():]

        # Паттерн 2: Пустые div'ы с justify-content:center (вложенные)
        pattern2 = r'<div\s+style=["\'][^"\']*justify-content:center[^"\']*["\'][^>]*>\s*<div[^>]*>\s*</div>\s*</div>'
        matches = list(re.finditer(pattern2, cleaned_md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL))
        for match in reversed(matches):
            if is_empty_block(match):
                cleaned_md = cleaned_md[:match.start()] + cleaned_md[match.end():]

        # Паттерн 3: Пустые div'ы с max-width:100% (одиночные)
        pattern3 = r'<div\s+style=["\'][^"\']*max-width:100%[^"\']*["\'][^>]*>\s*</div>'
        matches = list(re.finditer(pattern3, cleaned_md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL))
        for match in reversed(matches):
            if is_empty_block(match):
                cleaned_md = cleaned_md[:match.start()] + cleaned_md[match.end():]

        # Паттерн 4: Вложенные пустые div'ы (общий случай, но только если действительно пусто)
        pattern4 = r'<div[^>]*>\s*<div[^>]*>\s*</div>\s*</div>'
        # Применяем осторожно - только если действительно пусто
        for _ in range(2):  # Максимум 2 уровня вложенности
            matches = list(re.finditer(pattern4, cleaned_md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL))
            for match in reversed(matches):
                if is_empty_block(match):
                    cleaned_md = cleaned_md[:match.start()] + cleaned_md[match.end():]

        # Паттерн 5: Пустые div'ы с margin:20px 0
        pattern5 = r'<div\s+style=["\'][^"\']*margin:20px\s+0[^"\']*["\'][^>]*>\s*<div[^>]*>\s*</div>\s*</div>'
        matches = list(re.finditer(pattern5, cleaned_md, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL))
        for match in reversed(matches):
            if is_empty_block(match):
                cleaned_md = cleaned_md[:match.start()] + cleaned_md[match.end():]

        # Удаляем множественные пустые строки (более 2 подряд)
        cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md)

        return cleaned_md

    def _fix_code_blocks(self, md: str) -> str:
        """
        Исправляет незакрытые блоки кода в Markdown.
        
        Проверяет, что все блоки кода (```) правильно закрыты.
        Если блок не закрыт, закрывает его перед следующим заголовком или в конце документа.
        Также исправляет случаи, когда весь текст попадает в блок кода.
        
        Args:
            md: Markdown текст
            
        Returns:
            Исправленный Markdown текст
        """
        # Предварительная проверка: если документ начинается с блока кода и не закрыт,
        # это может быть ошибка генерации
        if md.strip().startswith('```'):
            # Подсчитываем количество открывающих и закрывающих блоков
            open_blocks = md.count('```')
            # Если нечетное количество, значит есть незакрытый блок
            if open_blocks % 2 != 0:
                # Ищем, где должен быть закрывающий блок
                # Если блок кода занимает более 30% документа, вероятно, это ошибка
                first_code_end = md.find('```', 3)  # Ищем следующий ``` после первого
                if first_code_end == -1 or first_code_end > len(md) * 0.3:
                    # Блок кода слишком длинный или не закрыт - закрываем его перед первым заголовком
                    # Ищем первый заголовок после начала блока кода
                    header_match = re.search(r'^#+\s+', md[3:], re.MULTILINE)
                    if header_match:
                        header_pos = header_match.start() + 3
                        # Вставляем закрывающий блок перед заголовком
                        md = md[:header_pos] + '\n```\n' + md[header_pos:]

        lines = md.split('\n')
        fixed_lines = []
        in_code_block = False
        code_block_start = None
        code_block_language = None
        code_block_lines = 0

        for i, line in enumerate(lines):
            # Проверяем начало блока кода
            if line.strip().startswith('```'):
                # Если мы уже в блоке кода, это может быть закрывающий блок
                if in_code_block:
                    # Проверяем, что это действительно закрывающий блок
                    closing_marker = line.strip()
                    if closing_marker == '```' or closing_marker == f'```{code_block_language}':
                        # Правильно закрытый блок
                        in_code_block = False
                        code_block_start = None
                        code_block_language = None
                        code_block_lines = 0
                        fixed_lines.append(line)
                        continue
                    else:
                        # Это новый блок кода внутри старого - ошибка, закрываем старый
                        fixed_lines.append('```')
                        in_code_block = False
                        code_block_start = None
                        code_block_language = None
                        code_block_lines = 0

                # Начинаем новый блок кода
                in_code_block = True
                code_block_start = i
                code_block_lines = 0
                # Извлекаем язык (если указан)
                code_block_language = line.strip()[3:].strip() or None
                fixed_lines.append(line)
                continue

            # Если мы в блоке кода
            if in_code_block:
                code_block_lines += 1
                fixed_lines.append(line)

                # Проверяем, не слишком ли длинный блок кода (возможно, весь текст попал в блок)
                # Если блок кода длиннее 500 строк и мы не видим закрывающего маркера,
                # вероятно, это ошибка - закрываем блок перед следующим заголовком
                if code_block_lines > 500:
                    # Ищем следующий заголовок (H1, H2, H3)
                    next_header_idx = None
                    for j in range(i + 1, min(i + 50, len(lines))):  # Проверяем следующие 50 строк
                        if lines[j].strip().startswith('#'):
                            next_header_idx = j
                            break

                    if next_header_idx:
                        # Закрываем блок кода перед заголовком
                        fixed_lines.append('```')
                        in_code_block = False
                        code_block_start = None
                        code_block_language = None
                        code_block_lines = 0
                        continue

                continue

            # Обычная строка вне блока кода
            fixed_lines.append(line)

        # Если остался незакрытый блок кода, закрываем его
        if in_code_block:
            # Если блок кода очень длинный (более 100 строк), вероятно, это ошибка
            # Закрываем его
            if code_block_lines > 100:
                fixed_lines.append('```')
            else:
                # Короткий незакрытый блок - возможно, просто забыли закрыть
                fixed_lines.append('```')

        return '\n'.join(fixed_lines)
