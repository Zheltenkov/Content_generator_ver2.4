"""
content_gen/agents/toc.py

Агент генерации оглавления.

Извлекает заголовки из markdown и формирует TOC (Table of Contents).
Вставляет оглавление после аннотации в структуре документа.
"""

import re
from dataclasses import dataclass


@dataclass
class TOCResult:
    """Результат генерации оглавления."""

    toc_md: str


class TOCAgent:
    """Генерирует оглавление по фактическим заголовкам."""

    def run(self, input_data: dict[str, str]) -> dict[str, TOCResult | str]:
        """Совместимый адаптер для старого graph/run-контракта."""
        op = input_data.get("op", "build")
        if op == "inject":
            result = self.inject(input_data.get("md", ""), input_data.get("toc_md", ""))
        else:
            result = self.build(input_data.get("md", ""), input_data.get("language", "ru"))
        return {"result": result}

    def build(self, md: str, language: str = "ru") -> TOCResult:
        """
        Строит оглавление из заголовков H2/H3.

        Args:
            md: Markdown документ
            language: Язык проекта

        Returns:
            TOCResult с оглавлением
        """
        lines = md.splitlines()
        items: list[str] = []
        for ln in lines:
            if ln.startswith("## "):
                title = ln[3:].strip()
                if "содержание" in title.lower() or "content" in title.lower() or "мазмун" in title.lower():
                    continue
                anchor = (
                    "#"
                    + re.sub(r"[^\w\- ]+", "", title, flags=re.U).strip().lower().replace(" ", "-")
                )
                items.append(f"- [{title}]({anchor})")
            elif ln.startswith("### "):
                title = ln[4:].strip()
                anchor = (
                    "#"
                    + re.sub(r"[^\w\- ]+", "", title, flags=re.U).strip().lower().replace(" ", "-")
                )
                items.append(f"  - [{title}]({anchor})")
        toc = "\n".join(items) if items else "- (появится после добавления разделов)"
        return TOCResult(toc_md=toc)

    def inject(self, md: str, toc_md: str) -> str:
        """
        Вставляет оглавление вместо плейсхолдера.

        Args:
            md: Исходный Markdown
            toc_md: Сгенерированное оглавление

        Returns:
            Обновлённый Markdown
        """
        import sys
        md_before = md
        # Более точное регулярное выражение - не жадное, останавливается на следующей строке
        result = re.sub(
            r"(##\s+(Содержание|Content|Мазмун)\s*\n)\s*<!-- TOC_PLACEHOLDER -->\s*\n",
            r"\1" + toc_md + "\n\n",
            md,
            flags=re.MULTILINE,  # Используем MULTILINE вместо DOTALL, чтобы . не захватывал \n
        )
        if len(result) < len(md_before):
            print(f"  ⚠️  TOC.inject: markdown стал короче! Было: {len(md_before)}, Стало: {len(result)}", file=sys.stderr, flush=True)
            print("     Паттерн: (##\\s+(Содержание|Content|Мазмун)\\s*\\n)\\s*<!-- TOC_PLACEHOLDER -->\\s*\\n", file=sys.stderr, flush=True)
        return result
