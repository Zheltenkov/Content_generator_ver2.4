import json
import shutil
from pathlib import Path

from content_gen.config import loader


def _reset_loader_caches(monkeypatch):
    monkeypatch.setattr(loader, "_prompt_cache", {})
    monkeypatch.setattr(loader, "_agent_config_cache", {})
    monkeypatch.setattr(loader, "_agent_versions", {})


def test_get_agent_config_reads_yaml_and_caches(monkeypatch):
    repo_root = Path(".tmp/test-fixtures/config-loader/repo").resolve()
    shutil.rmtree(repo_root, ignore_errors=True)
    config_root = repo_root / "content_gen" / "config"
    agents_dir = config_root / "agents"
    prompts_dir = repo_root / "prompts"
    agents_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    prompt_file = prompts_dir / "system.txt"
    prompt_file.write_text("System prompt for {language}", encoding="utf-8")

    agent_yaml = agents_dir / "demo.yaml"
    agent_yaml.write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "llm": {"temperature": 0.2},
                "prompts": {
                    "system": {"type": "file", "path": "prompts/system.txt"},
                    "user": {"type": "inline", "value": "Hello {skill}"},
                },
            }
        ),
        encoding="utf-8",
    )

    _reset_loader_caches(monkeypatch)
    monkeypatch.setattr(loader, "REPO_ROOT", repo_root)
    monkeypatch.setattr(loader, "CONFIG_ROOT", config_root)

    cfg1 = loader.get_agent_config("demo")
    cfg2 = loader.get_agent_config("demo")

    assert cfg1 is cfg2  # кеширование
    assert cfg1.version == "9.9.9"
    assert cfg1.get_prompt("system") == "System prompt for {language}"
    assert cfg1.get_prompt("user") == "Hello {skill}"
    assert loader.get_loaded_agent_versions() == {"demo": "9.9.9"}

