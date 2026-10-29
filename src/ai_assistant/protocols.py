"""Translate four API protocols to the existing bounded Responses-shaped loop."""
from copy import deepcopy
import json

BASES={'responses':'https://api.openai.com/v1','chat_completions':'https://api.openai.com/v1',
       'anthropic':'https://api.anthropic.com/v1','gemini':'https://generativelanguage.googleapis.com/v1beta'}
LABELS={'responses':'OpenAI Responses','chat_completions':'OpenAI 兼容 Chat Completions',
        'anthropic':'Anthropic Messages','gemini':'Gemini generateContent'}


def _messages(inputs,protocol):
    messages=[];names={}
    for item in inputs:
        kind=item.get('type')
        if item.get('role') in {'user','assistant'}:
            role=item['role'];text=item['content']
            if protocol=='gemini':messages.append({'role':'model' if role=='assistant' else 'user','parts':[{'text':text}]})
            else:messages.append({'role':role,'content':text})
        elif kind=='provider_state':
            if item.get('protocol')!=protocol:raise ValueError('provider state protocol mismatch')
            if protocol=='chat_completions':messages.append(deepcopy(item['content']))
            elif protocol=='anthropic':messages.append({'role':'assistant','content':deepcopy(item['content'])})
            else:messages.append(deepcopy(item['content']))
        elif kind=='function_call':names[item['call_id']]=item['name']
        elif kind=='function_call_output':
            if protocol=='chat_completions':messages.append({'role':'tool','tool_call_id':item['call_id'],'content':item['output']})
            elif protocol=='anthropic':
                block={'type':'tool_result','tool_use_id':item['call_id'],'content':item['output']}
                if messages and messages[-1]['role']=='user' and isinstance(messages[-1]['content'],list):messages[-1]['content'].append(block)
                else:messages.append({'role':'user','content':[block]})
            else:
                name=names.get(item['call_id'])
                if not name:raise ValueError('missing tool name for Gemini response')
                value={'name':name,'response':json.loads(item['output'])}
                # Gemini IDs are optional; local synthetic IDs must not be sent as provider IDs.
                if not item['call_id'].startswith('local-gemini-'):value['id']=item['call_id']
                block={'functionResponse':value}
                if messages and messages[-1]['role']=='user' and 'parts' in messages[-1] and any('functionResponse' in p for p in messages[-1]['parts']):messages[-1]['parts'].append(block)
                else:messages.append({'role':'user','parts':[block]})
    return messages


def to_wire(payload,config):
    protocol=config.protocol
    if protocol=='responses':return payload
    tools=payload.get('tools',[]);messages=_messages(payload['input'],protocol)
    if protocol=='chat_completions':
        body={'model':payload['model'],'messages':[{'role':'system','content':payload['instructions']},*messages],
              config.token_parameter:payload['max_output_tokens'],'stream':False}
        if tools:body['tools']=[{'type':'function','function':{k:t[k] for k in ('name','description','parameters')}} for t in tools]
    elif protocol=='anthropic':
        body={'model':payload['model'],'system':payload['instructions'],'messages':messages,'max_tokens':payload['max_output_tokens']}
        if tools:body['tools']=[{'name':t['name'],'description':t['description'],'input_schema':t['parameters']} for t in tools]
    else:
        body={'systemInstruction':{'parts':[{'text':payload['instructions']}]},'contents':messages,
              'generationConfig':{'maxOutputTokens':payload['max_output_tokens']}}
        if tools:body['tools']=[{'functionDeclarations':[{'name':t['name'],'description':t['description'],'parametersJsonSchema':t['parameters']} for t in tools]}]
    return body


def _text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return '\n'.join(p.get('text','') for p in value if isinstance(p,dict) and p.get('type')=='text')
    return ''


def from_wire(value,protocol):
    if protocol=='responses':return value
    output=[];texts=[];incomplete=False
    if protocol=='chat_completions':
        choice=value['choices'][0];message=choice['message'];calls=message.get('tool_calls') or []
        if calls:
            state={k:deepcopy(message[k]) for k in ('role','content','tool_calls','reasoning_content') if k in message}
            state['role']='assistant';output.append({'type':'provider_state','protocol':protocol,'content':state})
            for call in calls:
                output.append({'type':'function_call','call_id':call['id'],'name':call['function']['name'],'arguments':call['function']['arguments']})
        texts.append(_text(message.get('content')) or _text(message.get('refusal')))
        incomplete=choice.get('finish_reason')=='length'
    elif protocol=='anthropic':
        content=value['content'];calls=[p for p in content if p.get('type')=='tool_use']
        if calls:output.append({'type':'provider_state','protocol':protocol,'content':deepcopy(content)})
        for call in calls:output.append({'type':'function_call','call_id':call['id'],'name':call['name'],'arguments':json.dumps(call['input'],ensure_ascii=False,allow_nan=False)})
        texts.extend(p['text'] for p in content if p.get('type')=='text')
        incomplete=value.get('stop_reason')=='max_tokens'
    else:
        candidate=value['candidates'][0];content=candidate['content'];parts=content['parts']
        calls=[p['functionCall'] for p in parts if 'functionCall' in p]
        if calls:output.append({'type':'provider_state','protocol':protocol,'content':deepcopy(content)})
        for i,call in enumerate(calls):
            output.append({'type':'function_call','call_id':call.get('id') or 'local-gemini-'+str(i),
                 'name':call['name'],'arguments':json.dumps(call.get('args',{}),ensure_ascii=False,allow_nan=False)})
        texts.extend(p['text'] for p in parts if 'text' in p and not p.get('thought'))
        incomplete=candidate.get('finishReason') in {'MAX_TOKENS','CONTINUATION'}
    text='\n'.join(t for t in texts if t)
    if text:output.append({'type':'message','content':[{'type':'output_text','text':text}]})
    return {'id':value.get('id',value.get('responseId')),'status':'incomplete' if incomplete else 'completed','output':output}
