"""
content_gen/agents/practice.py

Агент генерации практических задач.

Генерирует Главу 3 (Практика) с задачами, содержащими:
- Цель задачи
- Подход (шаги выполнения)
- Входные данные
- Локация результата
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..artifact_chain import ArtifactChainPlan, GenericArtifactChainPlanner, is_generic_repo_path_template
from ..config.active_goals import has_active_goal_verb
from ..config.loader import get_agent_config
from ..config.thresholds import CODE_EXAMPLE_CONFIG, THRESHOLDS
from ..didactics.composer import compose_didactics_context
from ..domain_contracts import render_narrative_contract_section
from ..models.schemas import PracticeTask, ProjectSeed
from ..practice_contract import normalize_task_input_for_learning_activity
from ..project_planning import render_practice_plan_contract_section
from .base.agent import BaseAgent
from .base.llm_client import LLMClientProtocol
from .style_guard import StyleGuardAgent

if TYPE_CHECKING:
    from .code_example import CodeExampleAgent

SYSTEM = ""

USER_TMPL = ""


BONUS_USER_TMPL = ""


_RX_ARTIFACT_PATH = re.compile(r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]+)")


def _extract_inline_from_public(text: str, label: str) -> str:
    """Extract `Label: ...` fragments from canonical public practice blocks."""
    if not text:
        return ""
    match = re.search(
        rf"(?:^|\n)\s*{re.escape(label)}:\s*(.+?)(?=\n\s*(?:Ситуация|Исходные данные|Цель|Подход):|\Z)",
        text,
        flags=re.S | re.I,
    )
    return match.group(1).strip() if match else ""


@dataclass
class PracticeResult:
    """Результат генерации практических задач."""

    tasks: list[PracticeTask]
    bonus_tasks: list[PracticeTask] = field(default_factory=list)


class PracticeAgent(BaseAgent):
    """Генерирует практические задачи проекта."""

    CONFIG_NAME = "practice"

    def __init__(self, llm: LLMClientProtocol):
        super().__init__(llm)
        self.logger = logging.getLogger("content_gen.agents.practice")
        self.style = StyleGuardAgent()
        self.code_agent: CodeExampleAgent | None = None
        if CODE_EXAMPLE_CONFIG["enable_code_tasks_in_practice"]:
            try:
                from .code_example import CodeExampleAgent
                self.code_agent = CodeExampleAgent(llm)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("⚠️ CodeExampleAgent недоступен, продолжаю без code-подзадач: %s", exc)
        # Поддерживаем оба формата: "Задание 1. название" и "Задача 1. название" (для обратной совместимости)
        self.rx_task = re.compile(r"^###\s+(?:Задание|Задача)\s+(\d+)\.\s*(.+?)\s*$", re.M)
        self.config = get_agent_config(self.CONFIG_NAME)
        self.llm_kwargs = self.config.llm.to_kwargs() if self.config.llm else {}
        try:
            self.didactics_context, self.didactics_trace = compose_didactics_context(self.CONFIG_NAME)
        except Exception:
            self.didactics_context, self.didactics_trace = "", {}
        self.artifact_chain_planner = GenericArtifactChainPlanner()
        self.last_artifact_chain_plan: ArtifactChainPlan | None = None

    @staticmethod
    def _safe_artifact_root(seed: ProjectSeed) -> str:
        """Build a stable project folder name for generated artifact locations."""
        raw = (seed.platform_name or seed.title_seed or "project").strip()
        root = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
        return root[:80] or "project"

    def _artifact_location_for_task(
        self,
        seed: ProjectSeed,
        task_idx: int,
        *,
        bonus: bool = False,
    ) -> str:
        """Return a canonical artifact location without assuming a Git repository."""
        task_num = task_idx + 1
        if not bonus and seed.repo_path_template and not is_generic_repo_path_template(seed.repo_path_template):
            try:
                return seed.repo_path_template.format(num=task_num).replace("\\", "/")
            except (KeyError, ValueError):
                pass
        root = self._safe_artifact_root(seed)
        folder = f"bonus-{task_num:02d}" if bonus else f"task-{task_num:02d}"
        return f"{root}/part-03/{folder}/README.md"

    def _is_programming_topic(self, seed: ProjectSeed) -> bool:
        """
        Проверяет, касается ли тема проекта программирования или разработки.
        
        Args:
            seed: Входные данные проекта
        
        Returns:
            True, если тема касается программирования
        """
        if not CODE_EXAMPLE_CONFIG["enable_code_tasks_in_practice"]:
            return False

        # Ключевые слова, указывающие на программирование (ЖЕСТКАЯ ПРОВЕРКА)
        # Код нужен ТОЛЬКО если тема явно касается разработки ПО или изучения языков программирования
        programming_keywords = [
            # Явные указания на программирование
            "программирование", "разработка программного обеспечения", "разработка по", "разработка приложений",
            "изучение языка программирования", "изучение python", "изучение javascript", "изучение java",
            "написание кода", "написание программы", "создание программы", "разработка программы",
            # Языки программирования (только если явно упоминаются как тема изучения)
            "python", "javascript", "java", "c++", "cpp", "go", "rust", "sql", "bash",
            # Концепции программирования (только если это основная тема)
            "алгоритм программирования", "функция программирования", "класс программирования",
            "объектно-ориентированное программирование", "функциональное программирование",
            # Разработка (только если явно про разработку ПО)
            "разработка приложения", "разработка скрипта", "разработка модуля", "разработка библиотеки",
            "api разработка", "backend разработка", "frontend разработка"
        ]

        # Исключаем общие термины, которые не означают программирование
        excluded_keywords = [
            "разработка проекта", "разработка решения", "разработка подхода",  # Это не про код
            "алгоритм работы", "алгоритм процесса",  # Это не про программирование
            "функция системы", "функция процесса",  # Это не про функции в коде
        ]

        # ЖЕСТКАЯ ПРОВЕРКА: код нужен ТОЛЬКО если тема явно про разработку ПО или изучение языков программирования

        # Проверяем, нет ли исключающих ключевых слов (общие термины, не про код)
        all_text = " ".join([
            " ".join(seed.skills),
            seed.project_description,
            " ".join(seed.learning_outcomes)
        ]).lower()

        # Если есть исключающие ключевые слова, код не нужен
        if any(excluded in all_text for excluded in excluded_keywords):
            return False

        # Проверяем навыки (строгая проверка)
        skills_text = " ".join(seed.skills).lower()
        skills_match = any(keyword in skills_text for keyword in programming_keywords)

        # Проверяем описание проекта (строгая проверка)
        desc_text = seed.project_description.lower()
        desc_match = any(keyword in desc_text for keyword in programming_keywords)

        # Проверяем образовательные результаты (строгая проверка)
        lo_text = " ".join(seed.learning_outcomes).lower()
        lo_match = any(keyword in lo_text for keyword in programming_keywords)

        # Код нужен ТОЛЬКО если есть явное совпадение в навыках ИЛИ описании ИЛИ LO
        # И при этом нет исключающих ключевых слов
        return skills_match or desc_match or lo_match

    def _parse_p2p_criteria(self, block: str) -> list[str]:
        """
        Парсит критерии P2P проверки из блока задачи.
        
        Ищет секцию "Критерии проверки" с чеклистом.
        
        Args:
            block: Текст блока задачи
            
        Returns:
            Список критериев P2P проверки
        """
        criteria = []

        # Ищем секцию критериев, включая canonical PDF-блок.
        criteria_match = re.search(
            r'\*\*(?:Что должно получиться|Критерии проверки.*?):?\*\*\s*\n(.*?)(?=\n\*\*|\n###|\n---|\Z)',
            block,
            flags=re.S | re.I
        )

        if criteria_match:
            criteria_text = criteria_match.group(1)
            # Парсим чеклист (- [ ] или - [x] или просто -)
            for line in criteria_text.split('\n'):
                line = line.strip()
                # Убираем маркеры чеклиста
                line = re.sub(r'^[-*]\s*\[[ x]?\]\s*', '', line)
                line = re.sub(r'^[-*]\s*', '', line)
                if line and len(line) > 5:  # Минимальная длина критерия
                    criteria.append(line)

        return criteria[:7]  # Максимум 7 критериев

    def _parse_approach_bullets(self, approach: str) -> list[str]:
        """
        Разбирает markdown-блок "Подход" на пункты, сохраняя многострочные куски и код.
        """
        if not approach:
            return []

        lines = approach.splitlines()
        bullets: list[str] = []
        current: list[str] = []
        in_code = False
        fence = None

        def flush():
            text = "\n".join(current).strip()
            if text:
                bullets.append(text)
            current.clear()

        for raw in lines:
            line = raw.rstrip()
            stripped = line.lstrip()

            if in_code:
                current.append(line)
                if stripped.startswith(fence or "```"):
                    in_code = False
                    fence = None
                continue

            if not stripped:
                if current:
                    current.append("")
                continue

            # Начало нового буллета
            bullet_match = re.match(r"^((?:-|\*|•)|\d+\.)\s+(.*)", stripped)
            if bullet_match:
                flush()
                current.append(bullet_match.group(2).strip())
                continue

            # Кодовые блоки
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code = True
                fence = stripped[:3]
                if not current:
                    current.append(stripped)
                else:
                    current.append(stripped)
                continue

            current.append(stripped)

        flush()
        return bullets

    def _summarize_to_150(self, bullets: list[str], language: str) -> list[str]:
        """Суммаризует подход до 150 слов."""
        from ..utils.text_analysis import count_words

        text = " ".join(bullets).strip()
        words_count = count_words(text, language)
        if words_count <= THRESHOLDS["approach_words_max"]:
            return bullets
        new_bullets = []

        total = 0
        for b in bullets:
            sents = re.split(r"(?<=[\.!\?])\s+", b.strip())
            short = " ".join(sents[:2]).strip()
            w = count_words(short, language)
            if total + w <= THRESHOLDS["approach_words_max"]:
                new_bullets.append(short)
                total += w
            else:
                break
        if not new_bullets:
            new_bullets = ["Сформулируй рациональный план действий, опираясь на рамки проекта и доступные инструменты."]
        return new_bullets

    def _fix_goal_active_form(self, goal: str, language: str) -> str:
        """
        Исправляет цель, если она не в активной форме.
        Заменяет пассивные/изучающие глаголы на активные.
        """
        if language != "ru":
            return goal
        original_goal = (goal or "").strip()
        if not original_goal:
            return goal

        # Запрещенные глаголы (пассивные/изучающие) - расширенный список
        forbidden_verbs = [
            r"\bизуч(ить|и|ать|ение)\b", r"\bознаком(иться|ься|ление)\b", r"\bпосмотр(еть|и|ать)\b",
            r"\bрассмотр(еть|и|ать|ение)\b", r"\bпознаком(иться|ься|ление)\b", r"\bузна(ть|ть|вать)\b",
            r"\bпоня(ть|ть|вать|тие)\b", r"\bизучен(ие|ия)\b", r"\bознакомлен(ие|ия)\b"
        ]

        # Проверяем наличие запрещенных глаголов
        goal_lower = original_goal.lower()
        has_forbidden = any(re.search(verb, goal_lower) for verb in forbidden_verbs)
        fixed_goal = original_goal

        if has_forbidden:
            # Заменяем на активные формы
            replacements = {
                r"\bизуч(ить|и|ать|ение)\b": "проанализировать",
                r"\bознаком(иться|ься|ление)\b": "описать",
                r"\bпосмотр(еть|и|ать)\b": "проанализировать",
                r"\bрассмотр(еть|и|ать|ение)\b": "проанализировать",
                r"\bпознаком(иться|ься|ление)\b": "описать",
                r"\bузна(ть|ть|вать)\b": "определить",
                r"\bпоня(ть|ть|вать|тие)\b": "проанализировать",
                r"\bизучен(ие|ия)\b": "анализ",
                r"\bознакомлен(ие|ия)\b": "описание"
            }

            for pattern, replacement in replacements.items():
                fixed_goal = re.sub(pattern, replacement, fixed_goal, flags=re.I)

        if not has_active_goal_verb(fixed_goal):
            fixed_goal = self._force_active_goal(fixed_goal)

        if fixed_goal != original_goal:
            print(f"  ⚠️ Исправлена цель (активная форма): '{original_goal}' -> '{fixed_goal}'", file=sys.stderr, flush=True)

        return fixed_goal

    @staticmethod
    def _force_active_goal(goal: str) -> str:
        """Convert vague or imperfective Russian goal wording into an explicit action."""
        normalized = re.sub(r"\s+", " ", (goal or "").strip())
        if not normalized:
            return normalized

        leading_replacements = [
            (r"^формировать\b", "Сформировать"),
            (r"^сформировывать\b", "Сформировать"),
            (r"^собирать\b", "Сформировать"),
            (r"^работать\s+с\b", "Настроить работу с"),
            (r"^оформлять\b", "Подготовить"),
            (r"^делать\b", "Выполнить"),
        ]
        for pattern, replacement in leading_replacements:
            if re.search(pattern, normalized, flags=re.I):
                return re.sub(pattern, replacement, normalized, count=1, flags=re.I)

        lowered_first = normalized[0].lower() + normalized[1:] if normalized else normalized
        return f"Сформировать {lowered_first}"

    def _fix_task_situation(self, situation: str, input_data: str, goal: str, language: str) -> str:
        """
        Нормализует блок «Ситуация».
        Если модель не сгенерировала его, добавляет минимальный рабочий контекст,
        чтобы задача не превращалась в голый чек-лист.
        """
        normalized = (situation or "").strip()
        if normalized:
            if language == "ru" and not normalized.endswith((".", "!", "?")):
                normalized += "."
            return self.style.rewrite(normalized, language)

        input_short = re.sub(r"`[^`]+`", "", input_data or "").strip()
        input_short = re.sub(r"\s+", " ", input_short).strip(" .")
        goal_short = re.sub(r"\s+", " ", goal or "").strip(" .")
        if language == "ru":
            generated = (
                f"У тебя на руках {input_short or 'рабочие материалы по проекту'}. "
                f"По ним нужно принять понятное решение для команды и оформить результат так, "
                f"чтобы другой участник смог его проверить. "
                f"Фокус задачи: {goal_short or 'подготовить проверяемый артефакт'}."
            )
        else:
            generated = (
                "You have project materials on hand. Use them to make a concrete working decision "
                "and produce an artifact another learner can review."
        )
        return self.style.rewrite(generated, language)

    def _fix_task_risk(self, risk_text: str, situation: str, goal: str, language: str) -> str:
        """
        Нормализует блок «Ограничение / риск».
        Если модель его не вернула, извлекает напряжение из ситуации и цели.
        """
        normalized = re.sub(r"\s+", " ", (risk_text or "").strip())
        if normalized:
            if language == "ru" and not normalized.endswith((".", "!", "?")):
                normalized += "."
            return self.style.rewrite(normalized, language)

        situation_low = (situation or "").lower()
        if any(marker in situation_low for marker in ("срок", "дедлайн", "время", "тайм", "срочно")):
            generated = "Есть ограничение по сроку: решение нужно оформить быстро и без лишних итераций."
        elif any(marker in situation_low for marker in ("безопас", "риск", "ошиб", "конфликт", "неяс")):
            generated = "Главный риск — принять решение без достаточной ясности и получить проблемный результат на проверке."
        else:
            generated = f"Важно явно зафиксировать ограничения и критерии выбора, чтобы результат по задаче «{goal or 'проекта'}» можно было проверить."
        return self.style.rewrite(generated, language)

    @staticmethod
    def _extract_theory_topics(theory_summary: str) -> list[str]:
        """Извлекает названия тем из краткого конспекта теории."""
        topics: list[str] = []
        for line in (theory_summary or "").splitlines():
            match = re.match(r"^\s*\d+\.\s+(.+?)\s*$", line.strip())
            if match:
                topics.append(match.group(1).strip())
        return topics

    @staticmethod
    def _token_set(text: str) -> set[str]:
        stop_words = {
            "это", "для", "как", "что", "или", "при", "над", "под", "про", "без", "его", "ее",
            "её", "они", "она", "оно", "так", "уже", "ещё", "этот", "эта", "эти", "тот",
            "который", "которая", "которые", "если", "только", "будет", "задача", "проект",
            "нужно", "нужен", "нужна", "нужны", "можно", "нельзя", "важно",
        }
        tokens = re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", (text or "").lower())
        return {token for token in tokens if len(token) > 3 and token not in stop_words}

    def _infer_covered_outcomes(self, seed: ProjectSeed, *task_texts: str) -> list[str]:
        """Привязывает задачу к 1-2 LO по пересечению смысловых токенов."""
        blob_tokens = set()
        for text in task_texts:
            blob_tokens |= self._token_set(text)
        matches: list[tuple[int, str]] = []
        for lo in seed.learning_outcomes or []:
            lo_tokens = self._token_set(lo)
            score = len(blob_tokens & lo_tokens)
            if score > 0:
                matches.append((score, lo))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [lo for _, lo in matches[:2]]

    def _infer_theory_support(self, theory_summary: str, *task_texts: str) -> list[str]:
        """Определяет, какие темы из теории поддерживают задачу."""
        blob_tokens = set()
        for text in task_texts:
            blob_tokens |= self._token_set(text)
        matches: list[tuple[int, str]] = []
        for topic in self._extract_theory_topics(theory_summary):
            topic_tokens = self._token_set(topic)
            score = len(blob_tokens & topic_tokens)
            if score > 0:
                matches.append((score, topic))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [topic for _, topic in matches[:2]]

    def _fix_result_artifact(self, result: str, seed: ProjectSeed, task_idx: int) -> tuple[str, str]:
        """
        Проверяет и исправляет ожидаемый результат, добавляя артефакт и локацию, если их нет.
        
        Returns:
            Tuple[result_text, artifact_location]
        """
        def _extract_path_candidates(text: str) -> list[str]:
            candidates: list[str] = []
            for match in _RX_ARTIFACT_PATH.finditer(text or ""):
                candidate = match.group(1).strip("`'\".,;:()[]{}")
                if "://" in candidate:
                    continue
                if candidate not in candidates:
                    candidates.append(candidate)
            return candidates

        def _pick_primary_path(candidates: list[str]) -> str:
            if not candidates:
                return ""
            preferred = [
                path for path in candidates
                if "/part-" in path.lower() and not path.lower().startswith("repo/")
            ]
            if preferred:
                return preferred[0]
            non_generic = [path for path in candidates if not path.lower().startswith("repo/")]
            return non_generic[0] if non_generic else ""

        # Проверяем наличие артефакта (файл/отчет/код/скриншот)
        artifact_keywords = [
            r"файл\s+\w+", r"отчет", r"отч[её]т", r"код", r"скриншот", r"результат",
            r"документ", r"артефакт", r"README", r"markdown", r"текст", r"речь",
            r"выступлен", r"таблиц", r"матриц", r"схем", r"план", r"презентац",
            r"\.md", r"\.py", r"\.txt", r"\.xlsx", r"\.csv", r"\.png"
        ]
        has_artifact = any(re.search(kw, result, flags=re.I) for kw in artifact_keywords)

        # Проверяем наличие локации (путь, папка, рабочая область, файл)
        location_keywords = [
            r"путь", r"репозиторий", r"repo/", r"по пути", r"размещ[её]н",
            r"находится", r"директори", r"папк", r"рабоч", r"файл"
        ]
        has_location = any(re.search(kw, result, flags=re.I) for kw in location_keywords)

        # Извлекаем локацию, если она есть в скобках
        artifact_location = ""
        m_loc = re.search(r"\((?:где найти|where|путь|path):\s*([^)]+)\)", result, flags=re.I)
        if m_loc:
            artifact_location = m_loc.group(1).strip()
            result = re.sub(r"\s*\((?:где найти|where|путь|path):\s*([^)]+)\)\s*$", "", result).strip()

        # Если в тексте уже есть явный путь к артефакту, считаем его каноническим.
        path_candidates = _extract_path_candidates(result)
        explicit_artifact_path = _pick_primary_path(path_candidates)
        if explicit_artifact_path:
            artifact_location = explicit_artifact_path

        # Если нет локации, используем шаблон из seed или нейтральный проектный путь.
        if not artifact_location:
            artifact_location = self._artifact_location_for_task(seed, task_idx)

        # Если есть канонический путь к артефакту, убираем дублирующее упоминание
        # альтернативного "README в repo/", чтобы в результате был один понятный deliverable.
        if explicit_artifact_path:
            for candidate in path_candidates:
                if not candidate.lower().startswith("repo/"):
                    continue
                result = result.replace(f" Размещен в репозитории по пути {candidate}", "")
                result = result.replace(f" Размещен в репозитории по пути `{candidate}`", "")
                result = result.replace(f", размещенная в репозитории по пути `{candidate}`", "")
                result = result.replace(f", размещённая в репозитории по пути `{candidate}`", "")
                result = re.sub(
                    rf"\.?\s*[^.`\n]*`?{re.escape(candidate)}`?",
                    "",
                    result,
                    count=1,
                )
            result = re.sub(r"\s{2,}", " ", result).strip()

        # Если нет артефакта или локации в тексте, добавляем
        if not has_artifact or not has_location:
            # Определяем тип артефакта по умолчанию
            if not has_artifact:
                artifact_type = "Файл README.md"
            else:
                # Извлекаем тип артефакта из текста
                artifact_match = re.search(
                    r"(файл|отчет|отч[её]т|код|скриншот|документ|текст|таблица|матрица|схема|план|презентация)"
                    r"\s+([^\s,\.]+)?",
                    result,
                    flags=re.I,
                )
                if artifact_match:
                    artifact_type = artifact_match.group(0)
                else:
                    artifact_type = "Файл README.md"

            if explicit_artifact_path:
                result = re.sub(r"\s{2,}", " ", result).strip()
            else:
                # Формируем полный результат
                if not has_artifact and not has_location:
                    result = f"{artifact_type} размещён по пути `{artifact_location}`."
                elif not has_artifact:
                    result = f"{artifact_type}. {result} Артефакт размещён по пути `{artifact_location}`."
                elif not has_location:
                    result = f"{result} Артефакт размещён по пути `{artifact_location}`."

            print(f"  ⚠️ Добавлен артефакт/локация в результат задачи {task_idx+1}", file=sys.stderr, flush=True)

        return result, artifact_location

    @staticmethod
    def _is_generic_expected_artifact(result: str) -> bool:
        """Detect deliverable text that only points to a file without saying what is checked."""
        text = (result or "").strip()
        if not text:
            return True

        without_paths = _RX_ARTIFACT_PATH.sub("", text)
        without_code = re.sub(r"`[^`]*`", "", without_paths)
        normalized = re.sub(r"\s+", " ", without_code).strip(" .").lower()
        if not normalized:
            return True

        generic_patterns = [
            r"^(артефакт|результат|документ)\s+размещ",
            r"^файл\s+readme\.md(?:\s+с\s+результатом\s+задачи)?\s+размещ",
            r"^файл\s+\w+(?:\.\w+)?\s+размещ",
        ]
        if any(re.search(pattern, normalized, flags=re.I) for pattern in generic_patterns):
            return True

        words = re.findall(r"[А-Яа-яЁёA-Za-z0-9]+", normalized)
        return len(words) <= 8 and "размещ" in normalized and ("путь" in normalized or "файл" in normalized)

    @staticmethod
    def _artifact_kind_from_task(task: PracticeTask) -> str:
        """Infer a concrete review subject from the task instead of using a generic placeholder."""
        text = " ".join([
            task.title or "",
            task.goal or "",
            task.situation or "",
            task.expected_artifact or "",
        ]).lower()
        if any(marker in text for marker in ("дорожн", "roadmap", "роадмап")):
            return "дорожной картой проекта"
        if any(marker in text for marker in ("зависим", "гант", "критическ", "срок")):
            return "планом зависимостей, критическим участком и выводом по срокам"
        if any(marker in text for marker in ("структур", "декомпоз", "wbs", "работ")):
            return "структурой работ и декомпозицией задач"
        if any(marker in text for marker in ("бэклог", "backlog", "приоритет")):
            return "разбором бэклога, приоритетами и обоснованием очередности"
        if any(marker in text for marker in ("выступ", "реч", "sermon")):
            return "структурой выступления и итоговыми тезисами"
        if any(marker in text for marker in ("матриц", "таблиц")):
            return "таблицей решений и обоснованием выбора"
        return "решением по задаче"

    def _describe_expected_artifact(
        self,
        task: PracticeTask,
        artifact_location: str,
        language: str,
    ) -> str:
        """Build a concrete expected-result contract for P2P review."""
        if language != "ru":
            return (
                f"README.md document with the task solution: assumptions, decision, rationale and final conclusion. "
                f"The artifact is located at `{artifact_location}`."
            )

        artifact_kind = self._artifact_kind_from_task(task)
        task_context = " ".join([
            task.title or "",
            task.goal or "",
            task.situation or "",
            task.constraints_or_risk or "",
        ]).lower()
        stakeholder_tail = " для заказчика" if "заказчик" in task_context else ""
        return (
            f"Документ README.md с {artifact_kind}: содержит исходные допущения, решение, "
            f"обоснование выбора и итоговый вывод{stakeholder_tail}. "
            f"Артефакт размещён по пути `{artifact_location}`."
        )

    def _ensure_task_artifact_contract(
        self,
        tasks: list[PracticeTask],
        seed: ProjectSeed,
        language: str,
        artifact_chain_plan: ArtifactChainPlan | None = None,
    ) -> list[PracticeTask]:
        """Guarantee every task has a concrete deliverable, location and review checklist."""
        planned_locations: dict[int, str] = {}
        if artifact_chain_plan is not None:
            for step in artifact_chain_plan.steps:
                planned_locations[step.task_index] = step.artifact_location

        for idx, task in enumerate(tasks, 1):
            raw_result = (task.expected_artifact or "").strip()
            planned_location = planned_locations.get(idx, "")
            explicit_paths = [match.group(1) for match in _RX_ARTIFACT_PATH.finditer(raw_result)]

            if not (task.artifact_location or "").strip() and planned_location:
                task.artifact_location = planned_location

            fixed_result, fixed_location = self._fix_result_artifact(raw_result, seed, idx - 1)
            if planned_location and not explicit_paths:
                fixed_location = planned_location

            if fixed_location:
                task.artifact_location = fixed_location

            artifact_location = (task.artifact_location or "").strip()
            if artifact_location and artifact_location.lower() not in fixed_result.lower():
                fixed_result = (
                    f"{fixed_result.rstrip('.')} "
                    f"Артефакт размещён по пути `{artifact_location}`."
                )

            if not fixed_result.strip():
                fallback_location = artifact_location or planned_location or self._artifact_location_for_task(seed, idx - 1)
                task.artifact_location = fallback_location
                fixed_result = self._describe_expected_artifact(task, fallback_location, language)

            if self._is_generic_expected_artifact(fixed_result):
                fallback_location = artifact_location or planned_location or self._artifact_location_for_task(seed, idx - 1)
                task.artifact_location = fallback_location
                fixed_result = self._describe_expected_artifact(task, fallback_location, language)

            task.expected_artifact = self.style.rewrite(fixed_result.strip(), language)
            if not task.expected_artifact.strip():
                fallback_location = artifact_location or planned_location or self._artifact_location_for_task(seed, idx - 1)
                task.artifact_location = fallback_location
                task.expected_artifact = self._describe_expected_artifact(task, fallback_location, language)

            task.p2p_criteria = self._ensure_p2p_criteria(
                list(task.p2p_criteria or []),
                task.artifact_location,
                task.expected_artifact,
                task.theory_support,
                language,
            )

        return tasks

    @staticmethod
    def _normalize_sentence(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip()).strip(" -")
        if not normalized:
            return ""
        if normalized[0].islower():
            normalized = normalized[0].upper() + normalized[1:]
        if normalized[-1] not in ".!?":
            normalized += "."
        return normalized

    @staticmethod
    def _is_observable_p2p_criterion(text: str) -> bool:
        signals = [
            "содержит", "указан", "указаны", "есть", "присутствует", "присутствуют",
            "нет", "совпадает", "заполнен", "заполнены", "описан", "описаны",
            "размещен", "размещён", "добавлен", "добавлены", "оформлен", "оформлена",
            "перечислен", "перечислены", "зафиксирован", "зафиксированы", "учтен",
            "учтены", "обоснован", "обоснование", "путь", "файл", "раздел", "схема",
            "таблица", "презентация", "минимум", "по указанному пути", "в документе",
            "в таблице", "на схеме",
        ]
        normalized = (text or "").strip().lower()
        return len(normalized) >= 12 and any(signal in normalized for signal in signals)

    @staticmethod
    def _artifact_review_subject(expected_artifact: str, artifact_location: str) -> tuple[str, str]:
        text = f"{expected_artifact or ''} {artifact_location or ''}".lower()
        if any(ext in text for ext in (".png", ".svg", ".drawio", ".mmd")) or "схем" in text or "диаграм" in text:
            return "схеме", "Схема"
        if any(ext in text for ext in (".xlsx", ".csv")) or "таблиц" in text:
            return "таблице", "Таблица"
        if any(ext in text for ext in (".ppt", ".pptx")) or "презентац" in text:
            return "презентации", "Презентация"
        return "документе", "Документ"

    def _normalize_approach_bullets(
        self,
        bullets: list[str],
        theory_support: list[str],
        language: str,
    ) -> list[str]:
        """Нормализует подход и при необходимости добавляет явную опору на теорию."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for bullet in bullets:
            normalized = self._normalize_sentence(self.style.rewrite((bullet or "").strip(), language))
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)

        if not cleaned:
            cleaned = ["Зафиксируй решение по задаче и подготовь проверяемый артефакт."]

        needs_theory_anchor = bool(theory_support) and not any(
            any(token in bullet.lower() for token in self._token_set(topic))
            for bullet in cleaned
            for topic in theory_support
        )
        if needs_theory_anchor:
            theory_anchor = ", ".join(theory_support[:2])
            theory_bullet = self.style.rewrite(
                f"Проверь, что решение прямо опирается на темы из теории: {theory_anchor}.",
                language,
            )
            theory_bullet = self._normalize_sentence(theory_bullet)
            if len(cleaned) >= 6:
                cleaned[-1] = theory_bullet
            else:
                cleaned.append(theory_bullet)

        return cleaned[:6]

    def _ensure_p2p_criteria(
        self,
        criteria: list[str],
        artifact_location: str,
        expected_artifact: str,
        theory_support: list[str],
        language: str,
    ) -> list[str]:
        """Делает критерии P2P бинарными, наблюдаемыми и привязанными к артефакту."""
        normalized: list[str] = []
        seen: set[str] = set()
        for criterion in criteria or []:
            item = self._normalize_sentence(self.style.rewrite((criterion or "").strip(), language))
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)

        subject_case, subject_title = self._artifact_review_subject(expected_artifact, artifact_location)
        if artifact_location and not any(
            signal in " ".join(normalized).lower()
            for signal in ("по указанному пути", "размещ", artifact_location.lower())
        ):
            normalized.append(f"Артефакт размещён по указанному пути `{artifact_location}`.")

        observable_count = sum(1 for item in normalized if self._is_observable_p2p_criterion(item))
        filler_candidates: list[str] = []

        if subject_case == "таблице":
            filler_candidates.append("В таблице заполнены все обязательные строки и столбцы без пустых ключевых ячеек.")
        elif subject_case == "схеме":
            filler_candidates.append("На схеме подписаны все ключевые элементы и связи между ними.")
        elif subject_case == "презентации":
            filler_candidates.append("В презентации выделены ключевые тезисы, опорные слайды и итоговый вывод.")
        else:
            filler_candidates.append("В документе есть отдельные разделы с решением, аргументацией и итоговым выводом.")

        if theory_support:
            theory_anchor = ", ".join(theory_support[:2])
            filler_candidates.append(f"{subject_title} явно использует понятия из теории: {theory_anchor}.")

        filler_candidates.append("Формулировки в артефакте конкретны и позволяют другому участнику проверить результат без устных пояснений.")

        for candidate in filler_candidates:
            if len(normalized) >= 5 and observable_count >= 3:
                break
            key = candidate.lower()
            if key in seen:
                continue
            normalized.append(candidate)
            seen.add(key)
            if self._is_observable_p2p_criterion(candidate):
                observable_count += 1

        return normalized[:5]

    @staticmethod
    def _extract_sjm_task_anchors(sjm: str) -> list[str]:
        """Extract compact SJM anchors that must remain visible in practice tasks."""
        text = (sjm or "").strip()
        low = text.lower()
        if not low:
            return []

        anchors: list[str] = []
        if "заказчик" in low:
            anchors.append("заказчик")

        role_match = re.search(r"ты\s+[—-]\s+([^\.!\n]+)", low)
        if role_match:
            role = role_match.group(1).strip(" ,")
            if role:
                anchors.append(role)

        for pattern in (
            r"\b\d+\s*(?:минут[аы]?|час(?:а|ов)?|дн(?:я|ей)?|недел[ьяи]?|месяц(?:а|ев)?)\b",
            r"бюджет",
            r"релиз",
            r"срок",
            r"договор[её]н",
            r"план",
        ):
            match = re.search(pattern, low)
            if match:
                anchors.append(match.group(0))

        dedup: list[str] = []
        for anchor in anchors:
            anchor = anchor.strip()
            if anchor and anchor not in dedup:
                dedup.append(anchor)
        return dedup[:5]

    def _ensure_sjm_task_anchors(
        self,
        tasks: list[PracticeTask],
        seed: ProjectSeed,
        language: str,
        sjm_override: str | None = None,
    ) -> list[PracticeTask]:
        """Deterministically keep SJM role/constraint anchors visible in task wording."""
        anchors = self._extract_sjm_task_anchors(sjm_override or seed.sjm or "")
        if not anchors or not tasks:
            return tasks

        required_count = min(2, len(tasks))
        if "заказчик" in anchors:
            target_anchor = "заказчик"
            anchor_sentence = "Заказчик остаётся главным адресатом результата: решение должно помогать согласовать следующий шаг."
        else:
            target_anchor = anchors[0]
            anchor_sentence = f"Сохрани якорь кейса: {', '.join(anchors[:2])}."

        for idx, task in enumerate(tasks):
            task_text = " ".join(
                [
                    task.situation or "",
                    task.constraints_or_risk or "",
                    task.goal or "",
                    task.expected_artifact or "",
                ]
            ).lower()
            if idx >= required_count or target_anchor in task_text:
                continue

            sentence = self.style.rewrite(anchor_sentence, language)
            task.situation = self._normalize_sentence(f"{task.situation or ''} {sentence}".strip())

            if target_anchor not in (task.expected_artifact or "").lower():
                recipient = "заказчика" if target_anchor == "заказчик" else target_anchor
                task.expected_artifact = self._normalize_sentence(
                    f"{task.expected_artifact or ''} Артефакт показывает решение для {recipient}.".strip()
                )

        return tasks

    def _enforce_learning_activity_contract(self, tasks: list[PracticeTask], language: str) -> list[PracticeTask]:
        """Keeps materials as raw inputs and chains each task to the previous output."""
        for idx, task in enumerate(tasks, 1):
            previous = tasks[idx - 2] if idx > 1 else None
            normalized_input = normalize_task_input_for_learning_activity(
                task.input_data,
                task_index=idx,
                previous_artifact_location=previous.artifact_location if previous else None,
            )
            if normalized_input != task.input_data:
                task.input_data = self.style.rewrite(normalized_input, language)
        return tasks

    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Обрабатывает входные данные и возвращает результат (реализация BaseAgent).
        
        Args:
            input_data: Входные данные, должны содержать 'seed' (ProjectSeed)
            
        Returns:
            Словарь с результатами обработки
        """
        seed_input = input_data.get('seed', input_data)
        seed = seed_input if isinstance(seed_input, ProjectSeed) else ProjectSeed(**seed_input)
        kwargs: dict[str, Any] = {}
        for key in ("practice_plan_contract", "artifact_chain_plan", "section_context"):
            if key in input_data:
                kwargs[key] = input_data[key]
        result = self.generate(
            seed,
            instruction_text=input_data.get("instruction_text", ""),
            theory_summary=input_data.get("theory_summary", ""),
            **kwargs,
        )
        return {
            'tasks': [task.model_dump() for task in result.tasks],
            'bonus_tasks': [task.model_dump() for task in result.bonus_tasks] if result.bonus_tasks else None,
            'result': result,
        }

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Совместимый адаптер для старого graph/run-контракта."""
        if input_data.get("op") == "bonus":
            seed_input = input_data.get("seed", {})
            seed = seed_input if isinstance(seed_input, ProjectSeed) else ProjectSeed(**seed_input)
            tasks = self.generate_bonus(seed, int(input_data.get("n_bonus", 1)))
            return {
                "result": tasks,
                "tasks": [task.model_dump() for task in tasks],
            }
        return self.process(input_data)

    def _build_curriculum_context_section(
        self,
        seed: ProjectSeed,
        section_context: dict[str, Any] | None = None,
    ) -> str:
        """Строит секцию контекста из УП для промпта практики."""
        ctx = (section_context or {}).get("curriculum_context")
        if not isinstance(ctx, dict):
            ctx = getattr(seed, 'curriculum_context', None)
        if not ctx:
            return (
                "Контекст из учебного плана не предоставлен. "
                "Опирайся строго на описание проекта и LO выше; избегай общих формулировок — практика должна отражать специфику ЭТОГО проекта."
            )

        lines = [
            "Приоритет: описание проекта и LO из УП задают тематику и границы заданий; не подменяй их общими формулировками. Задания должны максимально соответствовать этому проекту."
        ]
        narrative_payload = (section_context or {}).get("narrative_contract") or ctx.get("narrative_contract")
        narrative_contract_section = render_narrative_contract_section(narrative_payload)
        if narrative_contract_section:
            lines.extend(["", narrative_contract_section])

        # Информация о блоке
        if ctx.get('block_name'):
            lines.append(f"Тематический блок УП: {ctx['block_name']}")

        if ctx.get('block_goals'):
            goals = ctx['block_goals']
            if isinstance(goals, list):
                lines.append(f"Цели блока: {'; '.join(goals[:3])}")

        # Предыдущие проекты (что студент уже делал на практике)
        prev_projects = ctx.get('previous_projects', [])
        if prev_projects:
            lines.append("")
            lines.append("ПРАКТИЧЕСКИЕ ЗАДАЧИ ИЗ ПРЕДЫДУЩИХ ПРОЕКТОВ БЛОКА:")
            for p in prev_projects[-2:]:
                lines.append(f"  - Проект <<{p.get('title')}>>: {p.get('description', '')[:100]}...")
            lines.append("НЕ ПОВТОРЯЙ типы заданий из предыдущих проектов! Создавай новые, более сложные.")

        # Следующие проекты (границы - НЕ ЗАБЕГАТЬ ВПЕРЁД!)
        next_projects = ctx.get('next_projects', [])
        if next_projects:
            lines.append("")
            lines.append("СЛЕДУЮЩИЕ ПРОЕКТЫ В БЛОКЕ (ГРАНИЦЫ - НЕ ТРОГАТЬ ЭТИ ТЕМЫ!):")
            for p in next_projects[:2]:
                # Показываем только название, БЕЗ LO (чтобы не провоцировать)
                lines.append(f"  - <<{p.get('title')}>>")
            lines.append("")
            lines.append("КРИТИЧЕСКИ ВАЖНО:")
            lines.append("НЕ вводи новые доменные термины и концепции из следующих проектов!")
            lines.append("Задания ТОЛЬКО по темам ТЕКУЩЕГО проекта (см. описание и LO выше).")
            lines.append("Можно развивать общие навыки (структурирование, ясность, проверяемость), но НЕ новые специальные темы.")

        return "\n".join(lines) if lines else "Контекст из учебного плана не предоставлен."

    def _build_sjm_section(
        self,
        seed: ProjectSeed,
        section_context: dict[str, Any] | None = None,
    ) -> str:
        """Строит секцию сторителлинга/кейса для промпта практики."""
        sjm = (section_context or {}).get("sjm_context") or getattr(seed, 'sjm', None)
        ctx = (section_context or {}).get("curriculum_context")
        if not isinstance(ctx, dict):
            ctx = getattr(seed, 'curriculum_context', None)

        # Пробуем взять SJM из контекста, если не задан напрямую
        if not sjm and ctx:
            sjm = ctx.get('sjm_context')

        if not sjm:
            # Минимальный контекст по описанию проекта, если SJM в УП пуст
            lines = [
                "Сторителлинг/кейс не предоставлен (колонка SJM в УП пуста).",
                "",
                "Сгенерируй минимальный рабочий контекст по описанию проекта (роль, компания/проект, ситуация; 4–6 строк) и привяжи к нему ВСЕ задания.",
                "Входные данные задач должны ссылаться на этот контекст. Опирайся на описание проекта и LO из УП, избегай общих мест."
            ]
            return "\n".join(lines)

        lines = [
            "КРИТИЧЕСКИ ВАЖНО: Задания должны быть ПРИВЯЗАНЫ к этому кейсу/истории!",
            "",
            sjm,
            "",
            "ОБЯЗАТЕЛЬНО:",
            "- Студент должен решать задачи В КОНТЕКСТЕ этого кейса",
              "- Входные данные каждой задачи должны ссылаться на персонажей/компании/ситуации из кейса",
              "- Все задания - как будто студент действительно работает над ЭТОЙ конкретной проблемой",
              "- Все задания должны быть этапами одной цепочки работы над одним результатом, а не разными учебными направлениями",
              "- Если в SJM есть заказчик, слово «заказчик» должно появиться в задаче 1 и минимум ещё в одной задаче",
              "- Не заменяй роль из SJM на продакта, руководителя или абстрактную команду, если такой роли нет в кейсе"
          ]
        return "\n".join(lines)

    def _determine_content_type(self, seed: ProjectSeed) -> str:
        """
        Определяет тип контента на основе направления.
        
        Returns:
            'hard_code' | 'low_code' | 'no_code'
        """
        direction = (getattr(seed, 'direction', '') or seed.thematic_block or "").upper()

        # Hard code: Разработчик ПО
        hard_code_directions = {
            'C', 'CPP', 'C++', 'JAVA', 'GO', 'RUST', 'BACKEND', 'MOBILE',
            'WEB', 'FRONTEND', 'FULLSTACK', 'DEV', 'SWE'
        }

        # Low code: DS, DevOps, QA
        low_code_directions = {
            'DS', 'DO', 'QA', 'BIO', 'BIOINF', 'DEVOPS', 'DATA',
            'ML', 'AI', 'TESTING', 'AUTOMATION'
        }

        # No code: PjM, UX, КБ, BSA
        no_code_directions = {
            'PJM', 'UX', 'CB', 'KB', 'BSA', 'BA', 'PM', 'CYBER',
            'SECURITY', 'PRODUCT', 'DESIGN', 'MANAGEMENT', 'ANALYST'
        }

        if direction in hard_code_directions:
            return 'hard_code'
        elif direction in low_code_directions:
            return 'low_code'
        elif direction in no_code_directions:
            return 'no_code'
        else:
            return 'low_code'

    def _build_content_type_section(self, content_type: str) -> str:
        """Строит секцию типа контента для промпта практики."""

        if content_type == 'hard_code':
            return """ТИП: ТЕХНИЧЕСКИЙ (hard code)
Это проект для РАЗРАБОТЧИКОВ. Типы и порядок заданий — по теории и LO: как в реальной разработке по этой теме (например: требования → проектирование → реализация → проверка → документация). Разнообразие по типу деятельности, не один шаблон для всех проектов.
Разрешено: код, алгоритмы, структуры данных, конфиги, скрипты. Тон: профессиональный, технический."""

        elif content_type == 'low_code':
            return """ТИП: ТЕХНИЧЕСКИЙ С ОГРАНИЧЕНИЯМИ (low code)
Это проект для DS, DevOps, QA. Типы заданий — по теории и LO (минимум кода: конфиги, простые скрипты; данные, пайплайны, тесты; таблицы, схемы). ОГРАНИЧЕНО: сложный код. Тон: практический, с примерами."""

        else:  # no_code
            return """ТИП: ГУМАНИТАРНЫЙ (no code)
Это проект для МЕНЕДЖЕРОВ, АНАЛИТИКОВ (PjM, BSA, UX, КБ).

ЗАДАНИЯ БЕЗ КОДА. Типы заданий выбирай по теории и LO проекта (примеры: анализ и решение, документы, коммуникация, оценка/приоритизация, схемы процессов). Последовательность — как в реальной работе по этой теме, не шаблонная.

АРТЕФАКТЫ: документы, таблицы, схемы, презентации — НЕ код!
ТОН: бизнесовый, реальные кейсы."""

    def _build_formulas_requirements(self, seed: ProjectSeed, content_type: str) -> str:
        """Строит требования к формулам и коду в заданиях."""

        if content_type == 'no_code':
            return """ФОРМУЛЫ И КОД В ЗАДАНИЯХ: ПОЛНОСТЬЮ ЗАПРЕЩЕНЫ!
Задания должны быть выполнимы БЕЗ программирования.
Артефакты: документы, таблицы, схемы, презентации.
НЕ проси писать код, скрипты или формулы."""

        elif content_type == 'low_code':
            return """КОД В ЗАДАНИЯХ: Минимально, только если критически нужен.
Максимум 1-2 задания с простым кодом (конфиги, скрипты до 20 строк).
Остальные задания — без кода (анализ, документация, схемы)."""

        else:  # hard_code
            return """КОД В ЗАДАНИЯХ: Разрешён.
Типы и порядок заданий — по теории и LO: как в реальной разработке по этой теме. Разнообразие по типу деятельности (кодирование, рефакторинг, тестирование, документирование и т.д.), не один шаблон для всех проектов."""

    def generate(
        self,
        seed: ProjectSeed,
        instruction_text: str = "",
        theory_summary: str = "",
        practice_plan_contract: Any | None = None,
        artifact_chain_plan: ArtifactChainPlan | dict[str, Any] | None = None,
        section_context: dict[str, Any] | None = None,
    ) -> PracticeResult:
        """
        Генерирует практические задачи.

        Args:
            seed: Входные данные проекта
            instruction_text: Текст инструкции из Главы 1 (для избежания дублирования в задачах)
            theory_summary: Краткий конспект Главы 2 (ключевые понятия и темы)

        Returns:
            PracticeResult с задачами
        """
        n = seed.tasks_count or THRESHOLDS["practice_tasks_recommend"][0]
        system_prompt = self.config.get_prompt("system").format(language=seed.language)
        if self.didactics_context:
            system_prompt = f"{system_prompt}\n\n=== DIDACTICS CONTEXT ===\n{self.didactics_context}"
        group_size = seed.group_size if seed.project_type == "group" else None

        # Формируем информацию о репозитории для промпта
        repo_info = ""
        repo_path_template = seed.repo_path_template if not is_generic_repo_path_template(seed.repo_path_template) else ""
        if seed.repo_base_url or repo_path_template:
            repo_info = "\nИнформация о репозитории для результатов:"
            if seed.repo_base_url:
                repo_info += f"\n- Базовый URL: {seed.repo_base_url}"
            if repo_path_template:
                repo_info += f"\n- Шаблон пути: {repo_path_template}"
            repo_info += "\nИспользуй эту информацию при указании локации ожидаемого результата."

        # Практика получает schema-filtered payload, чтобы контексты разделов не смешивались.
        curriculum_context_section = self._build_curriculum_context_section(seed, section_context=section_context)
        sjm_section = self._build_sjm_section(seed, section_context=section_context)
        practice_plan_section = render_practice_plan_contract_section(
            practice_plan_contract or (section_context or {}).get("practice_plan_contract")
        )

        # Определяем тип контента (hard_code / low_code / no_code)
        content_type = self._determine_content_type(seed)
        content_type_section = self._build_content_type_section(content_type)
        formulas_code_requirements = self._build_formulas_requirements(seed, content_type)

        # Получаем direction для промпта
        direction = getattr(seed, 'direction', '') or seed.thematic_block or "—"

        self.logger.info(f"Тип контента для практики: {content_type} (direction={direction})")

        # Логируем построенный контекст УП
        ctx = getattr(seed, 'curriculum_context', None)
        if ctx:
            self.logger.info("=" * 50)
            self.logger.info("PRACTICE AGENT - Контекст УП для промпта:")
            self.logger.info(f"  Блок: {ctx.get('block_name', 'N/A')}")
            self.logger.info(f"  Номер проекта: {ctx.get('current_project_order', 'N/A')}")
            prev_count = len(ctx.get('previous_projects', []))
            next_count = len(ctx.get('next_projects', []))
            self.logger.info(f"  Проектов ДО: {prev_count}, ПОСЛЕ: {next_count}")
            self.logger.info(f"  SJM: {'Да' if ctx.get('sjm_context') else 'Нет'}")
            self.logger.info("=" * 50)

        # Данные из УП
        platform_name = getattr(seed, 'platform_name', None) or "project"
        gitlab_link = getattr(seed, 'gitlab_link', None) or "—"
        filtered_learning_outcomes = (section_context or {}).get("learning_outcomes") or seed.learning_outcomes
        filtered_skills = (section_context or {}).get("skills") or seed.skills
        filtered_required_tools = (section_context or {}).get("required_tools") or seed.required_tools
        filtered_project_description = (section_context or {}).get("project_description") or seed.project_description

        # Если theory_summary не передан, формируем заглушку
        if not theory_summary:
            theory_summary = "Конспект теории не предоставлен. Ориентируйся на описание проекта и LO."
        if isinstance(artifact_chain_plan, dict):
            artifact_chain_plan = ArtifactChainPlan(**artifact_chain_plan)
        if artifact_chain_plan is None:
            artifact_chain_plan = self.artifact_chain_planner.plan(seed, n, theory_summary=theory_summary)
        self.last_artifact_chain_plan = artifact_chain_plan

        # Режим «приближение к референсу»: если передан эталонный фрагмент заданий — добавляем в промпт
        reference_hint = getattr(seed, "reference_practice_hint", None)
        if reference_hint and reference_hint.strip():
            reference_practice_section = (
                "\n=== ЭТАЛОН (ОРИЕНТИРУЙСЯ НА СТРУКТУРУ И СТИЛЬ ЗАДАНИЙ) ===\n"
                "Ниже — фрагмент эталонного README с заданиями. Сохраняй похожую структуру формулировок и типы заданий, адаптируя под описание и LO текущего проекта.\n\n"
                + reference_hint.strip()
            )
        else:
            reference_practice_section = ""

        usr = self.config.get_prompt("user_template").format(
            n=n,
            i="{i}",
            required_tools=", ".join(filtered_required_tools) if filtered_required_tools else "—",
            project_description=filtered_project_description,
            learning_outcomes="; ".join(filtered_learning_outcomes),
            skills="; ".join(filtered_skills),
            group_size=group_size or "—",
            repo_info=repo_info,
            instruction_text=instruction_text or "—",
            theory_summary=theory_summary,
            curriculum_context_section=curriculum_context_section,
            sjm_section=sjm_section,
            reference_practice_section=reference_practice_section,
            content_type_section=content_type_section,
            formulas_code_requirements=formulas_code_requirements,
            direction=direction,
            platform_name=platform_name,
            gitlab_link=gitlab_link,
        )
        if practice_plan_section:
            usr = (
                f"{usr}\n\n=== PRACTICE PLAN CONTRACT ===\n"
                "Следуй этому плану задач. Можно менять формулировки, но нельзя ломать causal chain, "
                "LO coverage и правило raw evidence.\n\n"
                f"{practice_plan_section}"
            )
        usr = f"{usr}\n\n=== ARTIFACT CHAIN CONTRACT ===\n{artifact_chain_plan.to_prompt_context()}"
        if seed.reference_project_hint and seed.reference_project_hint.strip():
            usr = (
                f"{usr}\n\n=== ЭТАЛОН ИДЕАЛЬНОГО ПРОЕКТА ===\n"
                "Ниже дан идеальный образ проекта. Используй его как ориентир по плотности, стилю и качеству заданий,"
                " но факты, ограничения и тему бери из текущего проекта и УП.\n\n"
                f"{seed.reference_project_hint.strip()}"
            )
        generation_kwargs = self.llm_kwargs.copy()
        generation_kwargs.setdefault("temperature", 0.2)
        md = self.llm.complete(system=system_prompt, user=usr, **generation_kwargs)

        tasks: list[PracticeTask] = []
        indices = [m.start() for m in self.rx_task.finditer(md)] + [len(md)]
        h_matches = list(self.rx_task.finditer(md))
        for idx, h in enumerate(h_matches):
            start = h.end()
            end = indices[idx + 1]
            block = md[start:end].strip()
            title = h.group(2).strip()

            def _extract(label: str) -> str:
                pat = rf"\*\*{label}:?\*\*\s*(.+?)(?=\n\*\*|\Z)"
                m = re.search(pat, block, flags=re.S)
                return m.group(1).strip() if m else ""

            def _extract_any(labels: list[str]) -> str:
                for label in labels:
                    value = _extract(label)
                    if value:
                        return value
                return ""

            public_action = _extract("Что нужно сделать")
            public_result = _extract("Что должно получиться")
            situation = _extract("Ситуация") or _extract_inline_from_public(public_action, "Ситуация")
            constraints_or_risk = _extract_any(["Ограничение / риск", "Ограничение/риск", "Ограничение", "Риск"])
            input_data = _extract("Входные данные") or _extract_inline_from_public(public_action, "Исходные данные")
            goal = _extract("Цель") or _extract_inline_from_public(public_action, "Цель")
            approach = _extract("Подход") or _extract_inline_from_public(public_action, "Подход") or public_action
            result = _extract("Ожидаемый результат") or public_result

            # Парсим критерии P2P проверки
            p2p_criteria = self._parse_p2p_criteria(block)

            # Валидация и исправление цели (активная форма)
            goal = self._fix_goal_active_form(goal, seed.language)
            situation = self._fix_task_situation(situation, input_data, goal, seed.language)
            constraints_or_risk = self._fix_task_risk(constraints_or_risk, situation, goal, seed.language)

            # Валидация и исправление результата (артефакт + локация)
            result, artifact_location = self._fix_result_artifact(result, seed, idx)

            raw_bullets = self._parse_approach_bullets(approach)
            styled_bullets = []
            for b in raw_bullets:
                if not b:
                    continue
                if "```" in b:
                    styled_bullets.append(b.strip())
                else:
                    styled_bullets.append(self.style.rewrite(b.strip(), seed.language))
            bullets = styled_bullets
            bullets = self._summarize_to_150(bullets, seed.language)

            roles = None
            if seed.project_type == "group" and seed.group_size:
                # Генерируем роли в зависимости от размера группы
                if seed.group_size == 2:
                    roles = ["лид", "исполнитель"]
                elif seed.group_size == 3:
                    roles = ["лид", "исполнитель", "рецензент"]
                else:
                    # Для больших групп: лид, несколько исполнителей, рецензент
                    roles = ["лид"] + [f"исполнитель {i+1}" for i in range(seed.group_size - 2)] + ["рецензент"]
                    if len(roles) > seed.group_size:
                        roles = roles[:seed.group_size]

            # Проверяем, нужно ли добавлять CodeTask для этой задачи
            code_tasks_for_task = []
            if self.code_agent and self._is_programming_topic(seed) and CODE_EXAMPLE_CONFIG["enable_code_tasks_in_practice"]:
                # Генерируем CodeTask для этой задачи
                try:
                    code_result = self.code_agent.generate(
                        topic=title,
                        skills=seed.skills or [],
                        seed=seed,
                        context=f"{goal}\n{input_data}"
                    )
                    if code_result and code_result.tasks:
                        # Ограничиваем количество заданий на программирование
                        max_tasks = CODE_EXAMPLE_CONFIG.get("max_code_tasks_per_practice", 3)
                        code_tasks_for_task = code_result.tasks[:max_tasks]
                except Exception as e:
                    import sys
                    print(f"  ⚠️ Ошибка генерации CodeTask для задачи '{title}': {str(e)}", file=sys.stderr, flush=True)

            # Формируем подход с учетом CodeTask
            enhanced_approach = bullets.copy()
            if code_tasks_for_task:
                # Добавляем информацию о заданиях на программирование в подход
                code_tasks_text = "\n".join([
                    f"- {task.title} ({task.difficulty}): {task.hint or 'Используй заготовку кода с TODO комментариями'}"
                    for task in code_tasks_for_task[:2]  # Максимум 2 задания на задачу
                ])
                if code_tasks_text:
                    enhanced_approach.append(f"**Задания на программирование:**\n{code_tasks_text}")

            theory_support = self._infer_theory_support(
                theory_summary,
                title,
                situation,
                constraints_or_risk,
                goal,
                input_data,
                " ".join(enhanced_approach),
            )
            enhanced_approach = self._normalize_approach_bullets(
                enhanced_approach,
                theory_support,
                seed.language,
            )
            covered_outcomes = self._infer_covered_outcomes(
                seed,
                title,
                situation,
                constraints_or_risk,
                goal,
                input_data,
                " ".join(enhanced_approach),
            )
            theory_support = self._infer_theory_support(
                theory_summary,
                title,
                situation,
                constraints_or_risk,
                goal,
                input_data,
                " ".join(enhanced_approach),
            )
            p2p_criteria = self._ensure_p2p_criteria(
                p2p_criteria,
                artifact_location,
                result,
                theory_support,
                seed.language,
            )

            tasks.append(
                PracticeTask(
                    title=title,
                    situation=situation,
                    constraints_or_risk=constraints_or_risk,
                    input_data=self.style.rewrite(input_data, seed.language),
                    goal=self.style.rewrite(goal, seed.language),
                    approach_bullets=enhanced_approach,
                    expected_artifact=self.style.rewrite(result, seed.language),
                    artifact_location=artifact_location,
                    p2p_criteria=p2p_criteria,
                    covered_outcomes=covered_outcomes,
                    theory_support=theory_support,
                    group_roles=roles,
                )
            )
        tasks = self._ensure_task_artifact_contract(tasks, seed, seed.language, artifact_chain_plan)
        tasks, artifact_chain_plan = self.artifact_chain_planner.apply(tasks, seed, artifact_chain_plan)
        self.last_artifact_chain_plan = artifact_chain_plan
        tasks = self._enforce_learning_activity_contract(tasks, seed.language)
        tasks = self._ensure_task_artifact_contract(tasks, seed, seed.language, artifact_chain_plan)
        tasks, artifact_chain_plan = self.artifact_chain_planner.apply(tasks, seed, artifact_chain_plan)
        self.last_artifact_chain_plan = artifact_chain_plan
        tasks = self._ensure_sjm_task_anchors(
            tasks,
            seed,
            seed.language,
            sjm_override=(section_context or {}).get("sjm_context"),
        )
        return PracticeResult(tasks=tasks, bonus_tasks=[])

    def generate_bonus(self, seed: ProjectSeed, n_bonus: int = 1) -> list[PracticeTask]:
        """
        Генерирует бонусные задания.

        Args:
            seed: Входные данные проекта
            n_bonus: Количество бонусных заданий (1-2)

        Returns:
            Список бонусных заданий
        """
        if n_bonus < 1:
            return []

        n_bonus = min(n_bonus, 2)  # Максимум 2 бонусных задания

        system_prompt = self.config.get_prompt("system").format(language=seed.language)
        if self.didactics_context:
            system_prompt = f"{system_prompt}\n\n=== DIDACTICS CONTEXT ===\n{self.didactics_context}"

        # Формируем информацию о репозитории для промпта
        repo_info = ""
        repo_path_template = seed.repo_path_template if not is_generic_repo_path_template(seed.repo_path_template) else ""
        if seed.repo_base_url or repo_path_template:
            repo_info = "\nИнформация о репозитории для результатов:"
            if seed.repo_base_url:
                repo_info += f"\n- Базовый URL: {seed.repo_base_url}"
            if repo_path_template:
                repo_info += f"\n- Шаблон пути: {repo_path_template}"
            repo_info += "\nИспользуй эту информацию при указании локации ожидаемого результата."

        usr = self.config.get_prompt("bonus_template").format(
            n=n_bonus,
            i="{i}",
            required_tools=", ".join(seed.required_tools) if seed.required_tools else "—",
            bonus_wish=seed.bonus_wish or "—",
            project_description=seed.project_description,
            learning_outcomes="; ".join(seed.learning_outcomes),
            skills="; ".join(seed.skills),
            repo_info=repo_info,
        )
        if seed.reference_project_hint and seed.reference_project_hint.strip():
            usr = (
                f"{usr}\n\n=== ЭТАЛОН ИДЕАЛЬНОГО ПРОЕКТА ===\n"
                "Сохраняй уровень и качество эталона, но бонусные задания должны оставаться в рамках текущего проекта.\n\n"
                f"{seed.reference_project_hint.strip()}"
            )
        generation_kwargs = self.llm_kwargs.copy()
        generation_kwargs.setdefault("temperature", 0.2)
        md = self.llm.complete(system=system_prompt, user=usr, **generation_kwargs)

        bonus_tasks: list[PracticeTask] = []
        # Ищем бонусные задачи (могут быть с * или без)
        rx_bonus = re.compile(r"^###\s+Бонусная\s+задача\s+(\d+)\*?\.\s*(.+?)\s*$", re.M)
        indices = [m.start() for m in rx_bonus.finditer(md)] + [len(md)]
        h_matches = list(rx_bonus.finditer(md))

        for idx, h in enumerate(h_matches):
            start = h.end()
            end = indices[idx + 1] if idx + 1 < len(indices) else len(md)
            block = md[start:end].strip()
            title = h.group(2).strip()

            def _extract(label: str) -> str:
                pat = rf"\*\*{label}:?\*\*\s*(.+?)(?=\n\*\*|\Z)"
                m = re.search(pat, block, flags=re.S)
                return m.group(1).strip() if m else ""

            def _extract_any(labels: list[str]) -> str:
                for label in labels:
                    value = _extract(label)
                    if value:
                        return value
                return ""

            public_action = _extract("Что нужно сделать")
            public_result = _extract("Что должно получиться")
            situation = _extract("Ситуация") or _extract_inline_from_public(public_action, "Ситуация")
            constraints_or_risk = _extract_any(["Ограничение / риск", "Ограничение/риск", "Ограничение", "Риск"])
            input_data = _extract("Входные данные") or _extract_inline_from_public(public_action, "Исходные данные")
            goal = _extract("Цель") or _extract_inline_from_public(public_action, "Цель")
            approach = _extract("Подход") or _extract_inline_from_public(public_action, "Подход") or public_action
            result = _extract("Ожидаемый результат") or public_result
            p2p_criteria = self._parse_p2p_criteria(block)

            raw_bullets = self._parse_approach_bullets(approach)
            styled_bullets = []
            for b in raw_bullets:
                if not b:
                    continue
                if "```" in b:
                    styled_bullets.append(b.strip())
                else:
                    styled_bullets.append(self.style.rewrite(b.strip(), seed.language))
            bullets = styled_bullets
            bullets = self._summarize_to_150(bullets, seed.language)
            situation = self._fix_task_situation(situation, input_data, goal, seed.language)
            constraints_or_risk = self._fix_task_risk(constraints_or_risk, situation, goal, seed.language)

            artifact_location = ""
            m_loc = re.search(r"\((?:где найти|where):\s*([^)]+)\)", result, flags=re.I)
            if m_loc:
                artifact_location = m_loc.group(1).strip()
                result = re.sub(r"\s*\((?:где найти|where):\s*([^)]+)\)\s*$", "", result).strip()
            else:
                artifact_location = self._artifact_location_for_task(seed, idx, bonus=True)

            theory_support = self._infer_theory_support(
                "",
                title,
                situation,
                constraints_or_risk,
                goal,
                input_data,
                " ".join(bullets),
            )
            bullets = self._normalize_approach_bullets(bullets, theory_support, seed.language)
            p2p_criteria = self._ensure_p2p_criteria(
                p2p_criteria,
                artifact_location,
                result,
                theory_support,
                seed.language,
            )

            roles = None
            if seed.project_type == "group":
                roles = ["лид", "исполнитель", "рецензент"]

            bonus_tasks.append(
                PracticeTask(
                    title=title,
                    situation=situation,
                    constraints_or_risk=constraints_or_risk,
                    input_data=self.style.rewrite(input_data, seed.language),
                    goal=self.style.rewrite(goal, seed.language),
                    approach_bullets=bullets,
                    expected_artifact=self.style.rewrite(result, seed.language),
                    artifact_location=artifact_location,
                    p2p_criteria=p2p_criteria,
                    covered_outcomes=self._infer_covered_outcomes(seed, title, situation, constraints_or_risk, goal, input_data, " ".join(bullets)),
                    theory_support=theory_support,
                    group_roles=roles,
                )
            )
        return self.finalize_bonus_tasks(bonus_tasks, seed, seed.language)

    def finalize_bonus_tasks(
        self,
        tasks: list[PracticeTask],
        seed: ProjectSeed,
        language: str,
        *,
        sjm_override: str | None = None,
    ) -> list[PracticeTask]:
        """Apply the same task-level contracts to optional bonus tasks."""
        if not tasks:
            return []

        bonus_plan = self.artifact_chain_planner.plan(seed, len(tasks))
        for idx, step in enumerate(bonus_plan.steps, 1):
            step.artifact_location = self._artifact_location_for_task(seed, idx - 1, bonus=True)

        for idx, task in enumerate(tasks, 1):
            canonical_location = self._artifact_location_for_task(seed, idx - 1, bonus=True)
            task.artifact_location = canonical_location
            if task.expected_artifact:
                task.expected_artifact = _RX_ARTIFACT_PATH.sub(canonical_location, task.expected_artifact)

        tasks, bonus_plan = self.artifact_chain_planner.apply(tasks, seed, bonus_plan)
        tasks = self._enforce_learning_activity_contract(tasks, language)
        tasks = self._ensure_task_artifact_contract(tasks, seed, language, bonus_plan)
        tasks, bonus_plan = self.artifact_chain_planner.apply(tasks, seed, bonus_plan)
        tasks = self._ensure_sjm_task_anchors(tasks, seed, language, sjm_override=sjm_override)
        tasks = self._ensure_task_artifact_contract(tasks, seed, language, bonus_plan)
        return tasks
