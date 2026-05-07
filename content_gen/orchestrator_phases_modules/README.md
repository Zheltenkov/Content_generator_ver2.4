# Orchestrator phases

Функции `phase_0` … `phase_7` в каталоге `phases/` — основной **последовательный** пайплайн генерации README (`OrchestratorPhases`).

## Контракт вызовов

- **Агенты и LLM-фасады** (генерация, регенерация, перевод, рубрика в фазе 6): предпочтительно `agent.run({...})` согласно [Migration Note в docs/AGENTS.md](../../docs/AGENTS.md).
- **Валидаторы** (`TheoryChecks`, `PracticeChecks`, `StructuralPreflight`, markdown-валидаторы): доменные методы `check` / `validate_*` — отдельный слой от агентов, `run()` не требуется.
- **Редакторы контента** (`ContentEditor`, `TheoryEnhancementAgent.enhance` и т.п.): вызовы специализированных методов; это не унифицированный `run()`, чтобы не размывать смысл API.

Точка входа: `content_gen/orchestrator_phases.py` (сборка оркестратора и вызов фаз).
