# OpenAI 接入与 Gork 验证

> 本页记录PR55的OpenAI初版。后续通用服务地址、Claude/Gemini和本地模型配置，请以 [多服务接入](multi-provider-ai.md) 为准。

基于界面PR54的48d5fb2e451d321d5c8f886f7d50a044c5612498增量开发；原界面/统一实机测试pin不移动。当前ChatGPT会话不是软件的远程后端，这里接入的是操作者自己配置的OpenAI API模型。

## 桌面启用

1. `python app.py`，左侧点“AI 连接”。
2. 填写账号可访问、支持Responses及工具调用的模型名称。模型不硬编码。
3. API密钥可在窗口中填写，或从本机OPENAI_API_KEY读取。留空可沿用本次进程的已有连接。界面输入遮罩，不把密钥存入配置文件、项目、提示词或日志。
4. 点“启用 OpenAI”。此时只完成配置，首次提交对话才真正验证网络/权限。
5. 输入文字，Ctrl+Enter提交；按钮可请求停止。正在进行的HTTP请求最多等待配置的超时，停止后不继续工具轮次。新任务丢弃旧任务的迟到回复。

默认保持“本地审核”，即使环境变量存在也不自动联网；随时可切回本地。OpenAI回复始终标“AI建议·待工程审核”。对话不自动加入CAD执行队列，审核请求的保存也不表示批准模型修改。

## 命令行/API

无需新增SDK依赖，使用Python标准库HTTPS，固定访问`https://api.openai.com/v1/responses`，不接受模型指定URL或其他主机。

在本机配置OPENAI_API_KEY（通过窗口填写更直接）以及OPENAI_MODEL后：

```powershell
python work/ai_assistant.py status
python work/ai_assistant.py tools
python work/ai_assistant.py chat --request examples/ai-design-request.json --out <新的回复JSON路径>
```

status只返回是否已配置等公开信息，connection_verified保持false，不能把“存在密钥”当作联网通过。chat的正常返回仍是review_required/退出3。没有密钥/模型时明确提示，不降级伪装成远程回复。输出文件必须不存在。

API：`AIConfig.from_env()`、`AssistantSession(config).chat(text, cancel=threading.Event())`。可注入`transport`做假HTTP测试；真实默认transport是ResponsesClient。配置对象repr隐藏密钥；不要自行用asdict序列化配置。

## 工具与数据范围

只开放三个工具：
- get_project_capabilities：复用已有项目能力清单。
- calculate_mechanics：复用现有11类机械计算，参数必须带单位和来源；结果为初算且要求人工核对输入/适用条件。
- review_roller_instruction：复用已有受限中文滚筒指令解析，生成未批准的审核请求。

没有任意文件读取、shell、COM附着、进程控制、原生建模或批准工具。模型请求任何其他工具会得到拒绝结果。没有把模型文本转换成代码执行。

发送内容是输入文字、最近6轮本地对话、当轮工具数据。附件/CAD/图纸/项目JSON和本机日志**不会自动读取或上传**；需要模型分析的数据应由操作者明确提供。请求设置store=false，用本地历史维护上下文，不使用服务端previous_response_id；工具续轮保留需要的响应/推理项。工具审计记录名称、参数和结果摘要哈希，不记录HTTP授权头或密钥。

单次输入最多8000字，输出默认2048 tokens，最多4轮/6次工具调用；HTTP默认45秒超时，无自动付费重试。响应过大、错误、拒绝或不完整会明确返回，不能报CAD/实机成功。模型仍可能提出不正确建议，机械验收由既有审核、原生读回与工程师完成。

协议依据：官方[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)和[Function calling](https://developers.openai.com/api/docs/guides/function-calling)。实现使用严格函数schema，并按官方续轮契约回传function_call_output与关联call_id；没有把同一ChatGPT会话或登录态打包进桌面软件。

## 验证与当前限制

- 21项假HTTP/本地核心检查通过：请求格式、密钥不进入公开状态/提示词、HTTP错误脱敏、重定向拒绝、只读工具白名单、推理项续传、预算/取消/历史、不完整回复等。
- Linux系统Tk8.6虚拟显示下7项GUI检查通过，含后台回复、无原生写入和新任务忽略迟到回复。没有使用真实API密钥、没有真实模型服务调用、没有SolidWorks运行。
- 集成回归815项运行：804通过、11跳过、0失败/错误；11跳过是原4项本机夹具/转换器及无显示环境的7项GUI，后7项另在虚拟显示通过。结果见delivery/ai-assistant/validation.json。

首版为非流式回复，线程等待时UI保持响应；不支持实时语音、图片/CAD上传、任意模型工具或全功能Codex代理。真实API权限/模型参数、账单额度、代理网络、Windows字体/DPI以及原生审核仍待本机验证。

Gork先在无密钥环境确认本地模式正常，再用假HTTP测试；操作者自行在本机配置API后做一次普通对话和一次明确数字的机械计算，检查结果、工具trace、取消/新任务行为及未写原件。没有可用API时标review_required，不使用假响应声称联网通过。统一回传实际SHA和结果，不上传密钥/授权头/客户CAD。旧#53/#54测试继续，不因本批切换正在运行的原生队列。
