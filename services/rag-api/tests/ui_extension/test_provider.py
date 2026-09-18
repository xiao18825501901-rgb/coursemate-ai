import json
import httpx
import pytest
from app.cm_update.config import Settings
from app.cm_update.provider import QwenProvider,ProviderError
from app.cm_update import templates

def cfg(**kw):return Settings(provider_mode='qwen',qwen_base_url='https://qwen.example.test/v1',qwen_key='test-not-real',allow_billable=True,**kw)
def chat(text,finish='stop'):
 return '\n\n'.join('data: '+json.dumps(x,ensure_ascii=False) for x in [
 {'choices':[{'delta':{'content':text},'finish_reason':None}]},
 {'choices':[{'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':10,'completion_tokens':20}},
 ])+'\n\ndata: [DONE]\n\n'

@pytest.mark.asyncio
async def test_thinking_mode_two_call_contract_uses_template_and_generated_prompt():
 calls=[];generated='你是这门课的私人老师，请使用中文解释并保留英文术语，逐步讲例题，最后给互动检查。'
 def transport(request):
  b=json.loads(request.content);calls.append(b)
  assert b['model']=='qwen3.8-max' and b['enable_thinking'] is False
  return httpx.Response(200,text=chat(generated if len(calls)==1 else '第二次调用生成教学答案 [S1]'),headers={'content-type':'text/event-stream'})
 p=QwenProvider(cfg(),httpx.MockTransport(transport))
 items=[x async for x in p.generate({'name':'Data Science','code':'CS3481'},'教我 DBSCAN',{'language':'zh-CN'},[{'id':'S1','text':'density'}],[],'teach',teaching_mode='thinking',template_id='OTHER')]
 assert len(calls)==2
 assert templates.plan_writer_instruction() in calls[0]['messages'][0]['content']
 assert templates.template_body('OTHER') in calls[0]['messages'][0]['content']
 assert generated in calls[1]['messages'][0]['content']
 assert '不输出 JSON' in calls[0]['messages'][0]['content']
 assert any(x['kind']=='prompt' and x['text']==generated for x in items)
 assert ''.join(x['text'] for x in items if x['kind']=='delta')=='第二次调用生成教学答案 [S1]'
 assert len([x for x in items if x['kind']=='usage'])==2

@pytest.mark.asyncio
async def test_normal_mode_is_single_call_without_plan():
 calls=[]
 def transport(request):
  b=json.loads(request.content);calls.append(b)
  assert b['model']=='qwen3.8-max' and b['enable_thinking'] is False
  return httpx.Response(200,text=chat('直接回答 [S1]'),headers={'content-type':'text/event-stream'})
 p=QwenProvider(cfg(),httpx.MockTransport(transport))
 items=[x async for x in p.generate({'name':'Data Science','code':'CS3481'},'教我 DBSCAN',{'language':'zh-CN'},[{'id':'S1','text':'density'}],[],'teach',teaching_mode='normal')]
 assert len(calls)==1
 assert any(x['kind']=='delta' and x['text']=='直接回答 [S1]' for x in items)
 assert not any(x['kind']=='prompt' for x in items)
 assert '教学 Prompt' not in calls[0]['messages'][0]['content']

@pytest.mark.asyncio
async def test_problem_lane_normal_mode_uses_problem_word_prompt():
 def transport(r):
  b=json.loads(r.content)
  assert templates.problem_prompt() in b['messages'][0]['content']
  return httpx.Response(200,text=chat('## Step 1 审题'),headers={'content-type':'text/event-stream'})
 p=QwenProvider(cfg(),httpx.MockTransport(transport))
 items=[x async for x in p.generate({'name':'x','code':'x'},'一道题',{},[],[],'problem',teaching_mode='normal')]
 assert any(x['kind']=='delta' for x in items)

@pytest.mark.asyncio
async def test_budget_gate_no_outbound_request():
 c=cfg();c.allow_billable=False;n=0
 def transport(r):
  nonlocal n;n+=1;return httpx.Response(200)
 with pytest.raises(ProviderError,match='BILLING_NOT_AUTHORIZED'):
  async for _ in QwenProvider(c,httpx.MockTransport(transport)).stream([],500):pass
 assert n==0

@pytest.mark.parametrize('status',[401,402,403,429,500])
@pytest.mark.asyncio
async def test_errors_no_retry_or_secret_echo(status):
 n=0
 def transport(request):
  nonlocal n;n+=1;return httpx.Response(status,text='secret upstream debug')
 with pytest.raises(ProviderError,match='PROVIDER_HTTP_'+str(status)) as e:
  async for _ in QwenProvider(cfg(),httpx.MockTransport(transport)).stream([],500):pass
 assert n==1;assert 'secret' not in str(e.value)

@pytest.mark.asyncio
async def test_incomplete_prompt_does_not_start_second_call():
 n=0
 def transport(r):
  nonlocal n;n+=1;return httpx.Response(200,text=chat('x'*100,'length'))
 with pytest.raises(ProviderError,match='INCOMPLETE'):
  async for _ in QwenProvider(cfg(),httpx.MockTransport(transport)).generate({'name':'x','code':'x'},'y',{},[],[],'teach',teaching_mode='thinking'):pass
 assert n==1

@pytest.mark.asyncio
async def test_responses_protocol_contract():
 def transport(r):
  b=json.loads(r.content);assert 'input' in b and b['max_output_tokens']==512
  return httpx.Response(200,text='data: '+json.dumps({'type':'response.output_text.delta','delta':'你好'})+'\n\ndata: '+json.dumps({'type':'response.completed','response':{'usage':{'input_tokens':5}}})+'\n\n')
 rows=[x async for x in QwenProvider(cfg(qwen_protocol='responses'),httpx.MockTransport(transport)).stream([],512)]
 assert rows[0]['text']=='你好';assert rows[1]['usage']['input_tokens']==5

def test_templates_are_not_garbled():
 s=templates.template_body('02');assert 'ciallo' in s and '中文' in s and len(s)>5000
 assert templates.exercise_prompt() and templates.problem_prompt() and templates.explanation_prompt()
