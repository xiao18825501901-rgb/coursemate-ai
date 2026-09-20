import React from 'react';

// KaTeX produces MathML only. No HTML received from the model is ever rendered as HTML.
function Formula({tex, display=false}) {
    if (!window.CourseMateMath || tex.length>4000) return <code>{tex}</code>;
    try {
        const out=window.CourseMateMath.renderToString(tex,{output:'mathml',displayMode:display,throwOnError:true,trust:false,maxExpand:100,maxSize:12,strict:'error'});
        const doc=new DOMParser().parseFromString(out,'text/html');
        const allowed=new Set(['math','semantics','annotation','mrow','mi','mn','mo','mtext','mspace','msup','msub','msubsup','mfrac','msqrt','mroot','munder','mover','munderover','mtable','mtr','mtd','menclose','mpadded','mstyle','mmultiscripts','mprescripts','none']);
        const attrs=new Set(['xmlns','display','encoding','mathvariant','stretchy','fence','separator','accent','accentunder','linethickness','columnalign','columnspacing','rowspacing','rowalign','lspace','rspace','width','height','depth','voffset','scriptlevel','displaystyle','notation']);
        const math=doc.querySelector('math');
        function convert(n,i) {
            if(n.nodeType===3) return n.textContent;
            const name=n.nodeName.toLowerCase();if(!allowed.has(name))return null;
            const props={key:i};for(const a of n.attributes)if(attrs.has(a.name))props[a.name]=a.value;
            return React.createElement(name,props,...Array.from(n.childNodes).map(convert));
        }
        return <span className={display?'formula-display':'formula-inline'}>{math?convert(math,0):tex}</span>;
    } catch { return <code className="math-source" title="公式未完整或暂不支持，显示原始表达式">{tex}</code>; }
}
function Inline({text}) {
    const parts=String(text).split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\\\([^\n]*?\\\)|\$[^$\n]+\$)/g);
    return <>{parts.map((s,i)=>s.startsWith('`')?<code key={i}>{s.slice(1,-1)}</code>:s.startsWith('**')?<strong key={i}>{s.slice(2,-2)}</strong>:s.startsWith('\\(')?<Formula key={i} tex={s.slice(2,-2)}/>:s.startsWith('$')?<Formula key={i} tex={s.slice(1,-1)}/>:s)}</>;
}
function BlockContent({lines}) {
    const result=[];
    for(let i=0;i<lines.length;i++){
        const line=lines[i];
        if(/^\s*(```|~~~)/.test(line)){
            const fence=line.trim().slice(0,3),code=[];
            while(++i<lines.length && !lines[i].trim().startsWith(fence))code.push(lines[i]);
            result.push(<pre key={'code'+i}><code>{code.join('\n')}</code></pre>);continue;
        }
        if(/^\s*(\$\$|\\\[)/.test(line)){
            const close=line.trim().startsWith('$$')?'$$':'\\]';let tex=line.trim().slice(2);
            if(tex.endsWith(close)&&tex.length>=2)tex=tex.slice(0,-2);
            else {while(++i<lines.length){if(lines[i].includes(close)){tex+='\n'+lines[i].slice(0,lines[i].indexOf(close));break;}tex+='\n'+lines[i];}}
            result.push(<Formula key={'math'+i} tex={tex.trim()} display/>);continue;
        }
        if(line.includes('|') && i+1<lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
            const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
            const header=cells(line),rows=[];i+=2;
            while(i<lines.length&&lines[i].includes('|')){rows.push(cells(lines[i]));i++;}i--;
            result.push(<div className="answer-table" key={'table'+i}><table><thead><tr>{header.map((v,j)=><th key={j}><Inline text={v}/></th>)}</tr></thead><tbody>{rows.map((r,k)=><tr key={k}>{r.map((v,j)=><td key={j}><Inline text={v}/></td>)}</tr>)}</tbody></table></div>);continue;
        }
        if(/^\s*[-*+]\s/.test(line)){
            const rows=[line.replace(/^\s*[-*+]\s/,'')];while(i+1<lines.length&&/^\s*[-*+]\s/.test(lines[i+1]))rows.push(lines[++i].replace(/^\s*[-*+]\s/,''));
            result.push(<ul key={'list'+i}>{rows.map((v,k)=><li key={k}><Inline text={v}/></li>)}</ul>);continue;
        }
        if(/^#{1,6}\s/.test(line))result.push(<h3 key={i}><Inline text={line.replace(/^#{1,6}\s*/, '')}/></h3>);
        else if(line.trim())result.push(<p key={i}><Inline text={line}/></p>);
    }
    return <>{result}</>;
}
export function RichText({text,message}){
    const lines=String(text).split('\n'),steps=message?.steps||[],groups=[];
    let group={step:null,lines:[]};
    for(let i=0;i<lines.length;i++){
        const step=steps.find(x=>x.line===i);
        if(step){if(group.lines.length)groups.push(group);group={step,lines:[]};}
        group.lines.push(lines[i]);
    }
    if(group.lines.length)groups.push(group);
    // Step sections remain as stable answer anchors. They deliberately do not
    // create a cross-pane question or mutate the teaching conversation.
    return <div className="rich-text">{groups.map((g,i)=><section key={i} id={g.step&&message?`step-${message.id}-${g.step.number}`:undefined}><BlockContent lines={g.lines}/></section>)}</div>;
}
