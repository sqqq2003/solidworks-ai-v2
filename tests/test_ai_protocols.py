"""Four real wire-format adapters over fake HTTP; no provider call is made."""
import json
import unittest
from unittest.mock import patch
from ai_assistant import AIConfig,AssistantSession,ResponsesClient,AssistantError
from ai_assistant.client import scoped_api_key
from ai_assistant.protocols import to_wire

class Response:
    def __init__(self,value):self.data=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.data[:limit]

class Wire:
    def __init__(self,responses):self.responses=iter(responses);self.requests=[]
    def open(self,request,timeout):self.requests.append(request);return Response(next(self.responses))

class ProtocolTests(unittest.TestCase):
    def chat(self,protocol,replies,**kwargs):
        cfg=AIConfig('fixture-model','fixture-key',protocol=protocol,**kwargs)
        wire=Wire(replies);session=AssistantSession(cfg,transport=ResponsesClient(cfg,opener=wire))
        report=session.chat('有哪些功能');return report,wire

    def test_chat_completions_text(self):
        report,wire=self.chat('chat_completions',[{'choices':[{'message':{'role':'assistant','content':'你好'},'finish_reason':'stop'}]}],base_url='https://provider.example/v1')
        self.assertEqual(report['text'],'你好');self.assertEqual(wire.requests[0].full_url,'https://provider.example/v1/chat/completions')
        body=json.loads(wire.requests[0].data);self.assertEqual(body['messages'][0]['role'],'system')
        self.assertNotIn('input',body);self.assertNotIn('store',body)

    def test_chat_tool_loop_preserves_reasoning(self):
        first={'choices':[{'message':{'role':'assistant','content':None,'reasoning_content':'fixture-private-reasoning',
               'tool_calls':[{'id':'c1','type':'function','function':{'name':'get_project_capabilities','arguments':'{}'}}]},'finish_reason':'tool_calls'}]}
        second={'choices':[{'message':{'role':'assistant','content':'需要工程复核'},'finish_reason':'stop'}]}
        report,wire=self.chat('chat_completions',[first,second])
        messages=json.loads(wire.requests[1].data)['messages']
        self.assertEqual(messages[-2]['reasoning_content'],'fixture-private-reasoning')
        self.assertEqual(messages[-1]['role'],'tool');self.assertEqual(messages[-1]['tool_call_id'],'c1')
        self.assertNotIn('fixture-private-reasoning',json.dumps(report))
        self.assertFalse(report['native_write_allowed'])

    def test_anthropic_tool_loop_keeps_thinking_signature(self):
        block={'type':'thinking','thinking':'not displayed','signature':'fixture-signed'}
        first={'id':'a1','content':[block,{'type':'tool_use','id':'t1','name':'get_project_capabilities','input':{}}],'stop_reason':'tool_use'}
        second={'id':'a2','content':[{'type':'text','text':'待审核'}],'stop_reason':'end_turn'}
        report,wire=self.chat('anthropic',[first,second])
        self.assertTrue(wire.requests[0].full_url.endswith('/v1/messages'))
        self.assertEqual(wire.requests[0].get_header('X-api-key'),'fixture-key')
        body=json.loads(wire.requests[1].data)
        self.assertEqual(body['messages'][-2]['content'][0],block)
        self.assertEqual(body['messages'][-1]['content'][0]['tool_use_id'],'t1')
        self.assertEqual(report['text'],'待审核')

    def test_gemini_tool_loop_preserves_thought_signature(self):
        part={'functionCall':{'id':'g1','name':'get_project_capabilities','args':{}},'thoughtSignature':'fixture-signature'}
        first={'candidates':[{'content':{'role':'model','parts':[part]},'finishReason':'STOP'}]}
        second={'candidates':[{'content':{'role':'model','parts':[{'text':'可查看审核方案'}]},'finishReason':'STOP'}]}
        report,wire=self.chat('gemini',[first,second])
        self.assertTrue(wire.requests[0].full_url.endswith('/models/fixture-model:generateContent'))
        self.assertNotIn('fixture-key',wire.requests[0].full_url)
        self.assertEqual(wire.requests[0].get_header('X-goog-api-key'),'fixture-key')
        contents=json.loads(wire.requests[1].data)['contents']
        self.assertEqual(contents[-2]['parts'][0]['thoughtSignature'],'fixture-signature')
        self.assertEqual(contents[-1]['parts'][0]['functionResponse']['id'],'g1')
        self.assertEqual(report['protocol'],'gemini')

    def test_gemini_without_function_id(self):
        first={'candidates':[{'content':{'role':'model','parts':[{'functionCall':{'name':'get_project_capabilities','args':{}}}]}}]}
        second={'candidates':[{'content':{'role':'model','parts':[{'text':'完成查询'}]}}]}
        _,wire=self.chat('gemini',[first,second]);response=json.loads(wire.requests[1].data)['contents'][-1]['parts'][0]['functionResponse']
        self.assertNotIn('id',response);self.assertEqual(response['name'],'get_project_capabilities')

    def test_plain_text_mode_omits_tools(self):
        _,wire=self.chat('chat_completions',[{'choices':[{'message':{'content':'文字回复'}}]}],enable_tools=False)
        self.assertNotIn('tools',json.loads(wire.requests[0].data))

    def test_disabled_tools_cannot_be_forced_by_server(self):
        reply={'output':[{'type':'function_call','name':'get_project_capabilities','call_id':'x','arguments':'{}'}]}
        cfg=AIConfig('m','key',enable_tools=False)
        with patch('ai_assistant.session.call_readonly_tool') as tool:
            with self.assertRaises(AssistantError):AssistantSession(cfg,transport=lambda payload:reply).chat('test')
            tool.assert_not_called()

    def test_local_endpoint_can_omit_key(self):
        for base in ('http://localhost:11434/v1','http://127.0.0.1:1234/v1','http://[::1]:1234/v1'):
            c=AIConfig('m','',protocol='chat_completions',base_url=base);c.validate();self.assertTrue(c.is_local())

    def test_remote_url_validation(self):
        for base in ('http://example.com/v1','https://user:password@example.com/v1','https://example.com/v1?key=secret','https://example.com/v1#secret','file:///tmp/a','https://[invalid','https://example.com:bad/v1'):
            with self.subTest(base=base):
                with self.assertRaises(AssistantError):AIConfig('m','key',base_url=base).validate()

    def test_missing_remote_key_refused(self):
        with self.assertRaises(AssistantError):AIConfig('m','',protocol='chat_completions',base_url='https://provider.example/v1').validate()

    def test_cross_vendor_secret_not_reused(self):
        old=AIConfig('m','old-secret')
        target=AIConfig('m','',protocol='chat_completions',base_url='https://new.example/v1')
        self.assertEqual(scoped_api_key(target,candidates=[old]),'')
        self.assertEqual(scoped_api_key(target,'new-secret',[old]),'new-secret')
        self.assertEqual(scoped_api_key(old,candidates=[old]),'old-secret')

    def test_provider_specific_environment(self):
        with patch.dict('os.environ',{'AI_PROTOCOL':'anthropic','ANTHROPIC_API_KEY':'anthropic-fixture','ANTHROPIC_MODEL':'fixture','OPENAI_API_KEY':'do-not-use'},clear=True):
            c=AIConfig.from_env();self.assertEqual(c.api_key,'anthropic-fixture');self.assertEqual(c.protocol,'anthropic')

    def test_chat_budget_field_configurable(self):
        _,wire=self.chat('chat_completions',[{'choices':[{'message':{'content':'ok'}}]}],token_parameter='max_completion_tokens')
        body=json.loads(wire.requests[0].data);self.assertIn('max_completion_tokens',body);self.assertNotIn('max_tokens',body)

    def test_protocol_mismatch_is_explicit(self):
        with self.assertRaises(AssistantError):self.chat('anthropic',[{'choices':[]}])

    def test_full_openai_endpoint_not_duplicated(self):
        c=AIConfig('m','key',protocol='chat_completions',base_url='https://example.com/v1/chat/completions')
        self.assertEqual(c.endpoint(),'https://example.com/v1/chat/completions')

    def test_unknown_protocol_refused(self):
        with self.assertRaises(AssistantError):AIConfig('m','key',protocol='unknown').validate()

    def test_gemini_model_path_is_not_arbitrary_url(self):
        with self.assertRaises(AssistantError):AIConfig('../secret','key',protocol='gemini').validate()
