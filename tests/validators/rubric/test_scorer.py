"""Тесты для RubricScorer."""

from content_gen.models.criteria_models import CriteriaReport
from content_gen.validators.rubric.scorer import RubricScorer


class TestRubricScorer:
    """Тесты для основного класса RubricScorer."""

    def test_init(self, mock_llm_client):
        """Тест инициализации RubricScorer."""
        scorer = RubricScorer(language="ru", llm_client=mock_llm_client)
        assert scorer.lang == "ru"
        assert scorer.llm == mock_llm_client
        assert scorer.rx_h1 is not None
        assert scorer.rx_h2 is not None
        assert scorer.rx_h3 is not None

    def test_score_empty_markdown(self, mock_llm_client):
        """Тест оценки пустого markdown."""
        scorer = RubricScorer(language="ru", llm_client=mock_llm_client)
        report = scorer.score("")

        assert isinstance(report, CriteriaReport)
        assert len(report.items) > 0
        # Большинство критериев должны провалиться
        failed_items = [item for item in report.items if item.score == 0]
        assert len(failed_items) > 0

    def test_score_valid_markdown(self, mock_llm_client, sample_markdown):
        """Тест оценки валидного markdown."""
        scorer = RubricScorer(language="ru", llm_client=mock_llm_client)
        report = scorer.score(sample_markdown)

        assert isinstance(report, CriteriaReport)
        assert len(report.items) > 0
        # Проверяем структуру отчета
        assert hasattr(report, 'total')
        assert hasattr(report, 'max_score')
        assert hasattr(report, 'items')

    def test_score_parses_structure(self, mock_llm_client, sample_markdown):
        """Тест парсинга структуры markdown."""
        scorer = RubricScorer(language="ru", llm_client=mock_llm_client)

        # Проверяем, что регулярные выражения работают
        h1_matches = scorer.rx_h1.findall(sample_markdown)
        h2_matches = scorer.rx_h2.findall(sample_markdown)
        h3_matches = scorer.rx_h3.findall(sample_markdown)

        assert len(h1_matches) > 0
        assert len(h2_matches) > 0
        assert len(h3_matches) > 0

    def test_score_calculates_total(self, mock_llm_client, sample_markdown):
        """Тест расчета общего балла."""
        scorer = RubricScorer(language="ru", llm_client=mock_llm_client)
        report = scorer.score(sample_markdown)

        # Проверяем, что total рассчитан
        assert report.total >= 0
        assert report.max_score > 0
        assert report.total <= report.max_score

