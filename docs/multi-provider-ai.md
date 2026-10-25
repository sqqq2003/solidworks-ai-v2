# 可切换的模型服务接入

在PR55的7a8987e173bb8667274eecf2d5729d0161b16260上复用现有对话/白名单工具/审核/超时/取消逻辑，只增加协议适配和连接配置。原生测试分支不移动。

## 支持范围

| 协议 | 连接方式 | 范围 |
|---|---|---|
| OpenAI Responses | 基础地址 + /responses | 保留原始适配和推理项续传 |
| OpenAI兼容 Chat Completions | 基础地址 + /chat/completions | DeepSeek、其他兼容网关和本地服务；转换messages/tool_calls/tool结果，保留工具续轮reasoning_content |
| Anthropic Messages | 基础地址 + /messages | Claude原生API风格，x-api-key与anthropic-version头；保留thinking/signature及tool_use/tool_result |
| Gemini generateContent | 基础地址 + /models/{模型}:generateContent | Gemini Developer API原生风格，x-goog-api-key头；保留thoughtSignature和函数调用关联信息 |

内置地址预设：OpenAI、DeepSeek、Claude、Gemini、Ollama本机11434、LM Studio本机1234；模型名称必须由用户填写，不猜测账号可用型号。通义/Qwen、Kimi/Moonshot、智谱/GLM等如果提供OpenAI兼容接口，可以选兼容协议并填其控制台基础地址与模型；**没有逐厂实连验证**。

这不是“任意API零配置”：Azure专有路由、Bedrock签名、Vertex OAuth、第三方私有格式及额外厂商参数尚未支持。新增协议可在ai_assistant/protocols.py适配请求/响应，并在client中定义认证/地址；不需要重写工程工具或UI执行器。

## 桌面

`python app.py` → AI连接：
1. 选服务预设，或自定义协议/基础地址。
2. 填当前服务的模型和API密钥。
3. 模型不支持函数调用时取消“启用受控工具”，仅做文字对话；不自动降级或替你开放工具。
4. 兼容接口可选择max_tokens或max_completion_tokens额度字段，匹配服务文档。
5. 启用连接。只完成配置，首次对话才验证网络、权限与格式。

更换服务/协议不自动沿用旧密钥；只有相同协议与基础地址的当前连接或环境配置才可复用。密钥仅在内存/环境变量，不写项目、日志或提示词。切换连接重置模型上下文，旧对话仍在界面显示但不会自动发送给另一家服务。

远程服务需要HTTPS；本机localhost/127.0.0.1/::1允许HTTP及空密钥。远程无密钥拒绝。禁止URL认证信息、查询参数、片段和跨地址重定向。使用本机服务时仍沿用系统代理配置，必要时由操作者正确配置本机NO_PROXY。

基础地址可含/v1等厂商路径，按其文档填写，不强行补/v1。Responses/Chat/Messages也接受完整操作地址；Gemini只接受基础路径和标准models/{id}模型名。

## API与环境变量

旧调用`AIConfig(model, api_key)`及OPENAI_MODEL/OPENAI_API_KEY继续工作。新增字段：protocol、base_url、enable_tools、token_parameter。`ModelClient`是原ResponsesClient的兼容别名。会话API与工程工具不变。

通用环境变量：AI_PROTOCOL、AI_BASE_URL、AI_MODEL、AI_API_KEY、AI_ENABLE_TOOLS（true/false）、AI_TOKEN_PARAMETER。默认responses；Anthropic/Gemini可分别回退到ANTHROPIC_MODEL/ANTHROPIC_API_KEY、GEMINI_MODEL/GEMINI_API_KEY。切换CLI服务时应同步设置对应模型与密钥。

```powershell
$env:AI_PROTOCOL='chat_completions'
$env:AI_BASE_URL='https://api.deepseek.com'
$env:AI_MODEL='<控制台实际模型名称>'
# 在本机配置AI_API_KEY，不写进项目或测试证据。
python work/ai_assistant.py status
python work/ai_assistant.py chat --request examples/ai-design-request.json --out <新回复文件>
```

本机Ollama用http://localhost:11434/v1、LM Studio用http://localhost:1234/v1和本机实际模型名。模型没有工具能力时设置AI_ENABLE_TOOLS=false。status仅报告配置，不发请求，也不声称连接通过。

连接地址只由操作者设置，模型无法改变服务地址、密钥、工具开关或原生权限。无CAD文件读取/自动上传，无shell、COM和写模型工具；模型输出仍是待工程审核建议。

## 验证

- 保留21项初版API检查，新增17项协议检查：四类格式、工具续轮、签名/推理状态保留、认证头、Gemini无ID调用、工具关闭、地址/模型/密钥隔离等。全部通过，使用假HTTP。
- Linux虚拟桌面8项交互检查通过，新增跨服务密钥不沿用检查；不调用真实模型服务。
- 离线集成833运行/821通过/12跳过/0失败错误。12跳过含原4项夹具/转换器及无显示环境8项GUI；8项GUI已另在系统Tk8.6虚拟显示实际通过。

没有任何厂商API密钥或本机模型服务，真实OpenAI/兼容服务/Claude/Gemini/Ollama/LM Studio连接全部not_run。不能把模拟协议检查当作每家已接通。按delivery/multi-provider-ai/windows-matrix.json用操作者自己的配置集中复验，不中断#53/#54/#55当前任务。

协议参考：[DeepSeek](https://api-docs.deepseek.com/)、[Claude工具格式](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)、[Gemini generateContent](https://ai.google.dev/api/generate-content)、[Ollama兼容接口](https://docs.ollama.com/api/openai-compatibility)。
