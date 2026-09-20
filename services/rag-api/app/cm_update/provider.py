"""Qwen teaching engine.

teaching_mode contract:
  normal   — one direct model call (course-faithful answer for the teach lane,
             exam-style stepped answer for the problem lane). No plan stage.
  thinking — two-stage: (1) plan: the selected professional template (or the
             OTHER template) + course context -> a full natural-language
             teaching prompt; (2) work: that exact prompt -> visible teaching.
The plan text is an internal artifact: it is stored for audit but is never
returned to users (the API layer whitelists run fields).

Native model "reasoning" parameters are deliberately NOT conflated with the
product's teaching_mode: enable_thinking stays off; the two-stage flow is the
product feature and is recorded separately from any API-level reasoning flags.
"""
import json
from pathlib import Path
from typing import AsyncIterator
import httpx
from .sse import events
from . import templates
from .budget import OperationEstimate, estimate_operation_cost
from .exercise_contract import EXERCISE_RESPONSE_FORMAT

class ProviderError(Exception):
    pass

TEACH_DIRECT_INSTRUCTION = (
    '你是 CourseMate 教师。直接、简洁地回答学生当前的问题，'
    '保留中文解释与英文术语，紧扣课程资料，引用材料时使用 [S1] 等标记。'
    '不要生成十部分长课，不要输出教学计划或内部 Prompt，不要暴露思维链。'
    '没有工具权限，不要声称修改了数据库、分数或发布状态。'
)

class QwenProvider:
    def __init__(self, settings, transport=None):
        self.cfg=settings
        self.transport=transport
        self.calls=[]

    # ------------------------------------------------------------------ teach

    def planner_messages(self, course: dict, text: str, profile: dict, sources: list, history: list, lane: str, bridge=None, spec_items=None, template_id: str = 'OTHER'):
        """Stage-1 plan call. The selected professional template body is the
        planning base; the plan-writer instruction (internal role) wraps it.
        """
        template_body = templates.template_body(template_id) or templates.template_body('OTHER')
        instruction = templates.plan_writer_instruction() + '\n\n【选定模板全文】\n' + template_body
        payload={'course':course.get('name',''),'code':course.get('code',''),'mode':lane,
            'template_id':template_id,'student_preferences':profile,
            'course_requirements':course.get('requirements',''),'student_question':text,
            'materials':sources,'recent_conversation':history[-12:],'problem_bridge':bridge,
            'spec_requirements':spec_items or []}
        return [{'role':'system','content':instruction},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]

    def direct_messages(self, course: dict, text: str, profile: dict, sources: list, history: list, lane: str, bridge=None):
        """Single-stage normal-mode call. Problem lane uses the owner's 题目
        Word prompt; the teach lane uses the compact course-faithful
        instruction. No professional template, no plan."""
        payload={'question':text,'course_materials':sources,'bridge':bridge,
                 'language':profile.get('language','zh-CN')}
        if lane=='problem':
            instruction=templates.problem_prompt()
        else:
            instruction=TEACH_DIRECT_INSTRUCTION
        messages=[{'role':'system','content':instruction}]
        messages.extend({'role':x['role'],'content':x['text'][:10000]} for x in history[-12:] if x['role'] in {'user','assistant'})
        messages.append({'role':'user','content':json.dumps(payload,ensure_ascii=False)})
        return messages

    def work_messages(self, prompt: str, course: dict, text: str, sources: list, history: list, bridge=None):
        """Stage-2 work call: executes the exact plan text from stage 1."""
        instruction=('你是 CourseMate 教师。执行下面由千问生成的教学 Prompt，给出可核验的教学解释，'
                     '不要暴露内部思维链。只使用提供的材料引用标记 [S1] 等；无材料支持时区分补充理解。'
                     '没有工具权限，不要声称修改了数据库、分数或发布状态。\n\n'+prompt)
        messages=[{'role':'system','content':instruction}]
        messages.extend({'role':x['role'],'content':x['text'][:10000]} for x in history[-12:] if x['role'] in {'user','assistant'})
        messages.append({'role':'user','content':json.dumps({'question':text,'course_materials':sources,'bridge':bridge},ensure_ascii=False)})
        return messages

    # ------------------------------------------------- exercise / explanation

    def exercise_messages(self, course: dict, node: dict | None, profile: dict, sources: list):
        """做一题: generate ONE diagnostic question for the target node, and the
        standard answer. The answer is prepared server-side and never streamed;
        the client only receives the question."""
        instruction=templates.exercise_prompt()+'\n\n'+templates.exercise_runtime_contract()
        payload={'course':course.get('name',''),'code':course.get('code',''),
                 'target_node':(node or {}).get('title','') if node else '',
                 'node_context':node or None,'course_materials':sources,
                 'language':profile.get('language','zh-CN')}
        return [{'role':'system','content':instruction},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]

    def explanation_messages(self, course: dict, question_text: str, answer_context: str, step_text: str, profile: dict, sources: list):
        """详解: explain only the requested step of a concrete problem."""
        instruction=templates.explanation_prompt()
        payload={'course':course.get('name',''),'code':course.get('code',''),
                 'problem':question_text,'answer_context':answer_context,'step':step_text,
                 'course_materials':sources,'language':profile.get('language','zh-CN')}
        return [{'role':'system','content':instruction},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]

    # ----------------------------------------------------------------- stream

    def attach_images(self, messages: list, images: list) -> None:
        """Images were authorized/read server-side; data URLs are never persisted or logged."""
        if not images:
            return
        content=messages[-1]['content']
        if self.cfg.qwen_protocol=='responses':
            parts=[{'type':'input_text','text':content}]
            parts.extend({'type':'input_image','image_url':im['data_url'],
                          'max_pixels':self.cfg.image_max_pixels} for im in images)
        else:
            parts=[{'type':'text','text':content}]
            parts.extend({'type':'image_url','image_url':{'url':im['data_url']},
                          'max_pixels':self.cfg.image_max_pixels} for im in images)
        messages[-1]['content']=parts

    def _estimate(self, stages: list[dict]) -> OperationEstimate:
        return estimate_operation_cost(
            stages=stages,
            input_usd_per_million=self.cfg.operation_input_usd_per_million,
            output_usd_per_million=self.cfg.operation_output_usd_per_million,
            # Qwen3.8 visual inputs are billed as input tokens. The provider
            # request carries this same maximum pixel setting, so the estimate
            # reserves ceil(max_pixels / 32 / 32) + two visual delimiters.
            image_tokens_per_input=(self.cfg.image_max_pixels + 1023) // 1024 + 2,
        )

    def _with_estimated_images(self, messages: list, attachments: list | None) -> list:
        # Message builders return fresh objects. Do not JSON-copy multi-megabyte
        # base64 attachments merely to count them: the estimator needs the same
        # request shape and image count, not the image bytes themselves.
        copied = [dict(message) for message in messages]
        if not attachments:
            return copied
        content = copied[-1]['content']
        if self.cfg.qwen_protocol == 'responses':
            parts = [{'type': 'input_text', 'text': content}]
            parts.extend({'type': 'input_image', 'image_url': '',
                          'max_pixels': self.cfg.image_max_pixels} for _ in attachments)
        else:
            parts = [{'type': 'text', 'text': content}]
            parts.extend({'type': 'image_url', 'image_url': {'url': ''},
                          'max_pixels': self.cfg.image_max_pixels} for _ in attachments)
        copied[-1]['content'] = parts
        return copied

    def estimate_generation(self, course, text, profile, sources, history, lane, bridge=None, *, attachments=None, spec_items=None, teaching_mode='normal', template_id='OTHER') -> OperationEstimate:
        if teaching_mode == 'normal':
            return self._estimate([{
                'name': 'answer',
                'messages': self._with_estimated_images(
                    self.direct_messages(course, text, profile, sources, history, lane, bridge), attachments
                ),
                'max_output_tokens': self.cfg.answer_tokens,
            }])
        planner = self._with_estimated_images(
            self.planner_messages(course, text, profile, sources, history, lane, bridge, spec_items, template_id),
            attachments,
        )
        # The second request receives the complete first-stage prompt. Reserve
        # its configured maximum as server-owned input, not a guessed response.
        work = self._with_estimated_images(
            self.work_messages('', course, text, sources, history, bridge), attachments
        )
        return self._estimate([
            {'name': 'planner', 'messages': planner, 'max_output_tokens': self.cfg.prompt_tokens},
            {'name': 'teacher', 'messages': work, 'extra_input_tokens': self.cfg.prompt_tokens,
             'max_output_tokens': self.cfg.answer_tokens},
        ])

    def estimate_exercise(self, course, node, profile, sources) -> OperationEstimate:
        return self._estimate([{
            'name': 'exercise',
            'messages': self.exercise_messages(course, node, profile, sources),
            'max_output_tokens': self.cfg.answer_tokens,
        }])

    def estimate_explanation(self, course, question_text, answer_context, step_text, profile, sources) -> OperationEstimate:
        return self._estimate([{
            'name': 'explanation',
            'messages': self.explanation_messages(
                course, question_text, answer_context, step_text, profile, sources
            ),
            'max_output_tokens': self.cfg.answer_tokens,
        }])

    def classification_messages(self, bundle: dict) -> list[dict]:
        """Build the one bounded automatic-classification request.

        Keeping this builder shared by the estimator and caller prevents a
        later classification prompt change from silently escaping preflight
        accounting.
        """
        instruction = (Path(__file__).parent / 'prompts' / 'CLASSIFICATION_INSTRUCTION_V1.txt').read_text(encoding='utf-8')
        return [
            {'role': 'system', 'content': instruction},
            {'role': 'user', 'content': json.dumps(bundle, ensure_ascii=False)},
        ]

    def estimate_classification(self, bundle: dict) -> OperationEstimate:
        return self._estimate([{
            'name': 'classification',
            'messages': self.classification_messages(bundle),
            'max_output_tokens': min(self.cfg.prompt_tokens, 1200),
        }])

    async def stream(self, messages: list, tokens: int, *, response_format: dict | None = None) -> AsyncIterator[dict]:
        cfg=self.cfg
        if not cfg.allow_billable: raise ProviderError('BILLING_NOT_AUTHORIZED')
        # Alibaba documents response_format/json_schema on its OpenAI-compatible
        # Chat Completions endpoint.  Exercise V2 therefore uses that supported
        # endpoint even when ordinary teaching is configured for Responses.
        protocol='chat_completions' if response_format is not None else cfg.qwen_protocol
        endpoint=cfg.qwen_base_url.rstrip('/')+('/responses' if protocol=='responses' else '/chat/completions')
        if protocol=='responses':
            body={'model':cfg.qwen_model,'input':messages,'stream':True,'max_output_tokens':tokens}
        else:
            body={'model':cfg.qwen_model,'messages':messages,'stream':True,'max_tokens':tokens,
                  'enable_thinking':False,'stream_options':{'include_usage':True}}
            if response_format is not None: body['response_format']=response_format
        self.calls.append({'model':cfg.qwen_model,'stage_tokens':tokens,'protocol':protocol,
                           'structured':response_format is not None})
        # Zero implicit retries, no credential echo in logs or public errors.
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.timeout,connect=12),transport=self.transport,follow_redirects=False) as client:
                async with client.stream('POST',endpoint,headers={'Authorization':'Bearer '+cfg.qwen_key},json=body) as response:
                    if response.status_code!=200: raise ProviderError('PROVIDER_HTTP_'+str(response.status_code))
                    finished=False
                    async for event_type, raw in events(response.aiter_lines()):
                        if raw.strip()=='[DONE]':
                            if not finished:
                                raise ProviderError('DISCONNECTED_PROVIDER_STREAM')
                            break
                        try:
                            data=json.loads(raw)
                        except json.JSONDecodeError:
                            raise ProviderError('INVALID_PROVIDER_STREAM') from None
                        if not isinstance(data,dict) or data.get('error'):
                            raise ProviderError('INVALID_PROVIDER_RESPONSE')
                        if protocol=='responses':
                            kind=data.get('type',event_type)
                            if kind=='response.output_text.delta':
                                value=data.get('delta','')
                                if not isinstance(value,str): raise ProviderError('INVALID_PROVIDER_STREAM')
                                if value: yield {'text':value}
                            if kind=='response.completed':
                                status=data.get('response',{}).get('status','completed')
                                if status!='completed': raise ProviderError('INCOMPLETE_PROVIDER_RESPONSE')
                                finished=True
                                yield {'usage':data.get('response',{}).get('usage',{})}
                            if kind in {'response.failed','response.incomplete','error'}:
                                raise ProviderError('INCOMPLETE_PROVIDER_RESPONSE')
                        else:
                            choices=data.get('choices',[])
                            if not isinstance(choices,list): raise ProviderError('INVALID_PROVIDER_STREAM')
                            for choice in choices:
                                if not isinstance(choice,dict): raise ProviderError('INVALID_PROVIDER_STREAM')
                                delta=choice.get('delta',{}).get('content')
                                if delta:
                                    if not isinstance(delta,str): raise ProviderError('INVALID_PROVIDER_STREAM')
                                    yield {'text':delta}
                                reason=choice.get('finish_reason')
                                if reason is not None and reason!='stop':
                                    raise ProviderError('INCOMPLETE_PROVIDER_RESPONSE')
                                if reason=='stop': finished=True
                            if data.get('usage'): yield {'usage':data['usage']}
                    if not finished: raise ProviderError('DISCONNECTED_PROVIDER_STREAM')
        except ValueError:
            raise ProviderError('INVALID_PROVIDER_STREAM') from None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            raise ProviderError('PROVIDER_TIMEOUT_OR_NETWORK') from None

    # ------------------------------------------------------------- generators

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, *, attachments=None, spec_items=None, teaching_mode='normal', template_id='OTHER'):
        """Chat teach/problem generation. teaching_mode selects the contract:
        normal = single direct call; thinking = plan (template-based) -> work."""
        if teaching_mode=='normal':
            yield {'kind':'status','status':'generating','label':'正在输出中'}
            messages=self.direct_messages(course,text,profile,sources,history,lane,bridge)
            self.attach_images(messages, attachments or [])
            async for item in self.stream(messages,self.cfg.answer_tokens):
                if 'text' in item: yield {'kind':'delta','text':item['text']}
                if 'usage' in item: yield {'kind':'usage','stage':'answer','value':item['usage']}
            return
        yield {'kind':'status','status':'planning','label':'正在思考中'}
        prompt=''
        planner=self.planner_messages(course,text,profile,sources,history,lane,bridge,spec_items,template_id)
        self.attach_images(planner, attachments or [])
        async for item in self.stream(planner,self.cfg.prompt_tokens):
            if 'text' in item: prompt+=item['text']
            if 'usage' in item: yield {'kind':'usage','stage':'prompt','value':item['usage']}
            if len(prompt)>24000: raise ProviderError('PROMPT_TOO_LONG')
        if len(prompt.strip())<30: raise ProviderError('EMPTY_GENERATED_PROMPT')
        yield {'kind':'prompt','text':prompt}
        yield {'kind':'status','status':'generating','label':'正在输出中'}
        messages=self.work_messages(prompt,course,text,sources,history,bridge)
        self.attach_images(messages, attachments or [])
        async for item in self.stream(messages,self.cfg.answer_tokens):
            if 'text' in item: yield {'kind':'delta','text':item['text']}
            if 'usage' in item: yield {'kind':'usage','stage':'answer','value':item['usage']}

    async def generate_exercise(self, course, node, profile, sources, *, target_label=''):
        """One structured call produces a public question and private answer.

        No model text is exposed as a delta: the API validates the complete
        object first and publishes only the validated question.
        """
        yield {'kind':'status','status':'generating','label':'正在出题中'}
        messages=self.exercise_messages(course,node,profile,sources)
        buffer=''
        async for item in self.stream(messages,self.cfg.answer_tokens,response_format=EXERCISE_RESPONSE_FORMAT):
            if 'text' in item:
                buffer+=item['text']
            if 'usage' in item: yield {'kind':'usage','stage':'exercise','value':item['usage']}
        if len(buffer.strip())<20: raise ProviderError('EMPTY_EXERCISE')
        yield {'kind':'complete','text':buffer}

    async def generate_explanation(self, course, question_text, answer_context, step_text, profile, sources):
        """详解: one provider call explaining a single answer step."""
        yield {'kind':'status','status':'generating','label':'正在生成详解'}
        messages=self.explanation_messages(course,question_text,answer_context,step_text,profile,sources)
        async for item in self.stream(messages,self.cfg.answer_tokens):
            if 'text' in item: yield {'kind':'delta','text':item['text']}
            if 'usage' in item: yield {'kind':'usage','stage':'explanation','value':item['usage']}

    async def classify_course(self, bundle: dict) -> str:
        """Template classification: ONE provider call returning the validated
        JSON candidate. Empty returns classify as OTHER by the caller."""
        text, _ = await self.classify_course_with_usage(bundle)
        return text

    async def classify_course_with_usage(self, bundle: dict) -> tuple[str, list[dict]]:
        """Classify once and return provider usage for the frozen revision.

        This is deliberately separate from ``classify_course`` so existing
        offline doubles retain their compact string-returning contract.
        """
        messages = self.classification_messages(bundle)
        text = ''
        usages: list[dict] = []
        async for item in self.stream(messages, min(self.cfg.prompt_tokens, 1200)):
            if 'text' in item: text += item['text']
            if 'usage' in item: usages.append(item['usage'])
        return text.strip(), usages

class DisabledProvider:
    async def generate(self,*args,**kwargs):
        raise ProviderError('MODEL_NOT_CONFIGURED')
        yield
    async def generate_exercise(self,*args,**kwargs):
        raise ProviderError('MODEL_NOT_CONFIGURED')
        yield
    async def generate_explanation(self,*args,**kwargs):
        raise ProviderError('MODEL_NOT_CONFIGURED')
        yield
    async def classify_course(self,*args,**kwargs):
        raise ProviderError('MODEL_NOT_CONFIGURED')

class TestProvider:
    """Deterministic, clearly-labelled generator for local and browser
    acceptance tests. Selected only by `provider_mode='test'`, which the
    settings validator forbids in production. It never writes learning state
    and never pretends to be Qwen."""

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, *, attachments=None, spec_items=None, teaching_mode='normal', template_id='OTHER'):
        if teaching_mode=='thinking':
            yield {'kind':'status','status':'planning','label':'正在思考中'}
            yield {'kind':'prompt','text':'本地测试教学 Prompt（非千问实测）：逐步讲解，保留英文术语，引用材料标记。'}
        yield {'kind':'status','status':'generating','label':'正在输出中'}
        if lane=='problem':
            answer=('## Step 1 审题与条件整理\n先把题目条件整理成输入参数。\n\n'
                    '## Step 2 计算核心点\n对每个点统计其 eps 邻域内的样本数，达到 MinPts 即为核心点。\n\n'
                    '## Step 3 判断边界与噪声\n根据核心点的邻域关系判断其余样本。\n\n'
                    '## Step 4 核对并作答\n复核条件后写出完整结论。')
        elif bridge and bridge.get('step'):
            answer=f"这是围绕原题第 {bridge['step']} 步的教学输出，携带桥接上下文。"
        elif spec_items:
            sentences=' '.join(
                f"{item.get('objective','')}：{item.get('acceptance','')}"
                for item in spec_items if item.get('requirement')=='REQUIRED')
            answer=f"这是测试教学。{sentences}"
        else:
            answer='从定义出发：核心点是邻域内样本数不少于 MinPts 的点。'
        yield {'kind':'delta','text':answer}
        yield {'kind':'usage','stage':'answer','value':{'output_tokens':24}}

    async def generate_exercise(self, course, node, profile, sources, *, target_label=''):
        yield {'kind':'status','status':'generating','label':'正在出题中'}
        target=(node or {}).get('title') or target_label or '当前知识点'
        question=(f'【诊断题 · {target}】给定二维样本点集合，请解释 DBSCAN 中核心点、'
                  '边界点与噪声点的判定条件，并指出 MinPts 对聚类结果的影响。'
                  '（依据课程知识点自编，非官方原题）')
        answer=[
            {'title':'核心点判定','text':'邻域内样本数不少于 MinPts 的点为核心点。'},
            {'title':'边界点与噪声点','text':'不是核心点但落在核心点邻域内的是边界点；其余为噪声点。'},
            {'title':'MinPts 的影响','text':'MinPts 增大，聚类更保守，噪声点倾向增多。'},
        ]
        yield {'kind':'usage','stage':'exercise','value':{'output_tokens':36}}
        yield {'kind':'complete','text':json.dumps({'question':question,'answer_steps':answer,'references':[]},ensure_ascii=False)}

    async def generate_explanation(self, course, question_text, answer_context, step_text, profile, sources):
        yield {'kind':'status','status':'generating','label':'正在生成详解'}
        yield {'kind':'delta','text':f'这是针对该步骤的本地测试详解：{step_text[:80]}'}
        yield {'kind':'usage','stage':'explanation','value':{'output_tokens':18}}

    async def classify_course(self, bundle: dict) -> str:
        """Deterministic test classification: data-science-flavoured courses
        classify to 03; everything else stays OTHER. Never pretends to be the
        live classifier."""
        haystack = json.dumps(bundle, ensure_ascii=False).casefold()
        if any(token in haystack for token in ('data science', 'cs3481', '统计', '数据分析')):
            return json.dumps({
                'template_id': '03', 'decision': 'classified',
                'degree_level': 'graduate', 'confidence': 0.9, 'alternatives': [],
                'reason': '课程内容以数据科学方法与统计推断为主（测试 Provider 确定性结果）',
                'evidence_refs': [], 'materials_revision': bundle.get('materials_revision', ''),
            }, ensure_ascii=False)
        return json.dumps({
            'template_id': 'OTHER', 'decision': 'other', 'degree_level': 'unknown',
            'confidence': None, 'alternatives': [], 'reason': 'insufficient_evidence',
            'evidence_refs': [], 'materials_revision': bundle.get('materials_revision', ''),
        }, ensure_ascii=False)
