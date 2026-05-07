"""
Модуль для работы со structured outputs через Pydantic модели.

Использует OpenAI Structured Outputs как транспортный слой между LLM и Pydantic моделями.
Pydantic остается "истиной" для доменных моделей, structured outputs гарантируют валидный JSON.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..exceptions import LLMAPIError
from .client import LLMClient

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class StructuredLLMClient:
    """
    Клиент для structured outputs с поддержкой Pydantic моделей.
    
    Использует OpenAI Structured Outputs для гарантированного соответствия схеме,
    с fallback на обычный JSON mode для неподдерживаемых моделей.
    """

    # Модели, поддерживающие structured outputs
    SUPPORTED_MODELS = {
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "o1-mini",
        "o1-preview",
        "o1-mini-preview",
    }

    def __init__(self, llm_client: LLMClient):
        """
        Инициализация клиента.
        
        Args:
            llm_client: Базовый LLM клиент
        """
        self.llm = llm_client

    def _supports_structured_outputs(self) -> bool:
        """
        Проверяет, поддерживает ли модель structured outputs.
        
        Returns:
            True если модель поддерживает structured outputs
        """
        model_name = self.llm.model.lower()
        # Проверяем точное совпадение или начало имени модели
        return any(model_name.startswith(supported.lower()) for supported in self.SUPPORTED_MODELS)

    def _prepare_json_schema(self, model_class: type[BaseModel]) -> dict[str, Any]:
        """
        Подготавливает JSON Schema из Pydantic модели для OpenAI.
        
        OpenAI Structured Outputs требует, чтобы для всех объектов было явно указано
        additionalProperties: false.
        
        Args:
            model_class: Pydantic модель
            
        Returns:
            JSON Schema словарь с additionalProperties: false для всех объектов
        """
        schema = model_class.model_json_schema()

        def add_additional_properties(obj: Any) -> Any:
            """
            Рекурсивно добавляет additionalProperties: false для всех объектов в схеме.
            """
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    # Сохраняем $defs и definitions - они нужны для ссылок на вложенные модели
                    # КРИТИЧЕСКИ ВАЖНО: $defs - это словарь определений, его нужно обработать рекурсивно
                    if key in ("$defs", "definitions"):
                        # $defs - это словарь, где ключи - имена моделей, значения - их схемы
                        # Обрабатываем каждое определение рекурсивно
                        if isinstance(value, dict):
                            processed_defs = {}
                            for def_name, def_schema in value.items():
                                processed_defs[def_name] = add_additional_properties(def_schema)
                            result[key] = processed_defs
                        else:
                            result[key] = value
                        continue
                    # Пропускаем только title
                    if key == "title":
                        continue
                    # Пропускаем $ref - это ссылки, их не нужно обрабатывать
                    if key == "$ref":
                        result[key] = value
                        continue
                    # Рекурсивно обрабатываем значение
                    result[key] = add_additional_properties(value)

                # Если это объект (имеет type: "object" или properties), добавляем additionalProperties: false
                # НО НЕ для $defs - это не объекты схемы, а контейнеры определений
                obj_type = obj.get("type")
                has_properties = "properties" in obj

                if (obj_type == "object" or has_properties) and "$defs" not in obj and "definitions" not in obj:
                    result["additionalProperties"] = False
                    # Убеждаемся, что type указан
                    if "type" not in result and has_properties:
                        result["type"] = "object"

                # Обрабатываем anyOf, oneOf, allOf - там могут быть вложенные объекты
                for union_key in ["anyOf", "oneOf", "allOf"]:
                    if union_key in result:
                        result[union_key] = [add_additional_properties(item) for item in result[union_key]]

                return result
            elif isinstance(obj, list):
                return [add_additional_properties(item) for item in obj]
            else:
                return obj

        # Применяем рекурсивную обработку
        cleaned_schema = add_additional_properties(schema)

        # OpenAI Structured Outputs в strict mode требует:
        # ВСЕ поля из properties ДОЛЖНЫ быть в required (даже с default)
        # НО также требуется, чтобы в required НЕ было ключей, которых нет в properties
        properties = cleaned_schema.get("properties", {})
        original_required = cleaned_schema.get("required", [])

        # КРИТИЧЕСКИ ВАЖНО: Проверяем соответствие required и properties
        # 1. Удаляем из required ключи, которых нет в properties
        # 2. Добавляем в required ключи из properties, которых нет в required
        if original_required:
            # Фильтруем required - оставляем только ключи, которые есть в properties
            required_fields = [key for key in original_required if key in properties]
            # Добавляем ключи из properties, которых нет в required
            missing_in_required = [key for key in properties.keys() if key not in required_fields]
            if missing_in_required:
                required_fields.extend(missing_in_required)
                logger.debug(
                    f"Добавлены в required отсутствующие ключи из properties: {missing_in_required}"
                )
            # Логируем, если были удалены лишние ключи из required
            extra_in_required = [key for key in original_required if key not in properties]
            if extra_in_required:
                logger.warning(
                    f"⚠️ Удалены из required ключи, отсутствующие в properties: {extra_in_required} "
                    f"для модели {model_class.__name__}"
                )
        else:
            # Если required нет, создаем из всех properties
            required_fields = list(properties.keys())

        def fix_required_in_defs(defs_dict: dict[str, Any]) -> dict[str, Any]:
            """
            Рекурсивно исправляет required для всех определений в $defs.
            
            OpenAI требует, чтобы все поля из properties были в required,
            даже если у них есть default значения.
            НО также требуется, чтобы в required НЕ было ключей, которых нет в properties.
            """
            fixed_defs = {}
            for def_name, def_schema in defs_dict.items():
                if isinstance(def_schema, dict):
                    fixed_schema = def_schema.copy()
                    # Для всех объектов с properties: все поля должны быть в required
                    if "properties" in fixed_schema:
                        def_properties = fixed_schema["properties"]
                        def_required = fixed_schema.get("required", [])

                        # Фильтруем required - оставляем только ключи из properties
                        filtered_required = [key for key in def_required if key in def_properties]
                        # Добавляем ключи из properties, которых нет в required
                        missing_keys = [key for key in def_properties.keys() if key not in filtered_required]
                        filtered_required.extend(missing_keys)

                        fixed_schema["required"] = filtered_required

                        # Логируем, если были проблемы
                        extra_keys = [key for key in def_required if key not in def_properties]
                        if extra_keys:
                            logger.warning(
                                f"⚠️ В $defs/{def_name} удалены из required ключи, "
                                f"отсутствующие в properties: {extra_keys}"
                            )
                    # Рекурсивно обрабатываем вложенные $defs
                    if "$defs" in fixed_schema:
                        fixed_schema["$defs"] = fix_required_in_defs(fixed_schema["$defs"])
                    fixed_defs[def_name] = fixed_schema
                else:
                    fixed_defs[def_name] = def_schema
            return fixed_defs

        # Собираем финальную схему, включая $defs для вложенных моделей
        final_schema = {
            "type": cleaned_schema.get("type", "object"),
            "properties": properties,
            "required": required_fields,  # ВСЕ поля из properties
            "additionalProperties": False,  # Обязательно для OpenAI
        }

        # КРИТИЧЕСКИ ВАЖНО: Исправляем required для всех вложенных моделей в $defs
        # Проверяем как в cleaned_schema, так и в исходной schema (на случай, если они были потеряны)
        if "$defs" in cleaned_schema:
            final_schema["$defs"] = fix_required_in_defs(cleaned_schema["$defs"])
            logger.debug(f"Включены $defs из cleaned_schema: {list(cleaned_schema['$defs'].keys())}")
        elif "$defs" in schema:
            final_schema["$defs"] = fix_required_in_defs(schema["$defs"])
            logger.debug(f"Включены $defs из исходной schema: {list(schema['$defs'].keys())}")
        elif "definitions" in cleaned_schema:
            final_schema["definitions"] = fix_required_in_defs(cleaned_schema["definitions"])
            logger.debug(f"Включены definitions из cleaned_schema: {list(cleaned_schema['definitions'].keys())}")
        elif "definitions" in schema:
            final_schema["definitions"] = fix_required_in_defs(schema["definitions"])
            logger.debug(f"Включены definitions из исходной schema: {list(schema['definitions'].keys())}")
        else:
            logger.debug(f"$defs не найдены в схеме для {model_class.__name__} (возможно, нет вложенных моделей)")

        logger.debug(
            f"Schema для {model_class.__name__}: "
            f"properties={list(properties.keys())}, "
            f"required={required_fields}"
        )

        # Дополнительная проверка: если в properties есть $ref, но нет $defs, это проблема
        def check_refs_in_properties(props: dict, path: str = ""):
            """Рекурсивно проверяет наличие $ref в properties."""
            for key, value in props.items():
                if isinstance(value, dict):
                    if "$ref" in value:
                        ref = value["$ref"]
                        logger.debug(f"Найдена ссылка $ref в {path}.{key}: {ref}")
                        # Проверяем, что ссылка может быть разрешена
                        if ref.startswith("#/$defs/") and "$defs" not in final_schema:
                            logger.error(f"ОШИБКА: Найдена ссылка {ref}, но $defs отсутствуют в финальной схеме!")
                        elif ref.startswith("#/definitions/") and "definitions" not in final_schema:
                            logger.error(f"ОШИБКА: Найдена ссылка {ref}, но definitions отсутствуют в финальной схеме!")
                    check_refs_in_properties(value, f"{path}.{key}" if path else key)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            check_refs_in_properties(item, f"{path}.{key}[]")

        check_refs_in_properties(properties)

        return final_schema

    def complete_structured(
        self,
        output_model: type[T],
        system: str,
        user: str,
        use_structured_outputs: bool | None = None,
        **kwargs
    ) -> T:
        """
        Выполняет запрос с гарантированным structured output.
        
        Args:
            output_model: Pydantic модель для результата
            system: Системный промпт
            user: Пользовательский промпт
            use_structured_outputs: Принудительно использовать structured outputs (None = автоопределение)
            **kwargs: Дополнительные параметры для LLM (temperature, max_tokens и т.д.)
            
        Returns:
            Валидированный объект Pydantic модели
            
        Raises:
            ValidationError: Если ответ не прошел валидацию Pydantic
            LLMAPIError: Если произошла ошибка при вызове LLM
        """
        # Определяем, использовать ли structured outputs
        if use_structured_outputs is None:
            use_structured_outputs = self._supports_structured_outputs()

        if use_structured_outputs:
            # Используем OpenAI Structured Outputs
            json_schema = self._prepare_json_schema(output_model)

            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__.lower().replace("model", ""),
                    "strict": True,
                    "schema": json_schema,
                }
            }

            logger.debug(
                f"Using structured outputs for model {self.llm.model} with schema {output_model.__name__}"
            )
        else:
            # Fallback на обычный JSON mode
            response_format = "json_object"
            logger.debug(
                f"Using JSON mode fallback for model {self.llm.model} (structured outputs not supported)"
            )

        # Выполняем запрос
        try:
            response = self.llm.complete(
                system=system,
                user=user,
                response_format=response_format,
                **kwargs
            )
        except Exception as e:
            logger.error(f"LLM API error during structured output call: {e}")
            raise LLMAPIError(f"Ошибка при вызове LLM для structured output: {e}") from e

        # Парсим и валидируем через Pydantic
        try:
            # Если ответ уже строка, парсим JSON
            if isinstance(response, str):
                # Убираем возможные markdown code blocks
                response_clean = response.strip()
                if response_clean.startswith("```json"):
                    response_clean = response_clean[7:]
                if response_clean.startswith("```"):
                    response_clean = response_clean[3:]
                if response_clean.endswith("```"):
                    response_clean = response_clean[:-3]
                response_clean = response_clean.strip()

                # Парсим JSON
                data = json.loads(response_clean)
            else:
                # Если ответ уже словарь (не должно быть, но на всякий случай)
                data = response

            # Валидируем через Pydantic
            result = output_model.model_validate(data)

            logger.debug(
                f"Successfully validated structured output for {output_model.__name__}: "
                f"{result.model_dump_json(exclude_none=True)[:200]}..."
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(
                f"JSON decode error for {output_model.__name__}: {e}\n"
                f"Raw response: {response[:500]}..."
            )
            raise ValidationError.from_exception_data(
                output_model.__name__,
                [
                    {
                        "type": "value_error",
                        "loc": ("__root__",),
                        "msg": f"Не удалось распарсить JSON ответ от LLM: {e}",
                        "input": response,
                        "ctx": {"error": f"Не удалось распарсить JSON ответ от LLM: {e}"},
                    }
                ],
            ) from e
        except ValidationError as e:
            logger.error(
                f"Pydantic validation error for {output_model.__name__}: {e}\n"
                f"Raw response: {response[:500]}..."
            )
            # Логируем raw JSON для дебага
            try:
                raw_data = json.loads(response) if isinstance(response, str) else response
                logger.debug(f"Raw JSON data: {json.dumps(raw_data, ensure_ascii=False, indent=2)}")
            except:
                logger.debug(f"Raw response (not JSON): {response[:1000]}")
            raise
