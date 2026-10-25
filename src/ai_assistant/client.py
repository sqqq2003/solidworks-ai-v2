"""Configurable model transport; keys never enter public reports or prompts."""
from dataclasses import dataclass,field
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit,quote
import ipaddress
import re
from .protocols import BASES

ENDPOINT='https://api.openai.com/v1/responses'

class AssistantError(RuntimeError):pass


@dataclass(frozen=True)
class AIConfig:
    model:str
    api_key:str=field(repr=False)
    timeout_seconds:float=45
    max_output_tokens:int=2048
    protocol:str="responses"
    base_url:str=""
    enable_tools:bool=True
    token_parameter:str="max_tokens"

    @classmethod
    def from_env(cls):
        protocol=os.environ.get('AI_PROTOCOL','responses').strip()
        prefix={'anthropic':'ANTHROPIC','gemini':'GEMINI'}.get(protocol,'OPENAI')
        tools=os.environ.get('AI_ENABLE_TOOLS','true').lower()
        if tools not in {'true','false','1','0'}:raise AssistantError('AI_ENABLE_TOOLS 只能为 true/false。')
        return cls(model=os.environ.get('AI_MODEL',os.environ.get(prefix+'_MODEL','')).strip(),
                   api_key=os.environ.get('AI_API_KEY',os.environ.get(prefix+'_API_KEY','')).strip(),
                   protocol=protocol,base_url=os.environ.get('AI_BASE_URL',os.environ.get('OPENAI_BASE_URL','') if protocol in {'responses','chat_completions'} else '').strip(),
                   enable_tools=tools in {'true','1'},token_parameter=os.environ.get('AI_TOKEN_PARAMETER','max_tokens'))

    def validate(self):
        if not isinstance(self.model,str) or not self.model.strip():raise AssistantError('请在本机设置 AI_MODEL 或填写模型名称。')
        self.normalized_base()
        if not isinstance(self.api_key,str) or (not self.api_key.strip() and not self.is_local()):raise AssistantError('请配置当前服务的 API 密钥。')
        if '\r' in self.api_key or '\n' in self.api_key:raise AssistantError('API 密钥格式不正确。')
        if type(self.enable_tools) is not bool:raise AssistantError('工具开关必须是布尔值。')
        if self.token_parameter not in {'max_tokens','max_completion_tokens'}:raise AssistantError('不支持的输出额度字段。')
        if self.protocol=='gemini' and not re.fullmatch(r'(?:models/)?[a-zA-Z0-9._-]+',self.model):raise AssistantError('Gemini 模型名称格式不正确。')
        if type(self.timeout_seconds) not in (int,float) or not 1<=self.timeout_seconds<=120:raise AssistantError('请求超时须在 1–120 秒之间。')
        if type(self.max_output_tokens) is not int or not 128<=self.max_output_tokens<=8192:raise AssistantError('输出额度须在 128–8192 tokens 之间。')

    def normalized_base(self):
        if self.protocol not in BASES:raise AssistantError('不支持的 API 协议。')
        value=(self.base_url or BASES[self.protocol]).rstrip('/')
        try:
            parts=urlsplit(value);port=parts.port
        except ValueError:raise AssistantError('API 服务地址或端口无效。') from None
        try:local=ipaddress.ip_address(parts.hostname or '').is_loopback
        except ValueError:local=parts.hostname=='localhost'
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or any(c.isspace() for c in value):raise AssistantError('API 基础地址无效；不能包含认证信息、查询参数或片段。')
        if parts.scheme!='https' and not (parts.scheme=='http' and local):raise AssistantError('远程服务须使用 HTTPS；本机回环服务可使用 HTTP。')
        return value

    def is_local(self):
        host=urlsplit(self.normalized_base()).hostname
        try:return ipaddress.ip_address(host).is_loopback
        except ValueError:return host=='localhost'

    def secret_scope(self):return self.protocol,self.normalized_base()

    def endpoint(self):
        base=self.normalized_base()
        if self.protocol=='gemini':return base+'/models/'+quote(self.model.removeprefix('models/'),safe='')+':generateContent'
        suffix={'responses':'/responses','chat_completions':'/chat/completions','anthropic':'/messages'}[self.protocol]
        return base if base.endswith(suffix) else base+suffix

    def public_status(self):
        return {'protocol':self.protocol,'server':urlsplit(self.normalized_base()).netloc,'tools_enabled':self.enable_tools,'model':self.model,'key_configured':bool(self.api_key),'model_configured':bool(self.model),
                'connection_verified':False,'key_storage':'process_memory_or_environment_only'}


def scoped_api_key(target, explicit='', candidates=()):
    """Never carry an existing/environment secret to a different protocol/server."""
    if explicit.strip():return explicit.strip()
    scope=target.secret_scope()
    for candidate in candidates:
        if candidate is not None and candidate.secret_scope()==scope:return candidate.api_key
    return ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise AssistantError('API 返回了重定向，连接已停止。')


class ResponsesClient:
    def __init__(self,config,*,opener=None):
        config.validate();self.config=config
        self.opener=opener or urllib.request.build_opener(NoRedirect())

    def __call__(self,payload):
        from .protocols import to_wire,from_wire
        body=json.dumps(to_wire(payload,self.config),ensure_ascii=False,allow_nan=False).encode('utf-8')
        if len(body)>262144:raise AssistantError('对话过长，请新建设计任务。')
        headers={'Content-Type':'application/json'}
        if self.config.protocol=='anthropic':
            headers['anthropic-version']='2023-06-01'
            if self.config.api_key:headers['x-api-key']=self.config.api_key
        elif self.config.protocol=='gemini':
            if self.config.api_key:headers['x-goog-api-key']=self.config.api_key
        elif self.config.api_key:headers['Authorization']='Bearer '+self.config.api_key
        request=urllib.request.Request(self.config.endpoint(),data=body,headers=headers,method='POST')
        try:
            with self.opener.open(request,timeout=self.config.timeout_seconds) as response:
                raw=response.read(2097153)
                if len(raw)>2097152:raise AssistantError('API 响应过大，本次回复已停止。')
                value=json.loads(raw.decode('utf-8'))
        except urllib.error.HTTPError as exc:
            messages={400:'模型、接口协议或参数不受支持，请检查连接配置和工具开关。',404:'模型名称或 API 资源不存在，请检查本机模型配置。',401:'API 密钥未通过验证，请检查本机配置。',403:'此项目或模型暂不可访问。',429:'请求额度或速率受限，请检查 API 项目后重试。'}
            raise AssistantError(messages.get(exc.code,'API 服务暂不可用，请稍后重试。')) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise AssistantError('无法连接模型服务，或请求超时；请检查网络和本机配置。') from None
        except (ValueError,UnicodeError):raise AssistantError('API 返回了无法解析的响应。') from None
        if not isinstance(value,dict):raise AssistantError('API 响应格式不正确。')
        if value.get('status') in {'failed','cancelled'} or value.get('error'):
            raise AssistantError('模型未完成本次请求，请稍后重试。')
        try:return from_wire(value,self.config.protocol)
        except (ValueError,KeyError,TypeError,IndexError,AttributeError):raise AssistantError('服务响应与所选 API 协议不匹配。') from None
