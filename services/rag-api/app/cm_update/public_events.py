"""Public SSE projection applies equally to new events and historical rows."""

def public_event(kind: str, value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    if kind == 'prompt_ready':
        count = value.get('characters')
        return {'characters': count} if type(count) is int and count >= 0 else {}
    if kind == 'status':
        status = value.get('status')
        labels = {'queued': '正在思考中', 'planning': '正在思考中',
                  'generating': '正在输出中', 'completed': '已完成',
                  'failed': '生成失败', 'cancelled': '已停止'}
        return {'status': status, 'label': labels[status]} if status in labels else None
    if kind == 'delta':
        text = value.get('text')
        return {'text': text} if isinstance(text, str) else None
    if kind == 'error':
        cancelled = value.get('code') == 'CANCELLED'
        return {'code': 'CANCELLED' if cancelled else 'GENERATION_FAILED',
                'message': '已停止' if cancelled else '生成未完成，请检查运行状态。'}
    if kind == 'coverage':
        # Coverage details are read from the authorized delivery receipt. Never
        # replay arbitrary nested evaluator/debug payloads or exception text.
        return {'updated': True}
    if kind == 'done':
        return {k: value[k] for k in ('message_id', 'exercise_id', 'explanation_id',
                                      'provider_mode')
                if isinstance(value.get(k), str)}
    return None
