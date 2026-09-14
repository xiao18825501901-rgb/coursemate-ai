import json
import httpx
import pytest
from app.cm_update.config import Settings
from app.cm_update.provider import QwenProvider,ProviderError,SOURCE_TEMPLATE

def cfg(**kw):return Settings(provider_mode='qwen',qwen_base_url='https://qwen.example.test/v1',qwen_key='test-not-real',allow_billable=True,**kw)
def chat(text,finish='stop'):
 return '\n\n'.join('data: '+json.dumps(x,ensure_ascii=False) for x in [
 {'choices':[{'delta':{'content':text},'finish_reason':None}]},
 {'choices':[{'delta':{},'finish_reason':finish}],'usage':{'prompt_tokens':10,'completion_tokens':20}},
 ])+'\n\ndata: [DONE]\n\n'

@pytest.mark.asyncio
async def test_real_http_two_call_contract_uses_full_word_and_generated_prompt():
 calls=[];generated='你是这门课的私人老师，请使用中文解释并保留英文术语，逐步讲例题，最后给互动检查。'
 def transport(request):
  b=json.loads(request.content);calls.append(b)
  assert b['model']=='qwen3.8-max' and b['enable_thinking'] is False
  return httpx.Response(200,text=chat(generated if len(calls)==1 else '第二次调用生成教学答案 [S1]'),headers={'content-type':'text/event-stream'})
 p=QwenProvider(cfg(),httpx.MockTransport(transport));items=[x async for x in p.generate({'name':'Data Science','code':'CS3481'},'教我 DBSCAN',{'language':'zh-CN'},[{'id':'S1','text':'density'}],[],'teach')]
 assert len(calls)==2
 assert SOURCE_TEMPLATE.read_text(encoding='utf-8') in calls[0]['messages'][0]['content']
 assert generated in calls[1]['messages'][0]['content']
 assert '不要输出 JSON' in calls[0]['messages'][0]['content']
 assert any(x['kind']=='prompt' and x['text']==generated for x in items)
 assert ''.join(x['text'] for x in items if x['kind']=='delta')=='第二次调用生成教学答案 [S1]'
 assert len([x for x in items if x['kind']=='usage'])==2

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
  async for _ in QwenProvider(cfg(),httpx.MockTransport(transport)).generate({'name':'x','code':'x'},'y',{},[],[],'teach'):pass
 assert n==1

@pytest.mark.asyncio
async def test_responses_protocol_contract():
 def transport(r):
  b=json.loads(r.content);assert 'input' in b and b['max_output_tokens']==512
  return httpx.Response(200,text='data: '+json.dumps({'type':'response.output_text.delta','delta':'你好'})+'\n\ndata: '+json.dumps({'type':'response.completed','response':{'usage':{'input_tokens':5}}})+'\n\n')
 rows=[x async for x in QwenProvider(cfg(qwen_protocol='responses'),httpx.MockTransport(transport)).stream([],512)]
 assert rows[0]['text']=='你好';assert rows[1]['usage']['input_tokens']==5

def test_word_template_is_not_garbled():
 s=SOURCE_TEMPLATE.read_text(encoding='utf-8');assert 'ciallo' in s and '中文' in s and '第十步' in s;assert len(s)>2500
