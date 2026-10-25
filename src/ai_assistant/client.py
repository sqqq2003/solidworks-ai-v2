"""Small stateless Responses API transport. Keys never enter reports or prompts."""
from dataclasses import dataclass,field
import json
import os
import urllib.error
import urllib.request

ENDPOINT='https://api.openai.com/v1/responses'

class AssistantError(RuntimeError):pass


@dataclass(frozen=True)
class AIConfig:
    model:str
    api_key:str=field(repr=False)
    timeout_seconds:float=45
    max_output_tokens:int=2048

    @classmethod
    def from_env(cls):
        return cls(model=os.environ.get('OPENAI_MODEL','').strip(),api_key=os.environ.get('OPENAI_API_KEY','').strip())

    def validate(self):
        if not isinstance(self.model,str) or not self.model.strip():raise AssistantError('请在本机设置 OPENAI_MODEL 或填写模型名称。')
        if not isinstance(self.api_key,str) or not self.api_key.strip():raise AssistantError('请在本机配置 OpenAI API 密钥。')
        if type(self.timeout_seconds) not in (int,float) or not 1<=self.timeout_seconds<=120:raise AssistantError('请求超时须在 1–120 秒之间。')
        if type(self.max_output_tokens) is not int or not 128<=self.max_output_tokens<=8192:raise AssistantError('输出额度须在 128–8192 tokens 之间。')

    def public_status(self):
        return {'model':self.model,'key_configured':bool(self.api_key),'model_configured':bool(self.model),
                'connection_verified':False,'key_storage':'process_memory_or_environment_only'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise AssistantError('API 返回了重定向，连接已停止。')


class ResponsesClient:
    def __init__(self,config,*,opener=None):
        config.validate();self.config=config
        self.opener=opener or urllib.request.build_opener(NoRedirect())

    def __call__(self,payload):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if len(body)>262144:raise AssistantError('对话过长，请新建设计任务。')
        request=urllib.request.Request(ENDPOINT,data=body,headers={
            'Authorization':'Bearer '+self.config.api_key,'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(request,timeout=self.config.timeout_seconds) as response:
                raw=response.read(2097153)
                if len(raw)>2097152:raise AssistantError('API 响应过大，本次回复已停止。')
                value=json.loads(raw.decode('utf-8'))
        except urllib.error.HTTPError as exc:
            messages={400:'模型或参数不受支持，请检查所选模型是否支持 Responses 与工具调用。',404:'模型名称或 API 资源不存在，请检查本机模型配置。',401:'API 密钥未通过验证，请检查本机配置。',403:'此项目或模型暂不可访问。',429:'请求额度或速率受限，请检查 API 项目后重试。'}
            raise AssistantError(messages.get(exc.code,'API 服务暂不可用，请稍后重试。')) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise AssistantError('无法连接 OpenAI API，或请求超时；请检查网络和本机配置。') from None
        except (ValueError,UnicodeError):raise AssistantError('API 返回了无法解析的响应。') from None
        if not isinstance(value,dict):raise AssistantError('API 响应格式不正确。')
        if value.get('status') in {'failed','cancelled'} or value.get('error'):
            raise AssistantError('模型未完成本次请求，请稍后重试。')
        return value
