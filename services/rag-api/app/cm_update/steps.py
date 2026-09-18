"""Stable, server-derived step anchors for completed Problem messages, not progress evidence."""
import hashlib
import re

_PATTERN = re.compile(r'^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:Step\s*(\d+)|第\s*(\d+)\s*步|步骤\s*(\d+)|(\d+)[.、)）])\s*[：:.、)）-]?\s*(.*?)(?:\*\*)?\s*$', re.I)

def solution_steps(text: str) -> list[dict]:
    result = []
    fenced = False
    for line_index, line in enumerate(text.splitlines()):
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _PATTERN.match(line)
        if not match:
            continue
        number = int(next(x for x in match.groups()[:4] if x is not None))
        if not 1 <= number <= 100 or any(x['number'] == number for x in result):
            continue
        title = re.sub(r'\*\*|`', '', match.group(5)).strip()[:160] or f'第 {number} 步'
        result.append({'number': number, 'line': line_index, 'title': title,
                       'anchor': hashlib.sha256(f'{line_index}:{line}'.encode()).hexdigest()[:16]})
    return result


def answer_steps_parse(text: str) -> list[dict]:
    """Split a full answer into stable steps WITH their bodies. step_id is a
    server-side content-derived id (not a frontend array position), so the
    详解 window can address the same step across refreshes and shares."""
    headings = solution_steps(text)
    if not headings:
        return []
    lines = text.splitlines()
    steps = []
    for index, heading in enumerate(headings):
        start = heading['line'] + 1
        end = headings[index + 1]['line'] if index + 1 < len(headings) else len(lines)
        body = '\n'.join(lines[start:end]).strip()
        steps.append({
            'step_id': heading['anchor'],
            'ordinal': heading['number'],
            'title': heading['title'],
            'text': (f"{heading['title']}\n{body}").strip() if body else heading['title'],
        })
    return steps
