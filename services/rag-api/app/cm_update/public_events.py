"""Public SSE projection applies equally to new events and historical rows."""

_SAFE_ERRORS = {
    'QUESTION_BLUEPRINT_INVALID': '当前知识点的测评蓝图无效，尚未调用模型；请记录诊断编号后重试。',
    'INVALID_OBJECTIVE': '当前知识点的学习目标不符合出题合同，尚未调用模型。',
    'NO_TEACHING_SPEC': '当前知识点缺少有效 Teaching Spec，尚未调用模型。',
    'SPEC_NOT_AVAILABLE': '当前知识点缺少已启用的 Teaching Spec，尚未调用模型。',
    'NO_EXERCISE_READY_NODE': '本课程暂时没有可用于出题的有效知识点。',
    'INCOMPLETE_PROVIDER_RESPONSE': '模型在生成完整结果前停止；已保留本次运行和费用记录，不会自动重发。',
    'INCOMPLETE_PROVIDER_RESPONSE_MAX_OUTPUT_TOKENS': '模型达到本次输出上限；已保留内部生成片段与费用记录，不会自动重发。',
    'INCOMPLETE_PROVIDER_RESPONSE_CONTENT_FILTER': '模型因内容策略停止；已保留本次运行和费用记录，不会自动重发。',
    'INCOMPLETE_PROVIDER_RESPONSE_SERVER_ERROR': '模型服务在完成前停止；已保留本次运行和费用记录，不会自动重发。',
    'DISCONNECTED_PROVIDER_STREAM': '模型连接已中断；系统会按原运行记录检查已保存结果，不会重新生成。',
    'PROVIDER_TIMEOUT_OR_NETWORK': '模型连接超时或网络中断；已保留运行记录，不会自动重发。',
    'AUTHOR_PROVIDER_BLOCKED': '题目作者请求状态未能确定；不会自动重复付费调用。',
    'AUTHOR_PROVIDER_FAILED': '题目作者未返回可验证的完整结果。',
    'BLIND_SOLVER_PROVIDER_BLOCKED': '盲解请求状态未能确定；不会自动重复付费调用。',
    'BLIND_SOLVER_PROVIDER_FAILED': '盲解未返回可验证的完整结果。',
    'QUESTION_REVIEW_UNAVAILABLE': '题目复核暂时不可用；未验证题目不会展示。',
    'QUESTION_ENGINE_FAILED': '题目未通过当前证据与验证门槛；不会展示未验证题目。',
}

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
        code = value.get('code')
        if code == 'CANCELLED':
            return {'code': 'CANCELLED', 'message': '已停止'}
        if isinstance(code, str) and code in _SAFE_ERRORS:
            return {'code': code, 'message': _SAFE_ERRORS[code]}
        return {'code': 'GENERATION_FAILED',
                'message': '生成未完成；已保留诊断编号，请稍后从原运行恢复。'}
    if kind == 'coverage':
        # Coverage details are read from the authorized delivery receipt. Never
        # replay arbitrary nested evaluator/debug payloads or exception text.
        return {'updated': True}
    if kind == 'done':
        return {k: value[k] for k in ('message_id', 'exercise_id', 'explanation_id',
                                      'provider_mode')
                if isinstance(value.get(k), str)}
    return None
