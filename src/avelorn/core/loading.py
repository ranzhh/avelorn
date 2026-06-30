"""YAML → Pydantic loading machinery."""

from pathlib import Path

import yaml
from pydantic import BaseModel


def load_yaml[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Load one YAML file and validate it against a model.

    Returns:
        The validated model instance.
    """
    return model.model_validate(yaml.safe_load(path.read_text()))


def load_yaml_dir[ModelT: BaseModel](directory: Path, model: type[ModelT]) -> list[ModelT]:
    """Load every ``*.yaml`` file directly under a directory, sorted by name.

    Returns:
        The validated model instances.
    """
    return [load_yaml(path, model) for path in sorted(directory.glob("*.yaml"))]
