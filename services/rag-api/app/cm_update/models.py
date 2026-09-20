from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
from zoneinfo import ZoneInfo

class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class Profile(Input):
    name: str = Field(min_length=1,max_length=50)
    bio: str = Field(default='',max_length=250)
    handle: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{2,29}$')
    language: Literal['auto','zh-CN','en','bilingual']='zh-CN'
    timezone: str='Asia/Hong_Kong'
    discoverable: bool=True
    reply_notify: bool=True
    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,v):
        try: ZoneInfo(v)
        except Exception: raise ValueError('Unknown IANA timezone') from None
        return v

class CourseCreate(Input):
    name: str=Field(min_length=1,max_length=100)
    code: str=Field(default='',max_length=30)
    description: str=Field(default='',max_length=500)
    color: str=Field(default='#38585b',pattern=r'^#[0-9a-fA-F]{6}$')
    requirements: str=Field(default='',max_length=10000)

class Text(Input):
    text: str=Field(min_length=1,max_length=6000)
    request_id: str=Field(min_length=8,max_length=100)

class CommentCreate(Text):
    parent: str|None=None

class MessageCreate(Text):
    recipient: str=Field(min_length=1,max_length=150)

class TaskCreate(Input):
    title: str=Field(min_length=1,max_length=150)
    due_at: datetime
    timezone: str='Asia/Hong_Kong'
    course: str|None=None
    request_id: str=Field(min_length=8,max_length=100)
    @field_validator('due_at')
    @classmethod
    def aware(cls,v):
        if v.tzinfo is None: raise ValueError('Timezone-aware timestamp required')
        return v
    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls,v):
        try: ZoneInfo(v)
        except Exception: raise ValueError('Unknown timezone') from None
        return v

class TaskUpdate(Input):
    title: str|None=Field(default=None,min_length=1,max_length=150)
    due_at: datetime|None=None
    status: Literal['todo','done']|None=None
    version: int=Field(ge=1)
    @field_validator('due_at')
    @classmethod
    def aware(cls,v):
        if v is not None and v.tzinfo is None: raise ValueError('Timezone-aware timestamp required')
        return v

class ConversationCreate(Input):
    course: str
    lane: Literal['teach','problem']
    pair_id: str|None=None
    title: str=Field(default='新对话',min_length=1,max_length=100)

class Rename(Input):
    title: str=Field(min_length=1,max_length=100)

class Layout(Input):
    ratio: float=Field(default=.5,ge=.25,le=.75)
    teach_conversation: str|None=None
    problem_conversation: str|None=None
    active_node: str|None=None
    teach_strength: Literal['medium','high','max']='medium'
    problem_strength: Literal['medium','high','max']='medium'

class ThemePreference(Input):
    theme: Literal['light','dark']

class RunCreate(Text):
    bridge_id: str|None=None
    node_id: str|None=None
    attachment_ids: list[str]=Field(default_factory=list,max_length=4)
    teaching_mode: Literal['normal','thinking']='normal'
    reasoning_strength: Literal['medium','high','max']='medium'

class BridgeCreate(Input):
    problem_message: str
    step: int=Field(ge=1,le=100)
    question: str=Field(min_length=1,max_length=2000)
    node: str|None=None

class CourseUpdate(Input):
    name: str=Field(min_length=1,max_length=100)
    description: str=Field(default='',max_length=500)
    color: str=Field(default='#38585b',pattern=r'^#[0-9a-fA-F]{6}$')
    requirements: str=Field(default='',max_length=10000)

class ReceiptClaim(Input):
    request_id: str=Field(min_length=8,max_length=100)
    text: str=Field(min_length=1,max_length=6000)
    timezone: str=Field(min_length=1,max_length=80)

class ReceiptFinish(Input):
    lease: str=Field(min_length=20,max_length=100)
    status: Literal['completed','failed']
    result: dict=Field(default_factory=dict)

class PairCreate(Input):
    course: str

class PairBind(Input):
    node: str|None=None

class ClassificationCorrection(Input):
    template_id: str=Field(min_length=1,max_length=40)

class VerificationRedeem(Input):
    code: str=Field(pattern=r'^[0-9]{7}$')
    request_id: str=Field(min_length=8,max_length=100)

class VerificationIssue(Input):
    count: int=Field(ge=1,le=100)

class VerificationDisable(Input):
    code_id: str=Field(min_length=8,max_length=100)

class ShareCreate(Input):
    course: str
    recipients: list[str]=Field(min_length=1,max_length=20)
    history_scope: Literal['all','none','selected']='none'
    selected_pair_ids: list[str]=Field(default_factory=list,max_length=50)
    request_id: str=Field(min_length=8,max_length=100)

class ExerciseCreate(Input):
    pair_id: str|None=None
    node: str|None=None
    request_id: str=Field(min_length=8,max_length=100)

class ExplanationCreate(Input):
    request_id: str=Field(min_length=8,max_length=100)

class ExplanationMessage(Text):
    pass
