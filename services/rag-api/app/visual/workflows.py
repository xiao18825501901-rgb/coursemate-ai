from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.visual.spec import Renderer

REGISTRY_PATH = Path(__file__).with_name("workflows") / "registry.example.json"


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    version: str
    renderer_type: Renderer
    provider: str
    enabled: bool
    allowed_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    model_version: str


class WorkflowRegistry:
    def __init__(self, workflows: list[Workflow]) -> None:
        self._workflows = tuple(workflows)
        keys = {(item.workflow_id, item.version) for item in workflows}
        if len(keys) != len(workflows):
            raise ValueError("Workflow registry contains duplicate IDs/versions")

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> WorkflowRegistry:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("registry_version") != "1":
            raise ValueError("Unsupported visual workflow registry version")
        workflows: list[Workflow] = []
        for value in raw.get("workflows", []):
            workflows.append(
                Workflow(
                    workflow_id=str(value["workflow_id"]),
                    version=str(value["version"]),
                    renderer_type=Renderer(value["renderer_type"]),
                    provider=str(value["provider"]),
                    enabled=bool(value["enabled"]),
                    allowed_inputs=tuple(str(item) for item in value["allowed_inputs"]),
                    outputs=tuple(str(item) for item in value["outputs"]),
                    model_version=str(value.get("model_version") or "mock-fixture-v1"),
                )
            )
        return cls(workflows)

    @classmethod
    def default_mock(cls) -> WorkflowRegistry:
        return cls.load()

    def select(self, renderer: Renderer, provider: str) -> Workflow:
        for item in self._workflows:
            if item.enabled and item.renderer_type is renderer and item.provider == provider:
                return item
        raise LookupError(f"No enabled server workflow for {renderer.value}/{provider}")
