from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.errors import ApiError
from app.learning.workspaces import join_course


def test_automatic_map_metering_workspaces_do_not_consume_user_quota(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "rag.sqlite3",
        upload_dir=tmp_path / "uploads",
        app_env="test",
        v3_enabled=True,
    )
    database = Database(settings)
    database.initialize()
    owner = "user-a"
    with database.connect() as connection:
        for index in range(2):
            course_id = f"campus-course-{index}"
            corpus_id = f"akm-corpus-{index}"
            connection.execute(
                "INSERT INTO courses(id,name,owner_user_id,course_type,visibility) "
                "VALUES(?,?,?,'user','private')",
                (corpus_id, "Automatic knowledge-map metering workspace", owner),
            )
            connection.execute(
                "INSERT INTO courses(id,name,course_type,visibility) "
                "VALUES(?,?,'official','public')",
                (course_id, f"Campus {index}"),
            )
            connection.execute(
                "INSERT INTO learning_workspaces(id,owner_user_id,course_id,private_course_id) "
                "VALUES(?,?,?,?)",
                (f"akm-workspace-{index}", owner, course_id, corpus_id),
            )
        for course_id in ("private-one", "private-two"):
            connection.execute(
                "INSERT INTO courses(id,name,owner_user_id,course_type,visibility) "
                "VALUES(?,?,?,'user','private')",
                (course_id, course_id, owner),
            )

    created = join_course(database, "private-one", owner, 1)
    assert created["course_id"] == "private-one"

    with pytest.raises(ApiError) as caught:
        join_course(database, "private-two", owner, 1)
    assert caught.value.status_code == 429
    assert caught.value.code == "WORKSPACE_QUOTA"
