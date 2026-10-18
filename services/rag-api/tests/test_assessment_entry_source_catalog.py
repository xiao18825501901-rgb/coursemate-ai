from test_assessment_point_sources import seeded
from test_learning_workspace import client_at

from app.learning.assessment_entry_source_catalog import AssessmentEntrySourceCatalogReader
from app.learning.assessment_point_configuration import AssessmentPointPolicyService
from app.learning.assessment_point_sources import freeze_point_sources
from app.learning.deterministic_graph_point_catalog import DeterministicGraphPointCatalogReader


def source_at(tmp_path):
    context = client_at(tmp_path)
    client = context.__enter__()
    workspace, node, _document, _chunk = seeded(client)
    source = freeze_point_sources(
        client.app.state.database,
        workspace_id=workspace["id"],
        owner="a",
        node_id=node["id"],
    )
    return context, client.app.state.database, source


def test_source_bound_teaching_targets_produce_dynamic_k_without_method_qualification(
    tmp_path,
):
    context, _database, source = source_at(tmp_path)
    reader = AssessmentEntrySourceCatalogReader(
        specialized=DeterministicGraphPointCatalogReader()
    )

    try:
        result = reader.read_with_targets_for(source, "en")
    finally:
        context.__exit__(None, None, None)

    assert result is not None
    catalog, targets = result
    assert catalog.validation_receipt_id.startswith("source-bound:")
    assert len(catalog.points) == len(source.targets)
    assert set(targets.values()) == {
        (target.objective_id,) for target in source.targets
    }

    setup = AssessmentPointPolicyService(reader).setup(source, "en")
    assert setup["status"] == "READY"
    assert setup["minimum_questions"] == len(source.targets)
    assert setup["maximum_questions"] == len(source.targets) * 2


def test_source_catalog_deduplicates_only_same_server_objective_identity(tmp_path):
    context, _database, source = source_at(tmp_path)
    duplicate = source.targets[0].model_copy(deep=True)
    duplicated_source = source.model_copy(
        update={"targets": [source.targets[0], duplicate]}, deep=True
    )

    try:
        catalog, targets = AssessmentEntrySourceCatalogReader().read_with_targets_for(
            duplicated_source, "en"
        )
    finally:
        context.__exit__(None, None, None)

    assert len(catalog.points) == 1
    assert list(targets.values()) == [(source.targets[0].objective_id,)]


def test_source_catalog_does_not_consult_historical_model_request_ledger(tmp_path):
    context, database, source = source_at(tmp_path)
    try:
        # A source projection has no model-ledger dependency.  Prove that by
        # making any accidental ledger read fail loudly.
        original = database.connect

        def forbidden_connect():
            raise AssertionError("source catalog consulted the historical request ledger")

        database.connect = forbidden_connect
        result = AssessmentEntrySourceCatalogReader().read_with_targets_for(source, "en")
        database.connect = original
        assert result is not None
    finally:
        context.__exit__(None, None, None)
