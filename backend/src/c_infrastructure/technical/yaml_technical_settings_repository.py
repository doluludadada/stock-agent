# backend/src/c_infrastructure/technical/yaml_technical_settings_repository.py

import os
import tempfile
from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from c_infrastructure.technical.technical_settings_schema import TechnicalSettingsSchema


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that rejects a repeated key, such as two strategies with one ID. PyYAML keeps the last one silently."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        keys: set[Hashable] = set()

        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)

            if not isinstance(key, Hashable):
                continue

            if key in keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark, f"found duplicate key {key!r}", key_node.start_mark
                )

            keys.add(key)

        return super().construct_mapping(node, deep=deep)


class YamlTechnicalSettingsRepository(ITechnicalSettingsRepository):
    """
    YAML-backed technical settings repository.

    The tracked template (config/technical.yaml) is never written. `save` writes
    technical.local.yaml next to it, and `load` prefers that file. Deleting it
    resets the settings to the template.

    Settings are loaded on every workflow start so the next workflow always
    receives the latest saved configuration.
    """

    def __init__(self, template_path: Path) -> None:
        self._template_path = template_path
        self._saved_path = template_path.with_name(f"{template_path.stem}.local{template_path.suffix}")

    async def load(self) -> TechnicalSettings:
        settings_path = self._saved_path if self._saved_path.exists() else self._template_path

        try:
            with settings_path.open(encoding="utf-8") as settings_file:
                raw_settings = yaml.load(settings_file, Loader=UniqueKeyLoader) or {}

            return TechnicalSettingsSchema.model_validate(raw_settings).to_domain()
        except (yaml.YAMLError, ValidationError) as error:
            error.add_note(f"Technical settings file: {settings_path}")
            raise

    async def save(self, settings: TechnicalSettings) -> None:
        document = TechnicalSettingsSchema.from_domain(settings).to_document()
        content = f"# Saved technical settings. Delete this file to use {self._template_path.name} again.\n\n" + yaml.safe_dump(
            document, allow_unicode=True, sort_keys=False
        )

        descriptor, temporary_name = tempfile.mkstemp(dir=self._saved_path.parent, prefix=f".{self._saved_path.name}.", suffix=".tmp")
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            temporary_path.replace(self._saved_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    async def reset(self) -> None:
        self._saved_path.unlink(missing_ok=True)
