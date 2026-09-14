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
