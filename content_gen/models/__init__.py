"""Модели данных для генератора контента."""

from .enums import Language, ProjectType
from .flow_state import ProjectBlueprint, ProjectContextBundle, ProjectFlowState
from .phase_results import (
    ContextPhaseResult,
    EvaluationPhaseResult,
    PracticePhaseResult,
    QualityPhaseResult,
    SkeletonPhaseResult,
    StructurePhaseResult,
    TheoryPhaseResult,
    TitleAnnotationPhaseResult,
    TranslationPhaseResult,
)
from .readme_blocks import ReadmeBlock, ReadmeBlockKind
from .readme_document import ReadmeDocument, ReadmeSection
from .result import OrchestratorResult
from .schemas import (
    Annotation,
    IntroSection,
    PracticeTask,
    ProjectContextMeta,
    ProjectSeed,
    ProjectSpec,
    TheoryPart,
)

__all__ = [
    "Language",
    "ProjectType",
    "ProjectSeed",
    "ProjectContextMeta",
    "Annotation",
    "IntroSection",
    "TheoryPart",
    "PracticeTask",
    "ProjectSpec",
    "ProjectBlueprint",
    "ProjectContextBundle",
    "ProjectFlowState",
    "ContextPhaseResult",
    "TitleAnnotationPhaseResult",
    "StructurePhaseResult",
    "SkeletonPhaseResult",
    "TheoryPhaseResult",
    "PracticePhaseResult",
    "QualityPhaseResult",
    "EvaluationPhaseResult",
    "TranslationPhaseResult",
    "ReadmeBlock",
    "ReadmeBlockKind",
    "ReadmeDocument",
    "ReadmeSection",
    "OrchestratorResult",
]
