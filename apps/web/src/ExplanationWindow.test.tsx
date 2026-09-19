import React from 'react';
import {render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
// @ts-ignore delivered JSX component
import {ExplanationWindow} from './ui/pages.jsx';

it('renders saved step code through the safe work-content renderer',()=>{
  const {container}=render(<ExplanationWindow win={{ordinal:1,z:1}}
    exp={{status:'completed',messages:[{id:'answer',role:'assistant',text:'Example\n```python\nprint(1)\n```\n\nInline `x` and <script>not executable</script>'}]}}
    onRaise={vi.fn()} onClose={vi.fn()} onFollowUp={vi.fn()} onCancel={vi.fn()}/>);
  expect(container.querySelector('pre code')).toHaveTextContent('print(1)');
  expect(container.querySelector('script')).toBeNull();
  expect(screen.getByRole('dialog',{name:'详解 · 第 1 步'})).toBeVisible();
});
