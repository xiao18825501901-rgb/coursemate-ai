import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

POLICY_VERSION = "v1"
POLICY_ROOT = Path(__file__).parent / "course_policies" / POLICY_VERSION
COURSE_POLICY_FILES = {"cs3481": "CS3481.json"}


class CoursePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=100)
    question_prefix: str | None = Field(default=None, max_length=32)
    applies_to: Literal["comprehension_check_display"]


@lru_cache(maxsize=32)
def course_policy(course_id: str) -> CoursePolicy:
    # The explicit mapping prevents a user-controlled course ID becoming a file path.
    filename = COURSE_POLICY_FILES.get(course_id.casefold(), "default.json")
    return CoursePolicy.model_validate(
        json.loads((POLICY_ROOT / filename).read_text(encoding="utf-8"))
    )
