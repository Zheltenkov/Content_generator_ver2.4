"""
Модуль фаз для нового архитектурного подхода.

Разделяет пайплайн на 6 фаз с встроенными проверками:
- Phase 0: Intent & curriculum context
- Phase 1: Каркас (с StructuralPreflight)
- Phase 2: Теория (с TheoryChecks и локальной Regeneration)
- Phase 3: Практика (с PracticeChecks)
- Phase 4: Глобальное качество
- Phase 5: Итоговая оценка
- Phase 6: Перевод
"""

from .phase_0 import phase_0_context
from .phase_1 import phase_1_skeleton, phase_1_structure, phase_1_title_annotation
from .phase_2 import phase_2_theory
from .phase_3 import phase_3_practice
from .phase_4 import phase_4_global_quality
from .phase_6 import phase_6_final_evaluation
from .phase_7 import phase_7_translate

__all__ = [
    "phase_0_context",
    "phase_1_skeleton",
    "phase_1_structure",
    "phase_1_title_annotation",
    "phase_2_theory",
    "phase_3_practice",
    "phase_4_global_quality",
    "phase_6_final_evaluation",
    "phase_7_translate",
]
