"""Qwen -> generated teaching prompt -> Qwen answer. Real HTTP, no hardcoded live answers."""
import json
from pathlib import Path
from typing import AsyncIterator
import httpx
from .sse import events

SOURCE_TEMPLATE=Path(__file__).parent/'prompts'/'cs3481_original.txt'

class ProviderError(Exception):
    pass

class QwenProvider:
    def __init__(self, settings, transport=None):
        self.cfg=settings
        self.transport=transport
        self.calls=[]

    def planner_messages(self, course: dict, text: str, profile: dict, sources: list, history: list, lane: str, bridge=None):
        template=SOURCE_TEMPLATE.read_text(encoding='utf-8')
        instruction=('你要为下一次 qwen3.8-max 调用撰写一份完整的教学 Prompt。直接输出 Prompt 正文，'
            '不要输出 JSON，不要回答学生问题，不要写内部推理记录。以以下 CS3481 原始 Word 模板为基础，'
            '保留中文解释、英文术语、为什么/是什么/怎么做、课程资料对应、英文考试作答、例题和互动检查。'
            '根据当前实际课程替换 CS3481 专有课程名；没有资料的部分不要假装读过。'
            '解题请使用 ## Step 1 标题、## Step 2 标题等稳定的步骤标题；模糊图像或缺条件不得猜。'
            '如果是普通寒暄，生成自然回应指令，不强制检索拒答；如果是题目模式，要求给完整参考解法和编号步骤。'
            '最终 Prompt 要能直接交给下一次千问调用执行。\n\n【原始模板全文】\n'+template)
        payload={'course':course['name'],'code':course['code'],'mode':lane,'student_preferences':profile,
            'course_requirements':course.get('requirements',''),'student_question':text,
            'materials':sources,'recent_conversation':history[-12:],'problem_bridge':bridge}
        return [{'role':'system','content':instruction},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]

    def attach_images(self, messages: list, images: list) -> None:
        """Images were authorized/read server-side; data URLs are never persisted or logged."""
        if not images:
            return
        content=messages[-1]['content']
        if self.cfg.qwen_protocol=='responses':
            parts=[{'type':'input_text','text':content}]
            parts.extend({'type':'input_image','image_url':im['data_url']} for im in images)
        else:
            parts=[{'type':'text','text':content}]
            parts.extend({'type':'image_url','image_url':{'url':im['data_url']}} for im in images)
        messages[-1]['content']=parts

    async def stream(self, messages: list, tokens: int) -> AsyncIterator[dict]:
        cfg=self.cfg
        if not cfg.allow_billable: raise ProviderError('BILLING_NOT_AUTHORIZED')
        endpoint=cfg.qwen_base_url.rstrip('/')+('/responses' if cfg.qwen_protocol=='responses' else '/chat/completions')
        if cfg.qwen_protocol=='responses':
            body={'model':cfg.qwen_model,'input':messages,'stream':True,'max_output_tokens':tokens}
        else:
            body={'model':cfg.qwen_model,'messages':messages,'stream':True,'max_tokens':tokens,
                  'enable_thinking':False,'stream_options':{'include_usage':True}}
        self.calls.append({'model':cfg.qwen_model,'stage_tokens':tokens,'protocol':cfg.qwen_protocol})
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
                        if cfg.qwen_protocol=='responses':
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
                                    # Teacher/planner have no tools. A tool_call or truncated answer is not success.
                                    raise ProviderError('INCOMPLETE_PROVIDER_RESPONSE')
                                if reason=='stop': finished=True
                            if data.get('usage'): yield {'usage':data['usage']}
                    if not finished: raise ProviderError('DISCONNECTED_PROVIDER_STREAM')
        except ValueError:
            raise ProviderError('INVALID_PROVIDER_STREAM') from None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            raise ProviderError('PROVIDER_TIMEOUT_OR_NETWORK') from None

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, *, attachments=None):
        yield {'kind':'status','status':'planning','label':'千问正在根据 CS3481 模板撰写教学 Prompt'}
        prompt=''
        planner=self.planner_messages(course,text,profile,sources,history,lane,bridge)
        self.attach_images(planner, attachments or [])
        async for item in self.stream(planner,self.cfg.prompt_tokens):
            if 'text' in item: prompt+=item['text']
            if 'usage' in item: yield {'kind':'usage','stage':'prompt','value':item['usage']}
            if len(prompt)>24000: raise ProviderError('PROMPT_TOO_LONG')
        if len(prompt.strip())<30: raise ProviderError('EMPTY_GENERATED_PROMPT')
        yield {'kind':'prompt','text':prompt}
        yield {'kind':'status','status':'generating','label':'教学 Prompt 已生成，千问正在讲解'}
        instruction=('你是 CourseMate 教师。执行下面由千问生成的教学 Prompt，给出可核验的教学解释，'
                     '不要暴露内部思维链。只使用提供的材料引用标记 [S1] 等；无材料支持时区分补充理解。'
                     '没有工具权限，不要声称修改了数据库、分数或发布状态。\n\n'+prompt)
        messages=[{'role':'system','content':instruction}]
        messages.extend({'role':x['role'],'content':x['text'][:10000]} for x in history[-12:] if x['role'] in {'user','assistant'})
        messages.append({'role':'user','content':json.dumps({'question':text,'course_materials':sources,'bridge':bridge},ensure_ascii=False)})
        self.attach_images(messages, attachments or [])
        async for item in self.stream(messages,self.cfg.answer_tokens):
            if 'text' in item: yield {'kind':'delta','text':item['text']}
            if 'usage' in item: yield {'kind':'usage','stage':'answer','value':item['usage']}

class DisabledProvider:
    async def generate(self,*args,**kwargs):
        raise ProviderError('MODEL_NOT_CONFIGURED')
        yield

class TestProvider:
    """Deterministic, clearly-labelled generator for local and browser acceptance tests.

    Selected only by `provider_mode='test'`, which the settings validator forbids
    in production. The problem lane answers with numbered step headings so the
    server-derived step parsing, bridge and return flow exercise exactly the same
    code path a live model's output would; the teach lane echoes the carried
    bridge context. It never writes learning state and never pretends to be Qwen.
    """

    async def generate(self, course, text, profile, sources, history, lane, bridge=None, *, attachments=None):
        yield {'kind': 'status', 'status': 'planning', 'label': '本地测试 Provider：撰写教学 Prompt'}
        yield {'kind': 'prompt', 'text': '本地测试教学 Prompt（非千问实测）：逐步讲解，保留英文术语，引用材料标记。'}
        yield {'kind': 'status', 'status': 'generating', 'label': '本地测试 Provider：生成讲解'}
        if lane == 'problem':
            answer = ('## Step 1 审题与条件整理\n先把题目条件整理成输入参数。\n\n'
                      '## Step 2 计算核心点\n对每个点统计其 eps 邻域内的样本数，达到 MinPts 即为核心点。')
        elif bridge and bridge.get('step'):
            answer = f"这是围绕原题第 {bridge['step']} 步的教学输出，携带桥接上下文。"
        else:
            answer = '从定义出发：核心点是邻域内样本数不少于 MinPts 的点。'
        yield {'kind': 'delta', 'text': answer}
        yield {'kind': 'usage', 'stage': 'answer', 'value': {'output_tokens': 24}}
