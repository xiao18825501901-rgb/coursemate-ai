from __future__ import annotations

import hashlib
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
    workflow_file: Path | None = None
    workflow_sha256: str | None = None
    checkpoint: str | None = None
    output_node_id: str | None = None
    input_bindings: tuple[tuple[str, str, str], ...] = ()


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
            workflow_file = (
                path.parent / str(value["workflow_file"])
                if value.get("workflow_file")
                else None
            )
            workflow_sha256 = (
                str(value["workflow_sha256"]) if value.get("workflow_sha256") else None
            )
            if workflow_file is not None:
                if not workflow_file.is_file():
                    raise ValueError("Visual workflow file is missing")
                actual_sha = hashlib.sha256(workflow_file.read_bytes()).hexdigest()
                if actual_sha != workflow_sha256:
                    raise ValueError("Visual workflow SHA-256 does not match registry")
            bindings = tuple(
                (str(name), str(binding["node_id"]), str(binding["input"]))
                for name, binding in sorted((value.get("input_bindings") or {}).items())
            )
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
                    workflow_file=workflow_file,
                    workflow_sha256=workflow_sha256,
                    checkpoint=str(value["checkpoint"]) if value.get("checkpoint") else None,
                    output_node_id=(
                        str(value["output_node_id"]) if value.get("output_node_id") else None
                    ),
                    input_bindings=bindings,
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

    def select_by_id(self, workflow_id: str, version: str) -> Workflow:
        for item in self._workflows:
            if item.enabled and item.workflow_id == workflow_id and item.version == version:
                return item
        raise LookupError(f"No enabled server workflow for {workflow_id}/{version}")
