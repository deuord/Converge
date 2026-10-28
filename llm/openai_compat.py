# llm/openai_compat.py — OpenAI 兼容协议流式调用
# OpenAI SDK = "OpenAI 协议"的通用客户端。协议是指 /v1/chat/completions 这套
# 请求/响应格式,已成为事实标准:DeepSeek、mimo、通义、Kimi、Ollama、vLLM...
# 几乎所有国内外模型都实现这套协议,所以换个 base_url + api_key 就能切换供应商,
# 这就是"OpenAI 兼容"的含义——代码不用改,改的只是配置
from openai import AsyncOpenAI

from config.settings import get_settings


async def chat_stream(messages, model=None, tools=None):
    """流式调 LLM,逐段 yield delta 对象(async 生成器)

    model: models.yaml 里的模型别名,None 用默认模型
    tools: OpenAI function 定义列表,传给 API 让模型能发起 tool_calls(v2.3 用)
    """

    # ---------------- client:一个 HTTP 客户端实例,管连接的所有"外设" ----------------
    # AsyncOpenAI 内部包着 httpx.AsyncClient,常用参数:
    #   api_key:    鉴权头 Authorization: Bearer <key>,所有兼容供应商都认这套
    #   base_url:   服务器地址,默认 https://api.openai.com/v1;换供应商主要就换它
    #   timeout:    单次请求超时(秒),默认 600s。流式下"收到首字节前"和"字节间隔"
    #               都受它管,模型思考太久没吐字会抛 APITimeoutError
    #   max_retries: 429/5xx/网络错自动重试次数,默认 2 次(指数退避)。流已经开始
    #               吐字后不会重试——半截重放会导致内容重复
    # 每次调用新建 client 是最简单的写法;生产上常见做法是模块级复用一个 client,
    # 复用底层连接池(TCP/TLS 握手只做一次),这是后续可做的小优化
    mcfg = get_settings().get_model(model)
    client = AsyncOpenAI(api_key=mcfg.api_key, base_url=mcfg.base_url)

    # ---------------- create:对应 POST /v1/chat/completions 的请求体 ----------------
    # 常用参数(v1.0 用到的 + 之后会用到的,都在这认识一遍):
    #   model:        模型全名(发给服务端路由用),不是我们 yaml 里的别名
    #   messages:     对话历史,[{"role":"user","content":"..."}, ...]。
    #                 role 有三种:system(人设/规则)、user(用户)、assistant(AI 回复)。
    #                 服务端是无状态的,每轮都要把完整历史重发,上下文全靠这里拼
    #   stream:       True = SSE 流式,服务端边生成边推,客户端逐块收;
    #                 False = 等全部生成完一次性返回(阻塞久,桌面助手体验差)
    #   stream_options: 流式的附加开关。include_usage=True 让服务端在流末尾多发
    #                 一个空 choices 的 chunk,里面带本次 token 用量(计费用;
    #                 默认不发,所以要显式打开)
    #   tools:        function 定义列表,把"可以调用的工具"(如执行命令/读文件)
    #                 告诉模型。模型不直接执行,只是产出 tool_calls 结构说"我想
    #                 调 XX 工具、参数是 YY",由 runner 执行后把结果塞回 messages
    #                 再继续对话(v2.3 的 ReAct 循环靠它)
    #   tool_choice:  何时强制调工具:"auto"=模型自己决定(默认);
    #                 {"type":"function",...}=强制调指定函数;"none"=禁止调用
    #   temperature:  随机性 0~2,0≈稳定可复现,1≈发散。默认 1,一般不用动
    #   max_tokens:   本次回复最多生成多少 token,防止跑飞(如模型开始复读时截断)
    #   response_format: {"type":"json_object"} 强制返回 JSON(结构化输出用)
    # 注意各兼容供应商支持度不一:参数发了对方不认识会被忽略或报错,
    # 所以 v1.0 只发协议最通用的几个,别家的私有参数(如 mimo 的 thinking)
    # 不写死在这里,将来要开就进 models.yaml 按模型配置
    # 流式 create 要 await,返回 AsyncStream;异常时 stream 未赋值,finally 需要 None 兜底
    stream = None
    try:
        stream = await client.chat.completions.create(
            model=mcfg.model,  # 发给 API 的是模型全名,不是入参别名
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            tools=tools,
        )

        # ---------------- 读流:AsyncStream 像异步版的文件对象 ----------------
        # async for 每轮拿到一个 chunk(= 服务端一条 "data: {...}" 的 SSE 帧),
        # 结构:chunk.choices[0].delta —— 只有"增量",不是全文!
        #   delta.content:    文本增量,如 "你"、"好"。正常回复时有值
        #   delta.tool_calls: 工具调用增量(v2.3 用)。模型决定调工具时 content
        #                    为空,tool_calls 里有 name/arguments
        #   delta.reasoning_content: 思考模型(DeepSeek-R1 等)的推理过程增量
        # 流末尾服务端会发一个 finish_reason 标记(stop/tool_calls/length),
        # runner 将来靠它判断"正常结束还是被截断"
        async for chunk in stream:
            if not chunk.choices:  # usage 在末尾空 choices 的 chunk 上,v1.0 不统计 token,跳过
                continue
            yield chunk.choices[0].delta  # 整个 delta 交给 runner 解析

    # ---------------- 收尾:顺序不能反 ----------------
    # finally 而不是正常结束才关:调用方中途 break(用户取消/断连)时,
    # 生成器被关闭也会走到这,否则连接泄漏
    # 先关 SSE 流再关客户端:反过来会先拆掉底层连接,残留的字节流迭代器
    # 被 GC 强杀时报 PoolByteStream 的错
    finally:
        if stream is not None:
            await stream.close()
        await client.close()
