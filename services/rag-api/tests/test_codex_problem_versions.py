from test_current_change_features import UI, auth, client, make_course, wait_terminal


def test_user_problem_persists_answer_steps_and_can_open_explanation(client):
    make_course(client)
    conv=client.post(f'{UI}/conversations',headers=auth('token-a'),json={'course':'cs3481','lane':'problem'}).json()
    started=client.post(f"{UI}/conversations/{conv['id']}/runs",headers=auth('token-a'),
        json={'text':'Explain the steps of this supplied synthetic problem','request_id':'supplied-problem'})
    assert started.status_code==202,started.text
    assert wait_terminal(client,started.json()['id'])['status']=='completed'
    restored=client.get(f"{UI}/conversations/{conv['id']}",headers=auth('token-a')).json()
    message=next(m for m in restored['messages'] if m['role']=='assistant')
    assert message['exercise'], 'Supplied problems need persistent answer versions, not only Markdown anchors'
    answer=client.get(f"{UI}/exercises/{message['exercise']}",headers=auth('token-a')).json()
    assert answer['revealed'] and answer['steps']
    opened=client.post(f"{UI}/exercises/{message['exercise']}/steps/{answer['steps'][0]['step_id']}/explanation",
        headers=auth('token-a'),json={'request_id':'supplied-problem-explanation'})
    assert opened.status_code==202,opened.text
    assert wait_terminal(client,opened.json()['run'])['status']=='completed'
    followup_url=f"{UI}/explanations/{opened.json()['id']}/messages"
    followup={'text':'Explain the same step more slowly','request_id':'explanation-followup-once'}
    sent=client.post(followup_url,headers=auth('token-a'),json=followup)
    assert sent.status_code==202,sent.text
    wait_terminal(client,sent.json()['run'])
    repeated=client.post(followup_url,headers=auth('token-a'),json=followup)
    assert repeated.status_code==202,repeated.text
    assert repeated.json()['run']==sent.json()['run']
    conflict=client.post(followup_url,headers=auth('token-a'),json={**followup,'text':'Different request'})
    assert conflict.status_code==409
    detail=client.get(f"{UI}/explanations/{opened.json()['id']}",headers=auth('token-a')).json()
    assert sum(m['role']=='user' for m in detail['messages'])==1
