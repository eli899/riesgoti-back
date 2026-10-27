"""
Adaptador multi-proveedor de LLM con Structured Outputs (Gemini / OpenAI / servidor local compatible con OpenAI).
Sin API key externa configurada opera en modo determinista local (reglas extractivas), y lo declara en
TAREA_IA.proveedor / TAREA_IA.modelo para que la trazabilidad sea explícita.
"""
from typing import Callable, TypeVar

from django.conf import settings
from pydantic import BaseModel

from apps.ai_config.constants import ProveedorLlm
from apps.ai_config.crypto import EnvelopeCryptoService

DETERMINISTIC_PROVIDER = 'DETERMINISTA_LOCAL'
DETERMINISTIC_MODEL = 'reglas-extractivas-v1'
TEMPERATURE = 0.2

SchemaT = TypeVar('SchemaT', bound=BaseModel)


class LLMClient:
    def __init__(self, config):
        self.config = config
        self.provider = getattr(config, 'proveedor_llm', None) or ''
        self.model = getattr(config, 'modelo_llm', None) or ''
        self.endpoint = getattr(config, 'endpoint_base_llm', None)
        cifrada = getattr(config, 'api_key_llm_cifrada', None)
        self._api_key = EnvelopeCryptoService.decrypt_api_key(cifrada) if cifrada else None

    @property
    def is_deterministic(self) -> bool:
        if self.provider == ProveedorLlm.HUGGINGFACE_LOCAL:
            return not self.endpoint
        return self.provider not in (ProveedorLlm.GEMINI, ProveedorLlm.OPENAI) or not self._api_key

    @property
    def provider_label(self) -> str:
        return DETERMINISTIC_PROVIDER if self.is_deterministic else self.provider

    @property
    def model_label(self) -> str:
        return DETERMINISTIC_MODEL if self.is_deterministic else self.model

    def generate(self, *, system: str, user: str, schema: type[SchemaT], fallback: Callable[[], SchemaT]) -> SchemaT:
        """Devuelve una instancia validada de `schema`; en modo determinista ejecuta `fallback`."""
        if self.is_deterministic:
            return fallback()
        if self.provider == ProveedorLlm.GEMINI:
            return self._gemini(system, user, schema)
        return self._openai_compatible(system, user, schema)

    def _gemini(self, system: str, user: str, schema: type[SchemaT]) -> SchemaT:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type='application/json',
                response_schema=schema,
                temperature=TEMPERATURE,
            ),
        )
        parsed = getattr(response, 'parsed', None)
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate_json(response.text)

    def _openai_compatible(self, system: str, user: str, schema: type[SchemaT]) -> SchemaT:
        from openai import OpenAI

        client = OpenAI(
            api_key=self._api_key or 'no-key',
            base_url=self.endpoint or None,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        if self.provider == ProveedorLlm.OPENAI:
            response_format = {
                'type': 'json_schema',
                'json_schema': {'name': schema.__name__, 'schema': schema.model_json_schema()},
            }
        else:  # Servidores locales: modo JSON con el esquema embebido en el prompt.
            response_format = {'type': 'json_object'}
            system = f'{system}\n\nResponde únicamente con JSON válido según este esquema:\n{schema.model_json_schema()}'
        response = client.chat.completions.create(
            model=self.model,
            temperature=TEMPERATURE,
            response_format=response_format,
            messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        )
        return schema.model_validate_json(response.choices[0].message.content)
