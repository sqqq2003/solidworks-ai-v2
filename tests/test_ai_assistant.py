"""Responses wire/loop checks using fake HTTP only; never a live API or CAD."""
from copy import deepcopy
import json
import threading
import unittest
from unittest.mock import patch
import urllib.error
from ai_assistant import AIConfig,ResponsesClient,AssistantSession,AssistantError
from ai_assistant.client import NoRedirect
from ai_assistant.tools import call_readonly_tool,tool_definitions


def config():return AIConfig(model='fixture-model',api_key='fixture-api-key')
def answer(text='方案建议',status='completed'):
    return {'id':'fixture-response','status':status,'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
def call(name='get_project_capabilities',args=None):
    return {'type':'function_call','name':name,'arguments':json.dumps(args or {},ensure_ascii=False),'call_id':'fixture-call'}


class FakeResponse:
    def __init__(self,data):self.data=json.dumps(data).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.data[:limit]


class AssistantTests(unittest.TestCase):
    def test_configuration_missing_not_connected(self):
        with patch.dict('os.environ',{},clear=True):
            c=AIConfig.from_env();self.assertFalse(c.public_status()['connection_verified'])
            with self.assertRaises(AssistantError):AssistantSession(c)

    def test_key_hidden_from_repr_and_public_status(self):
        c=config();self.assertNotIn(c.api_key,repr(c));self.assertNotIn(c.api_key,json.dumps(c.public_status()))

    def test_wire_contract(self):
        from unittest.mock import Mock
        opener=Mock();opener.open.return_value=FakeResponse(answer())
        client=ResponsesClient(config(),opener=opener)
        client({'model':'fixture-model','input':'hello','store':False})
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
        self.assertEqual(request.get_method(),'POST')
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-api-key')
        self.assertFalse(json.loads(request.data)['store'])

    def test_redirect_is_refused(self):
        with self.assertRaises(AssistantError):NoRedirect().redirect_request(None,None,302,'redirect',{},'https://example.org')

    def test_http_error_body_never_echoed(self):
        from unittest.mock import Mock
        opener=Mock();opener.open.side_effect=urllib.error.HTTPError('https://api.openai.com',401,'fixture-api-key',{},None)
        with self.assertRaises(AssistantError) as caught:ResponsesClient(config(),opener=opener)({})
        self.assertNotIn('fixture-api-key',str(caught.exception))

    def test_payload_is_bounded(self):
        from unittest.mock import Mock
        opener=Mock()
        with self.assertRaises(AssistantError):ResponsesClient(config(),opener=opener)({'input':'x'*300000})
        opener.open.assert_not_called()

    def test_plain_conversation_and_history(self):
        requests=[]
        def fake(payload):requests.append(deepcopy(payload));return answer()
        session=AssistantSession(config(),transport=fake)
        out=session.chat('你好');session.chat('继续')
        self.assertEqual(len(requests[1]['input']),3)
        self.assertFalse(out['native_write_allowed']);self.assertFalse(out['cad_executed'])
        self.assertNotIn('fixture-api-key',json.dumps(requests))
        self.assertFalse(requests[0]['store'])

    def test_reasoning_and_function_result_are_carried_forward(self):
        requests=[]
        def fake(payload):
            requests.append(deepcopy(payload))
            if len(requests)==1:return {'output':[{'type':'reasoning','encrypted_content':'fixture-encrypted'},call()]}
            return answer()
        report=AssistantSession(config(),transport=fake).chat('有哪些功能')
        self.assertEqual(requests[1]['input'][1]['encrypted_content'],'fixture-encrypted')
        self.assertEqual(requests[1]['input'][-1]['type'],'function_call_output')
        self.assertEqual(report['tool_trace'][0]['tool'],'get_project_capabilities')

    def test_native_tool_is_never_callable(self):
        steps=iter([{'output':[call('execute_native',{'path':'do-not-write.sldprt'})]},answer('不能自动执行')])
        requests=[]
        def fake(payload):requests.append(deepcopy(payload));return next(steps)
        report=AssistantSession(config(),transport=fake).chat('修改原件')
        self.assertEqual(report['tool_trace'][0]['status'],'rejected')
        self.assertIn('tool_not_allowed',requests[1]['input'][-1]['output'])
        self.assertFalse(report['native_write_allowed'])

    def test_mechanical_kernel_reused(self):
        inputs={'driver':{'value':10,'unit':'count','source':'fixture'},'driven':{'value':20,'unit':'count','source':'fixture'}}
        result=call_readonly_tool('calculate_mechanics',{'kind':'ratio','inputs_json':json.dumps(inputs)})
        self.assertEqual(result['calculation']['results']['output_input_ratio'],.5)
        self.assertFalse(result['engineering_approved'])

    def test_review_request_remains_unapproved(self):
        r=call_readonly_tool('review_roller_instruction',{'text':'把滚筒总长改成800 mm，轴径不变，两端安装结构不变。'})
        self.assertEqual(r['parsed']['target_overall_mm'],800);self.assertFalse(r['native_write_allowed'])

    def test_tool_schema_has_no_writer_and_is_strict(self):
        schemas=tool_definitions()
        self.assertEqual(len(schemas),3)
        for item in schemas:
            self.assertTrue(item['strict']);self.assertFalse(item['parameters']['additionalProperties'])
            self.assertEqual(set(item['parameters']['required']),set(item['parameters']['properties']))

    def test_extra_arguments_refused(self):
        with self.assertRaises(ValueError):call_readonly_tool('get_project_capabilities',{'path':'not-read'})

    def test_tool_budget_prevents_execution(self):
        with patch('ai_assistant.session.call_readonly_tool') as tool:
            session=AssistantSession(config(),transport=lambda payload:{'output':[call()]},max_tool_calls=0)
            with self.assertRaises(AssistantError):session.chat('test')
            tool.assert_not_called()

    def test_round_budget(self):
        session=AssistantSession(config(),transport=lambda payload:{'output':[call()]},max_rounds=1)
        with self.assertRaises(AssistantError):session.chat('test')
        self.assertEqual(session.history,[])

    def test_cancel_before_network(self):
        from unittest.mock import Mock
        transport=Mock();cancel=threading.Event();cancel.set()
        with self.assertRaises(AssistantError):AssistantSession(config(),transport=transport).chat('test',cancel=cancel)
        transport.assert_not_called()

    def test_cancel_after_network_blocks_tools(self):
        cancel=threading.Event()
        def fake(payload):cancel.set();return {'output':[call()]}
        with patch('ai_assistant.session.call_readonly_tool') as tool:
            with self.assertRaises(AssistantError):AssistantSession(config(),transport=fake).chat('test',cancel=cancel)
            tool.assert_not_called()

    def test_incomplete_text_not_reported_passed(self):
        out=AssistantSession(config(),transport=lambda payload:answer('部分建议','incomplete')).chat('test')
        self.assertEqual(out['status'],'degraded');self.assertTrue(out['incomplete'])

    def test_malformed_or_empty_response(self):
        for response in ({'output':[]},{'output':['invalid']},{'output':[{'type':'message','content':'invalid'}]}):
            with self.assertRaises(AssistantError):AssistantSession(config(),transport=lambda payload:response).chat('test')

    def test_unknown_tool_does_not_interpret_python(self):
        with self.assertRaises(ValueError):call_readonly_tool('shell',{'code':'print(1)'})

    def test_history_is_bounded_and_can_clear(self):
        session=AssistantSession(config(),transport=lambda payload:answer())
        for i in range(10):session.chat(str(i))
        self.assertEqual(len(session.history),12);session.clear();self.assertEqual(session.history,[])
