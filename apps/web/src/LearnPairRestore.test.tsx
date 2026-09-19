import { expect, it, vi } from 'vitest';
// @ts-ignore delivered JSX module
import { Learn } from './ui/pages.jsx';
const api=vi.hoisted(()=>({request:vi.fn(),getPair:vi.fn(),listPairs:vi.fn(),send:vi.fn(),createPair:vi.fn()}));
vi.mock('./ui/api.js',async original=>({...await original<object>(),...api}));

it('restores the exact layout Pair rather than the most recently updated other Pair',async()=>{
  api.request.mockImplementation(async(path:string)=>path.endsWith('/layout')?
    {ratio:.6,teach_conversation:'teach-A',problem_conversation:'problem-A'}:[]);
  api.listPairs.mockResolvedValue([{id:'B',teach_conversation:'teach-B',problem_conversation:'problem-B'},
    {id:'A',teach_conversation:'teach-A',problem_conversation:'problem-A'}]);
  api.getPair.mockResolvedValue({id:'A',bound_node:'node-A',teach:{conversation:{id:'teach-A'},messages:[]},
    problem:{conversation:{id:'problem-A'},messages:[]}});
  const page=new Learn({course:{id:'course'},toast:vi.fn()});
  page.setState=(value:any,callback?:()=>void)=>{page.state={...page.state,...(typeof value==='function'?value(page.state):value)};callback?.();};
  await page.load();
  expect(page.state.pair).toBe('A');
  expect(page.state.conv).toEqual({teach:'teach-A',problem:'problem-A'});
  expect(page.state.activeNode).toBe('node-A');
});

it('simultaneous first lane requests share one pending Pair creation',async()=>{
  api.createPair.mockResolvedValue({id:'both-lanes'});
  const page=new Learn({course:{id:'course'},toast:vi.fn()});
  page.setState=(value:any)=>{page.state={...page.state,...value};};
  expect(await Promise.all([page.ensurePair(),page.ensurePair()])).toEqual(['both-lanes','both-lanes']);
  expect(api.createPair).toHaveBeenCalledTimes(1);
});

it('a delayed initial layout cannot overwrite a newly opened Pair',async()=>{
  let resolveLayout:(value:object)=>void=()=>{};
  api.request.mockImplementation(async(path:string)=>path.endsWith('/layout')?
    new Promise(resolve=>{resolveLayout=resolve;}):[]);
  api.createPair.mockResolvedValue({id:'new-pair'});
  const page=new Learn({course:{id:'course'},toast:vi.fn()});
  page.setState=(value:any,callback?:()=>void)=>{page.state={...page.state,...value};callback?.();};
  const loading=page.load();
  await page.newPair();
  resolveLayout({teach_conversation:'teach-A'});
  await loading;
  expect(page.state.pair).toBe('new-pair');
  expect(page.state.conv).toEqual({teach:null,problem:null});
});
