import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
// @ts-ignore delivered JSX module
import { Inbox } from './ui/pages.jsx';
const request = vi.hoisted(() => vi.fn(async (path: string) => {
  if (path.startsWith('/people')) {
    const params = new URLSearchParams(path.split('?')[1]);
    return Array.from({length: Number(params.get('offset')||0)===0?20:1},(_,i)=>({
      id:`person_${Number(params.get('offset')||0)+i}`,name:`Person ${Number(params.get('offset')||0)+i}`,handle:`student${i}`
    }));
  }
  return [];
}));
vi.mock('./ui/api.js',async (original)=>({...await original<object>(),request,
  listShares:async()=>[],searchPeople:(q='',offset=0)=>request(`/people?q=${q}&offset=${offset}&limit=20`)}));

it('opens the default registered directory and can browse beyond twenty',async()=>{
  let content: ReactNode;
  render(<Inbox toast={()=>{}} closeModal={()=>{}} modal={(_:string,node:ReactNode)=>{content=node;}}/>);
  fireEvent.click(screen.getByRole('button',{name:'写信息'}));
  render(<>{content}</>);
  await screen.findByText('Person 0');
  fireEvent.click(screen.getByRole('button',{name:'下一页用户'}));
  await screen.findByText('Person 20');
  await waitFor(()=>expect(request).toHaveBeenCalledWith(expect.stringContaining('offset=20')));
});
