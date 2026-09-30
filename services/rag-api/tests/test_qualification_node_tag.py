"""Family tags must be unique per node, or independence is overstated.

A qualification's whole weight rests on the number of *independent* negative
families, and a family id is built from a tag derived from the node id.  Deriving
that tag by stripping one known prefix collapses every `official-node-*` to the
same tag, so families from different official nodes share an id and are counted
once.  That is a silent overstatement of the sample, which is the one number the
qualification admission rules are built on.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "run_hybrid_qualification.py"


def _module():
    specification = importlib.util.spec_from_file_location("qual_runner", SCRIPT)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    sys.path.insert(0, str(SCRIPTS.parent))
    specification.loader.exec_module(module)
    return module


def test_official_nodes_get_distinct_tags() -> None:
    module = _module()
    nodes = [
        "official-node-8f5b8ccbd49351c5e65e4945",
        "official-node-8c90a44fc79aa08570379305",
        "official-node-f6a37bd1c753b214ddd314ba",
        "official-node-199a19b6d003154191de6fa4",
    ]
    tags = [module._node_tag(node) for node in nodes]
    assert len(set(tags)) == len(nodes)
    # The prefix-stripping form collapsed all four onto one tag.
    assert len({n.replace("auto-node-", "")[:8] for n in nodes}) == 1


def test_auto_node_tags_are_unchanged_from_earlier_runs() -> None:
    """Earlier results are only comparable if the auto-node tags did not move."""
    module = _module()
    assert module._node_tag("auto-node-94cdec4e3954b945d1eeb45467c6") == "94cdec4e"
    assert module._node_tag("auto-node-b0c2a977001a1f5546d521c3c0de") == "b0c2a977"
