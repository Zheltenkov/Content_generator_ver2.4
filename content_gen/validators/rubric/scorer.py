"""Основной класс RubricScorer для оценки проектов по критериям."""

import concurrent.futures
import re

from ...llm.client import LLMClient
from ...models.criteria_models import CriteriaItem, CriteriaReport
from ...embeddings import create_embedding_function
from ...utils.logging import safe_print
from ...utils.validation_cache import get_cache
from .section1_checker import Section1Checker
from .section2_checker import Section2Checker
from .section3_checker import Section3Checker
from .section4_checker import Section4Checker
from .similarity import SimilarityCalculator


class RubricScorer:
    """Оценивает проект по всем критериям из "Критерии проверки.txt"."""

    def __init__(self, language: str = "ru", llm_client: LLMClient | None = None):
        """
        Инициализация RubricScorer.
        
        Args:
            language: Язык текстов
            llm_client: LLM клиент для AI-проверок
        """
        self.lang = language
        self.llm = llm_client

        # Инициализируем embedding function для SBERT (если доступен)
        try:
            self.embedding_function = create_embedding_function()
        except Exception as e:
            safe_print(f"[RUBRIC] SBERT embeddings недоступны: {e}", flush=True)
            self.embedding_function = None

        # Регулярные выражения для парсинга
        self.rx_h1 = re.compile(r"^#\s+(.+)$", re.M)
        self.rx_h2 = re.compile(r"^##\s+(.+)$", re.M)
        self.rx_h3 = re.compile(r"^###\s+(.+)$", re.M)
        self.rx_toc = re.compile(r"^##\s+(Содержание|Оглавление|Content|Мазмун)\s*$", re.M)
        self.rx_chapter1 = re.compile(r"^##\s+Глава\s+1[^\n]*\n", re.M)
        self.rx_chapter2 = re.compile(r"^##\s+Глава\s+2[^\n]*\n", re.M)
        self.rx_chapter3 = re.compile(r"^##\s+Глава\s+3[^\n]*\n", re.M)
        self.rx_theory_part = re.compile(r"^###\s+(?:2\.\d+|Часть\s+\d+)\.", re.M)
        self.rx_task = re.compile(r"^###\s+(?:Задание|Задача)\s+\d+\.", re.M)

        # Директивы и маркетинговые триггеры
        from ...config.banned_phrases import BANNED_BY_LANG
        self.rx_directives = BANNED_BY_LANG.get(language, BANNED_BY_LANG.get("ru", []))
        self.rx_marketing = [
            r"только сейчас",
            r"последние места",
            r"успей",
            r"не упусти",
            r"ограниченное предложение",
        ]

        # Подготавливаем regex_patterns для чекеров
        regex_patterns = {
            "rx_h1": self.rx_h1,
            "rx_h2": self.rx_h2,
            "rx_h3": self.rx_h3,
            "rx_toc": self.rx_toc,
            "rx_chapter1": self.rx_chapter1,
            "rx_chapter2": self.rx_chapter2,
            "rx_chapter3": self.rx_chapter3,
            "rx_theory_part": self.rx_theory_part,
            "rx_task": self.rx_task,
            "rx_directives": self.rx_directives,
            "rx_bad_goals": [],  # Будет использоваться из BAD_GOAL_PATTERNS внутри чекеров
            "rx_marketing": self.rx_marketing
        }

        # Инициализируем чекеры
        self.section1_checker = Section1Checker(regex_patterns=regex_patterns)
        self.section2_checker = Section2Checker(
            llm_client=self.llm,
            embedding_function=self.embedding_function,
            language=self.lang,
            regex_patterns=regex_patterns
        )

        # SimilarityCalculator для Section3Checker
        similarity_calculator = SimilarityCalculator(
            embedding_function=self.embedding_function,
            language=self.lang
        )
        self.section3_checker = Section3Checker(
            similarity_calculator=similarity_calculator,
            llm_client=self.llm
        )

        self.section4_checker = Section4Checker(
            llm_client=self.llm,
            regex_patterns=regex_patterns
        )

    def run(self, input_data: dict[str, object]) -> dict[str, CriteriaReport]:
        """Совместимый адаптер для старого graph/run-контракта."""
        result = self.score(
            md=input_data.get("md", ""),
            learning_outcomes=input_data.get("learning_outcomes"),
            use_cache=bool(input_data.get("use_cache", True)),
        )
        return {"result": result}

    def score(self, md: str, learning_outcomes: list[str] | None = None, use_cache: bool = True) -> CriteriaReport:
        """
        Оценивает проект по всем критериям.
        
        Оптимизированная версия с параллельным выполнением независимых разделов и кэшированием.
        
        Args:
            md: Markdown документ
            learning_outcomes: Список образовательных результатов (ЗУНов) для проверки соответствия
            use_cache: Использовать кэш результатов (по умолчанию True)
        
        Returns:
            CriteriaReport с оценками по всем критериям
        """
        # Проверяем кэш
        if use_cache:
            cache = get_cache()
            cached_report = cache.get(md, context={"learning_outcomes": learning_outcomes or []})
            if cached_report is not None:
                safe_print("  ✅ Результат валидации найден в кэше", flush=True)
                return cached_report

        items: list[CriteriaItem] = []

        safe_print("  📋 Начало проверки критериев (параллельный режим)...", flush=True)

        # Параллельное выполнение независимых разделов
        # Разделы 1, 2, 3, 4 независимы и могут выполняться параллельно
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            # Запускаем все проверки параллельно
            future_section1 = executor.submit(self.section1_checker.check, md)
            future_section2 = executor.submit(self.section2_checker.check, md, learning_outcomes)
            future_section3 = executor.submit(self.section3_checker.check, md)
            future_section4 = executor.submit(self.section4_checker.check, md)

            # Ждем результаты и обрабатываем их по мере готовности
            safe_print("  📋 Раздел 1: Соответствие шаблону структуры (1.1-1.6)...", flush=True)
            section1_items = future_section1.result()
            items.extend(section1_items)
            section1_score = sum(item.score for item in section1_items)
            safe_print(f"    ✅ Раздел 1: {section1_score}/{len(section1_items)} критериев пройдено", flush=True)

            safe_print("  📋 Раздел 2: Соответствие требованиям (2.1-2.5)...", flush=True)
            section2_items = future_section2.result()
            items.extend(section2_items)
            section2_score = sum(item.score for item in section2_items)
            safe_print(f"    ✅ Раздел 2: {section2_score}/{len(section2_items)} критериев пройдено", flush=True)

            safe_print("  📋 Раздел 3: Единый сторителлинг (3.1-3.2)...", flush=True)
            section3_items = future_section3.result()
            items.extend(section3_items)
            section3_score = sum(item.score for item in section3_items)
            safe_print(f"    ✅ Раздел 3: {section3_score}/{len(section3_items)} критериев пройдено", flush=True)

            safe_print("  📋 Раздел 4: Tone of voice и редактура (4.1-4.3)...", flush=True)
            section4_items = future_section4.result()
            items.extend(section4_items)
            section4_score = sum(item.score for item in section4_items)
            safe_print(f"    ✅ Раздел 4: {section4_score}/{len(section4_items)} критериев пройдено", flush=True)

        # Подсчет итогов
        total = sum(item.score for item in items)
        max_score = len(items)

        # Проверяем, что все 39 критериев проверены
        if max_score != 39:
            safe_print(f"  ⚠️ Предупреждение: ожидалось 39 критериев, получено {max_score}", flush=True)

        # Сводка по разделам
        summary = {}
        for item in items:
            section = item.id.split('.')[0]
            if section not in summary:
                summary[section] = 0
            summary[section] += item.score

        safe_print(f"  ✅ Проверка критериев завершена: {total}/{max_score} баллов ({total/max_score*100:.1f}%)", flush=True)

        report = CriteriaReport(
            items=items,
            total=total,
            max_score=max_score,
            summary=summary
        )

        # Сохраняем в кэш
        if use_cache:
            cache = get_cache()
            cache.set(md, report, context={"learning_outcomes": learning_outcomes or []})

        return report
