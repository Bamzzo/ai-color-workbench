"""Application state with explicit colour revisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from baker.cube_reader import CubeLut
from baker.params import ColorParams

from .image_io import SourceImage
from .video_io import VideoInfo

Mode = Literal["params", "external_lut"]


@dataclass
class AppState:
    document_id: str = ""
    revision: int = 0
    source: SourceImage | None = None
    preview_image: Image.Image | None = None
    params: ColorParams = field(default_factory=ColorParams.identity)
    strength: float = 1.0
    mode: Mode = "params"
    external_lut: CubeLut | None = None
    saved_params: ColorParams = field(default_factory=ColorParams.identity)
    split_t: float = 1.0
    show_split: bool = False
    hold_original: bool = False
    zoom: float = 0.0  # 0 = fit
    pan_x: float = 0.0
    pan_y: float = 0.0
    last_completed_revision: int = -1
    busy_revision: int | None = None
    preview_is_scaled: bool = False
    source_label: str = "手动"
    last_error: str = ""
    dirty: bool = False
    # Video mode: the graded source is one extracted frame of this clip.
    video: VideoInfo | None = None
    video_time: float = 0.0

    def new_document(self, source: SourceImage) -> None:
        self.document_id = f"doc-{uuid.uuid4().hex[:12]}"
        self.revision += 1
        self.source = source
        self.preview_image = None
        self.params = ColorParams.identity()
        self.saved_params = ColorParams.identity()
        self.strength = 1.0
        self.mode = "params"
        self.external_lut = None
        self.split_t = 1.0
        self.show_split = False
        self.hold_original = False
        self.zoom = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.last_completed_revision = -1
        self.busy_revision = None
        self.source_label = "手动"
        self.last_error = ""
        self.dirty = False
        self.video = None
        self.video_time = 0.0

    def bump_color(self) -> int:
        self.revision += 1
        return self.revision

    def set_params(self, params: ColorParams, label: str = "手动") -> int:
        self.params = params
        self.source_label = label
        self.mode = "params"
        self.dirty = True
        return self.bump_color()

    def set_strength(self, strength: float) -> int:
        self.strength = max(0.0, min(1.0, float(strength)))
        self.dirty = True
        return self.bump_color()

    def import_external_lut(self, lut: CubeLut) -> int:
        self.saved_params = self.params
        self.external_lut = lut
        self.mode = "external_lut"
        self.source_label = "外部 LUT"
        self.dirty = True
        return self.bump_color()

    def return_to_params(self) -> int:
        self.mode = "params"
        self.external_lut = None
        self.source_label = "参数调色"
        self.dirty = True
        return self.bump_color()

    @property
    def has_image(self) -> bool:
        return self.source is not None

    @property
    def source_path(self) -> Path | None:
        return self.source.path if self.source else None
