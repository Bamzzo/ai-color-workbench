"""Document session: state, export gate, AI proposals, and color undo/redo.

No Tk dependency — safe for FastAPI and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ai.provider import Proposal
from baker.params import ColorParams

from .state import AppState, Mode

if TYPE_CHECKING:
    pass

MAX_COLOR_HISTORY = 64


@dataclass
class ExportTicket:
    """One accepted export; removed when the outcome is handled."""

    kind: str
    revision: int
    material: str
    token: int


@dataclass(frozen=True)
class ColorSnapshot:
    """Params + strength + mode fingerprint for undo/redo."""

    params: ColorParams
    strength: float
    mode: Mode
    source_label: str

    @classmethod
    def from_state(cls, state: AppState) -> ColorSnapshot:
        return cls(
            params=state.params,
            strength=float(state.strength),
            mode=state.mode,
            source_label=str(state.source_label),
        )

    def apply_to(self, state: AppState) -> None:
        state.params = self.params
        state.strength = self.strength
        state.mode = self.mode
        state.source_label = self.source_label
        state.dirty = True


@dataclass
class DocumentSession:
    """Per-document business rules formerly embedded in ``ColorApp``."""

    state: AppState = field(default_factory=AppState)
    pending_proposal: Proposal | None = None
    export_tickets: list[ExportTicket] = field(default_factory=list)
    export_seq: int = 0
    batch_active: bool = False
    _color_history: list[ColorSnapshot] = field(default_factory=list)
    _color_history_index: int = 0

    # -- color history -------------------------------------------------
    def reset_color_history(self) -> None:
        self._color_history = [ColorSnapshot.from_state(self.state)]
        self._color_history_index = 0

    def clear_color_history(self) -> None:
        self._color_history = []
        self._color_history_index = 0

    def record_color_history(self) -> None:
        """Call before mutating params/strength/mode from user edits."""
        snap = ColorSnapshot.from_state(self.state)
        if not self._color_history:
            self._color_history = [snap]
            self._color_history_index = 0
            return
        if self._color_history[self._color_history_index] == snap:
            return
        if self._color_history_index < len(self._color_history) - 1:
            self._color_history = self._color_history[: self._color_history_index + 1]
        self._color_history.append(snap)
        self._color_history_index = len(self._color_history) - 1
        if len(self._color_history) > MAX_COLOR_HISTORY:
            overflow = len(self._color_history) - MAX_COLOR_HISTORY
            self._color_history = self._color_history[overflow:]
            self._color_history_index -= overflow

    def can_undo(self) -> bool:
        return self._color_history_index > 0

    def can_redo(self) -> bool:
        return self._color_history_index < len(self._color_history) - 1

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._color_history_index -= 1
        self._color_history[self._color_history_index].apply_to(self.state)
        self.state.bump_color()
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._color_history_index += 1
        self._color_history[self._color_history_index].apply_to(self.state)
        self.state.bump_color()
        return True

    # -- AI proposals --------------------------------------------------
    def set_pending_proposal(self, proposal: Proposal | None) -> None:
        self.pending_proposal = proposal

    def clear_pending_proposal(self) -> None:
        self.pending_proposal = None

    def apply_proposal_to_state(self, proposal: Proposal) -> int:
        self.pending_proposal = None
        self.record_color_history()
        if proposal.source == "ai":
            label = f"AI · {proposal.provider}/{proposal.model}"
        else:
            label = "离线模板"
        self.state.params = proposal.params
        self.state.mode = "params"
        self.state.external_lut = None
        self.state.source_label = label
        self.state.dirty = True
        rev = self.state.bump_color()
        self.record_color_history()
        return rev

    # -- export gate ---------------------------------------------------
    def export_started(self, kind: str, revision: int, material: str = "") -> int:
        self.export_seq += 1
        token = self.export_seq
        self.export_tickets.append(
            ExportTicket(kind, revision, material, token)
        )
        return token

    def export_take(self, token: int | None, kind: str) -> ExportTicket | None:
        if token is not None:
            for index, ticket in enumerate(self.export_tickets):
                if ticket.token == token:
                    return self.export_tickets.pop(index)
        for index, ticket in enumerate(self.export_tickets):
            if ticket.kind == kind:
                return self.export_tickets.pop(index)
        return None

    def export_drop_token(self, token: int) -> None:
        for index, ticket in enumerate(self.export_tickets):
            if ticket.token == token:
                del self.export_tickets[index]
                return

    def outstanding_exports(self, runner_queued: int = 0) -> int:
        return max(len(self.export_tickets), int(runner_queued))

    def export_block_reason(self, runner_queued: int = 0) -> str | None:
        outstanding = self.outstanding_exports(runner_queued)
        if outstanding <= 0:
            return None
        text = "当前素材仍有导出任务正在进行，暂时无法切换。请等待导出完成后再试。"
        if outstanding > 1:
            text = text[:-1] + f"（剩余 {outstanding} 项）。"
        return text

    def batch_blocks_single_asset_work(self) -> bool:
        return self.batch_active


__all__ = [
    "ColorSnapshot",
    "DocumentSession",
    "ExportTicket",
]