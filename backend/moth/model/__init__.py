"""MOTH Model: an original decoder-only Transformer trained from random init."""

from moth.model.config import PRESETS, MothConfig
from moth.model.transformer import MothModel

__all__ = ["MothConfig", "MothModel", "PRESETS"]
