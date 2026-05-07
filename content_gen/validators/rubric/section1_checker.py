"""Проверка Раздела 1: Соответствие шаблону структуры (1.1-1.6)."""

import re

from ...models.criteria_models import CheckMethod, CriteriaItem
from ...utils.logging import safe_print


class Section1Checker:
    """Проверяет соответствие шаблону структуры документа."""

    def __init__(self, regex_patterns: dict):
        """
        Инициализация checker'а.
        
        Args:
            regex_patterns: Словарь с регулярными выражениями для парсинга
        """
        self.rx_h1 = regex_patterns.get("rx_h1")
        self.rx_toc = regex_patterns.get("rx_toc")
        self.rx_chapter1 = regex_patterns.get("rx_chapter1")
        self.rx_chapter2 = regex_patterns.get("rx_chapter2")
        self.rx_chapter3 = regex_patterns.get("rx_chapter3")

    def check(self, md: str) -> list[CriteriaItem]:
        """Проверяет раздел 1: Соответствие шаблону структуры (1.1-1.6)."""
        items = []

        # 1.1: Проверка наличия блока с названием
        m_h1 = self.rx_h1.search(md)
        if m_h1 and md.strip().startswith('#'):
            items.append(CriteriaItem(
                id="1.1",
                title="Проверка наличия блока с названием",
                description="Есть текст с отметкой заголовка первого уровня в первой строке документа: #",
                check_method=CheckMethod.SCRIPT,
                score=1,
                comments=[],
                parent_id="1"
            ))
        else:
            items.append(CriteriaItem(
                id="1.1",
                title="Проверка наличия блока с названием",
                description="Есть текст с отметкой заголовка первого уровня в первой строке документа: #",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет H1 в первой строке документа"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.1: {items[-1].title}", flush=True)

        safe_print("    🔍 Проверка 1.2: Наличие блока с аннотацией...", flush=True)
        # 1.2: Проверка наличия блока с аннотацией
        if m_h1:
            chunk = md[m_h1.end():]
            before_h2 = chunk.split("\n## ", 1)[0].strip()
            # Проверяем, что это текст без заголовков и маркеров списков
            has_headers = bool(re.search(r'^##', before_h2, re.M))
            has_list_markers = bool(re.search(r'^[\s]*[-*+]', before_h2, re.M))

            if before_h2 and not has_headers and not has_list_markers:
                items.append(CriteriaItem(
                    id="1.2",
                    title="Проверка наличия блока с аннотацией",
                    description="Текст сразу после H1 без заголовков и маркеров списков",
                    check_method=CheckMethod.SCRIPT,
                    score=1,
                    comments=[],
                    parent_id="1"
                ))
            else:
                items.append(CriteriaItem(
                    id="1.2",
                    title="Проверка наличия блока с аннотацией",
                    description="Текст сразу после H1 без заголовков и маркеров списков",
                    check_method=CheckMethod.SCRIPT,
                    score=0,
                    comments=["Аннотация не найдена или содержит заголовки/маркеры списков"],
                    parent_id="1"
                ))
        else:
            items.append(CriteriaItem(
                id="1.2",
                title="Проверка наличия блока с аннотацией",
                description="Текст сразу после H1 без заголовков и маркеров списков",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет H1, аннотация не может быть проверена"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.2: {items[-1].title}", flush=True)

        safe_print("    🔍 Проверка 1.3: Наличие блока с оглавлением...", flush=True)
        # 1.3: Проверка наличия блока с оглавлением
        toc_match = self.rx_toc.search(md)
        if toc_match:
            # Извлекаем блок оглавления (до следующего H2)
            toc_start = toc_match.end()
            toc_end = md.find("\n## ", toc_start)
            if toc_end == -1:
                toc_end = len(md)
            toc_block = md[toc_start:toc_end]
            toc_lines = [l.strip() for l in toc_block.split('\n') if l.strip()]

            if len(toc_lines) >= 3:
                items.append(CriteriaItem(
                    id="1.3",
                    title="Проверка наличия блока с оглавлением",
                    description="Есть блок с заголовком второго уровня, содержащий не менее 3 строк",
                    check_method=CheckMethod.SCRIPT,
                    score=1,
                    comments=[],
                    parent_id="1"
                ))
            else:
                items.append(CriteriaItem(
                    id="1.3",
                    title="Проверка наличия блока с оглавлением",
                    description="Есть блок с заголовком второго уровня, содержащий не менее 3 строк",
                    check_method=CheckMethod.SCRIPT,
                    score=0,
                    comments=[f"Оглавление содержит только {len(toc_lines)} строк(и), требуется минимум 3"],
                    parent_id="1"
                ))
        else:
            items.append(CriteriaItem(
                id="1.3",
                title="Проверка наличия блока с оглавлением",
                description="Есть блок с заголовком второго уровня, содержащий не менее 3 строк",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет раздела «Содержание/Оглавление»"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.3: {items[-1].title}", flush=True)

        safe_print("    🔍 Проверка 1.4: Наличие блока с введением и инструкцией...", flush=True)
        # 1.4: Проверка наличия блока с введением и инструкцией
        ch1_match = self.rx_chapter1.search(md)
        if ch1_match:
            ch1_start = ch1_match.end()
            ch1_end = md.find("\n## ", ch1_start)
            if ch1_end == -1:
                ch1_end = len(md)
            ch1_content = md[ch1_start:ch1_end].strip()

            if ch1_content and len(ch1_content) > 50:  # Не пустой блок
                items.append(CriteriaItem(
                    id="1.4",
                    title="Проверка наличия блока с введением и инструкцией",
                    description="Есть не пустой блок ## Глава 1. Введение и инструкция",
                    check_method=CheckMethod.SCRIPT,
                    score=1,
                    comments=[],
                    parent_id="1"
                ))
            else:
                items.append(CriteriaItem(
                    id="1.4",
                    title="Проверка наличия блока с введением и инструкцией",
                    description="Есть не пустой блок ## Глава 1. Введение и инструкция",
                    check_method=CheckMethod.SCRIPT,
                    score=0,
                    comments=["Блок Главы 1 пуст или слишком короткий"],
                    parent_id="1"
                ))
        else:
            items.append(CriteriaItem(
                id="1.4",
                title="Проверка наличия блока с введением и инструкцией",
                description="Есть не пустой блок ## Глава 1. Введение и инструкция",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет блока «Глава 1. Введение и инструкция»"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.4: {items[-1].title}", flush=True)

        safe_print("    🔍 Проверка 1.5: Наличие теоретического блока...", flush=True)
        # 1.5: Проверка наличия теоретического блока
        ch2_match = self.rx_chapter2.search(md)
        if ch2_match:
            ch2_start = ch2_match.end()
            ch2_end = md.find("\n## ", ch2_start)
            if ch2_end == -1:
                ch2_end = len(md)
            ch2_content = md[ch2_start:ch2_end].strip()

            if ch2_content and len(ch2_content) > 50:
                items.append(CriteriaItem(
                    id="1.5",
                    title="Проверка наличия теоретического блока",
                    description="Есть не пустой блок ## Глава 2. Теоретический блок",
                    check_method=CheckMethod.SCRIPT,
                    score=1,
                    comments=[],
                    parent_id="1"
                ))
            else:
                items.append(CriteriaItem(
                    id="1.5",
                    title="Проверка наличия теоретического блока",
                    description="Есть не пустой блок ## Глава 2. Теоретический блок",
                    check_method=CheckMethod.SCRIPT,
                    score=0,
                    comments=["Блок Главы 2 пуст или слишком короткий"],
                    parent_id="1"
                ))
        else:
            items.append(CriteriaItem(
                id="1.5",
                title="Проверка наличия теоретического блока",
                description="Есть не пустой блок ## Глава 2. Теоретический блок",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет блока «Глава 2. Теоретический блок»"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.5: {items[-1].title}", flush=True)

        safe_print("    🔍 Проверка 1.6: Наличие практического блока...", flush=True)
        # 1.6: Проверка наличия практического блока
        ch3_match = self.rx_chapter3.search(md)
        if ch3_match:
            ch3_start = ch3_match.end()
            ch3_end = md.find("\n## ", ch3_start)
            if ch3_end == -1:
                ch3_end = len(md)
            ch3_content = md[ch3_start:ch3_end].strip()

            if ch3_content and len(ch3_content) > 50:
                items.append(CriteriaItem(
                    id="1.6",
                    title="Проверка наличия практического блока",
                    description="Есть не пустой блок ## Глава 3. Практический блок",
                    check_method=CheckMethod.SCRIPT,
                    score=1,
                    comments=[],
                    parent_id="1"
                ))
            else:
                items.append(CriteriaItem(
                    id="1.6",
                    title="Проверка наличия практического блока",
                    description="Есть не пустой блок ## Глава 3. Практический блок",
                    check_method=CheckMethod.SCRIPT,
                    score=0,
                    comments=["Блок Главы 3 пуст или слишком короткий"],
                    parent_id="1"
                ))
        else:
            items.append(CriteriaItem(
                id="1.6",
                title="Проверка наличия практического блока",
                description="Есть не пустой блок ## Глава 3. Практический блок",
                check_method=CheckMethod.SCRIPT,
                score=0,
                comments=["Нет блока «Глава 3. Практический блок»"],
                parent_id="1"
            ))

        safe_print(f"      {'✅' if items[-1].score == 1 else '❌'} 1.6: {items[-1].title}", flush=True)

        return items

