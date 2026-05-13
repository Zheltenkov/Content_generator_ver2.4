import io

from api.services.reverse_extraction_service import (
    ReverseExtractionCommand,
    ReverseExtractionService,
    build_excel_filename,
)


class _FakeOrchestrator:
    def __init__(self, _llm) -> None:
        pass

    def extract_from_readme(self, readme_text: str):
        assert readme_text == "# README"
        return io.BytesIO(b"xlsx-bytes"), {
            "extracted_fields": {
                "final_mapping": {
                    "title_seed": "Публичные выступления: intro",
                }
            }
        }


def test_reverse_extraction_service_caches_excel_for_download() -> None:
    service = ReverseExtractionService(
        llm_factory=lambda: object(),
        orchestrator_factory=_FakeOrchestrator,
    )

    result = service.extract_from_readme(
        ReverseExtractionCommand(
            request_id="req_1",
            user_id="user_1",
            readme_text="# README",
        )
    )
    download = service.get_download(result.excel_file_id)

    assert result.status == "completed"
    assert download is not None
    assert download.excel_bytes == b"xlsx-bytes"
    assert download.filename == "Publichnye_vystupleniya_intro_spec.xlsx"


def test_build_excel_filename_returns_safe_ascii_name() -> None:
    assert build_excel_filename("Риски проекта: план/оценка?") == "Riski_proekta_plan_otsenka_spec.xlsx"
