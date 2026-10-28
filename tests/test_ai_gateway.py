import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from src.ai_gateway import Gateway
from work.ai_gateway import rpc, stdio, handler

EXPECTED_TOOLS = {
    'solidworks_capabilities', 'solidworks_doctor', 'solidworks_run_job',
    'solidworks_batch_review', 'solidworks_skill_integration',
    'solidworks_review_execution_plan',
}


def discovered_names(rows):
    names = [row['name'] for row in rows]
    if len(names) != len(set(names)):
        raise AssertionError('duplicate tool names in transport discovery')
    return set(names)

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls = []
        def execute(job):
            self.calls.append(job)
            return {'status':'planned','events':[],'cad_verified':False}
        self.gateway = Gateway(self.root,execute=execute)
    def tearDown(self):
        self.temp.cleanup()
    def test_discover_without_cad_and_job_report(self):
        capabilities = self.gateway.call('solidworks_capabilities',{})
        self.assertFalse(capabilities['native_enabled'])
        self.assertFalse(capabilities['session_policy']['attach_user_session'])
        self.assertEqual(capabilities['session_policy']['fallback_on_isolation_failure'],'refuse')
        result = self.gateway.call('solidworks_run_job',{'job':{'kind':'parametric','machine':'GT-ZX','length':100,'width':80,'height':60}})
        self.assertEqual(result['status'],'planned')
        self.assertTrue((self.root/result['report']).is_file())
        self.assertEqual(len(self.calls),1)
    def test_reject_escape_and_injection(self):
        for path in ('../outside.dxf',str(self.root/'absolute.dxf')):
            with self.assertRaises(ValueError):
                self.gateway.call('solidworks_run_job',{'job':{'kind':'sheet','source':path}})
        with self.assertRaises(ValueError):
            self.gateway.call('solidworks_run_job',{'job':{'kind':'turned','sw_exe':'evil.exe'}})
        self.assertFalse(self.calls)
    def test_native_disabled_and_busy(self):
        with self.assertRaisesRegex(ValueError,'disabled'):
            self.gateway.call('solidworks_run_job',{'job':{'kind':'sheet','action':'generate'}})
        self.gateway.lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError,'busy'):
                self.gateway.call('solidworks_run_job',{'job':{'kind':'parametric','machine':'GT-ZX'}})
        finally:
            self.gateway.lock.release()
        self.assertFalse(self.calls)
    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            try:
                (self.root/'link').symlink_to(outside,target_is_directory=True)
            except OSError:
                self.skipTest('symlink unavailable')
            with self.assertRaises(ValueError):
                self.gateway.path('link/file.dxf')
    def test_mcp_line_transport_discovery_error_and_notifications(self):
        requests = [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'invalid'}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'solidworks_run_job','arguments':{'job':{'kind':'parametric','machine':'GT-ZX','length':100,'width':80,'height':60}}}}]
        source = io.BytesIO(('\n'.join(json.dumps(r) for r in requests)+'\n').encode())
        sink = io.StringIO()
        stdio(self.gateway,source,sink)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(len(responses),4)
        self.assertEqual(responses[0]['result']['protocolVersion'],'2024-11-05')
        self.assertEqual(discovered_names(responses[1]['result']['tools']), EXPECTED_TOOLS)
        self.assertTrue(responses[2]['result']['isError'])
        self.assertFalse(responses[3]['result']['isError'])
    def test_http_real_loopback_auth_and_job(self):
        token = 'a'*40
        server = ThreadingHTTPServer(('127.0.0.1',0),handler(self.gateway,token))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(base+'/v1/tools')
            self.assertEqual(error.exception.code,401)
            request = Request(base+'/v1/tools',headers={'Authorization':'Bearer '+token})
            with urlopen(request) as response:
                self.assertEqual(discovered_names(json.load(response)['tools']), EXPECTED_TOOLS)
            data = {'name':'solidworks_run_job','arguments':{'job':{'kind':'parametric','machine':'GT-ZX','length':100,'width':80,'height':60}}}
            request = Request(base+'/v1/tools/call',data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urlopen(request) as response:
                self.assertEqual(json.load(response)['status'],'planned')
            request = Request(base+'/v1/tools/call',data=b'[]',headers={'Authorization':'Bearer '+token})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code,400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    def test_parametric_cannot_pretend_native(self):
        with self.assertRaises(ValueError):
            self.gateway.call('solidworks_run_job',{'job':{'kind':'parametric','machine':'GT-ZX','action':'generate'}})
        self.assertFalse(self.calls)
    def test_native_confirmation_bound_to_host_and_input(self):
        source = self.root/'part.dxf'
        source.write_text('synthetic placeholder; native executor mocked')
        executable = self.root/'SLDWORKS.exe'
        executable.write_text('mock executable; never launched')
        gateway = Gateway(self.root,sw_exe=executable,execute=self.gateway.execute)
        result = gateway.call('solidworks_run_job',{'job':{'kind':'turned','action':'generate','source':'part.dxf','output':'part.SLDPRT','confirmed':True}})
        self.assertEqual(result['status'],'planned')
        job = self.calls[0]
        self.assertEqual(job['sw_exe'],str(executable))
        self.assertTrue(job['source_sha256'])
        from src.project_workbench import build_command
        source.write_text('changed after confirmation')
        with self.assertRaisesRegex(ValueError,'changed since review'):
            build_command(job)

    def test_ql_planning_uses_explicit_machine(self):
        result = Gateway(self.root).call('solidworks_run_job',{'job':{'kind':'parametric','machine':'QL-5050PX','length':1800,'width':900,'height':1500}})
        self.assertIn(result['status'],('review_required','pending_mapping'))
        self.assertFalse(result['cad_verified'])

    def test_real_offline_parameter_execution(self):
        result = Gateway(self.root).call('solidworks_run_job',{'job':{'kind':'parametric','machine':'GT-ZX','length':1000,'width':800,'height':600}})
        self.assertIn(result['status'],('planned','review_required'))
        self.assertFalse(result['cad_verified'])
        self.assertTrue(result['events'])

if __name__ == '__main__':
    unittest.main()
