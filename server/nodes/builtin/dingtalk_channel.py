"""
DingTalkChannel 节点 — 钉钉通道监听器

基于钉钉 Stream 模式（WebSocket）接收消息，不需要公网回调地址。
使用钉钉官方 Python SDK（dingtalk-stream）。

依赖: dingtalk-stream（pip install dingtalk-stream）
协议: 钉钉 Stream Mode（WebSocket 长连接）

工作流模式: listener
用法:
    {"id": "dingtalk_1", "type": "dingtalk_channel",
     "config": {"client_id": "dingxxx", "client_secret": "xxx"}}
"""
import asyncio
import json
import threading

from server.nodes.base import NodeInput, NodeOutput, ListenerNode
from server.nodes.registry import node


@node(
    "dingtalk_channel",
    version="1.0.0",
    icon="📌",
    color="#1677FF",
    author="videofactory",
)
class DingTalkChannelNode(ListenerNode):
    """钉钉通道 — 基于 Stream 模式收发消息

    通过钉钉 Stream SDK 建立 WebSocket 长连接，
    无需公网 IP/域名，无需内网穿透。
    支持: 机器人消息回调、事件订阅回调、卡片回调。
    """

    label = "钉钉通道"
    category = "监听器"
    description = "钉钉机器人消息收发，基于 Stream 模式（WebSocket），无需公网回调"
    bidirectional = True

    inputs = [
        NodeInput(name="reply", type="Reply", label="回复内容",
                  connected=True, required=False,
                  description="来自下游节点的回复"),
    ]

    outputs = [
        NodeOutput(name="message", type="Message", label="收到的消息",
                   description="包含 text/conversation_id/sender_staff_id 等字段"),
    ]

    config_schema = {
        "client_id": {
            "type": "string",
            "label": "Client ID (AppKey)",
            "default": "",
            "description": "钉钉应用 AppKey（企业内部应用 = 旧称 AppKey）",
        },
        "client_secret": {
            "type": "string",
            "label": "Client Secret (AppSecret)",
            "default": "",
            "description": "钉钉应用 AppSecret",
        },
    }

    async def prepare(self, ctx):
        """验证配置"""
        client_id = self.get_config("client_id", "")
        client_secret = self.get_config("client_secret", "")

        if not client_id or not client_secret:
            ctx.logger.error("client_id 和 client_secret 必须配置")
            raise ValueError("钉钉应用凭证未配置")

        self._client_id = client_id
        self._client_secret = client_secret
        self._dingtalk_client = None
        self._emit_callback = None
        ctx.logger.info("DingTalkChannel 初始化完成")

    async def listen(self, ctx, emit):
        """通过钉钉 Stream WebSocket 接收消息"""
        try:
            from dingtalk_stream import DingTalkStreamClient, ChatbotHandler, AckMessage
        except ImportError:
            ctx.logger.error("缺少依赖: dingtalk-stream. 请运行 pip install dingtalk-stream")
            return

        self._emit_callback = emit
        self._ctx = ctx

        # 创建自定义消息处理器
        node_self = self

        class _DingTalkHandler(ChatbotHandler):
            """钉钉消息处理器"""

            async def process(self, callback):
                """处理收到的机器人消息"""
                try:
                    # 提取消息内容
                    message = callback.message
                    text = ""
                    if hasattr(message, 'text') and message.text:
                        text = message.text.content or ""

                    parsed = {
                        "text": text,
                        "conversation_id": getattr(message, 'conversation_id', ''),
                        "sender_staff_id": getattr(message, 'sender_staff_id', ''),
                        "sender_nick": getattr(message, 'sender_nick', ''),
                        "chatbot_user_id": getattr(message, 'chatbot_user_id', ''),
                        "msg_id": getattr(message, 'msg_id', ''),
                        "create_at": getattr(message, 'create_at', ''),
                        "conversation_type": getattr(message, 'conversation_type', ''),
                        "raw": {
                            "conversation_id": getattr(message, 'conversation_id', ''),
                            "sender_staff_id": getattr(message, 'sender_staff_id', ''),
                            "msg_id": getattr(message, 'msg_id', ''),
                        },
                    }

                    ctx.logger.info(
                        f"收到钉钉消息: sender={parsed['sender_nick']}, "
                        f"text={text[:50]}"
                    )

                    # 调用 emit 触发下游
                    if node_self._emit_callback:
                        await node_self._emit_callback(parsed)

                    # 保存 callback 供 send_reply 使用
                    node_self._last_callback = callback

                    return AckMessage.STATUS_OK

                except Exception as e:
                    ctx.logger.error(f"钉钉消息处理异常: {e}")
                    return AckMessage.STATUS_FAILED

        # 创建客户端
        self._dingtalk_client = DingTalkStreamClient(
            self._client_id,
            self._client_secret,
        )
        self._dingtalk_client.register_callback(_DingTalkHandler())

        ctx.logger.info("DingTalkChannel 开始监听消息（Stream WebSocket 模式）")

        # start_forever() 是阻塞调用，放到线程中运行
        stop_event = asyncio.Event()

        def _run_stream():
            try:
                self._dingtalk_client.start_forever()
            except Exception as e:
                ctx.logger.error(f"钉钉 Stream 异常: {e}")
            finally:
                asyncio.run_coroutine_threadsafe(
                    stop_event.set(), asyncio.get_event_loop()
                )

        stream_thread = threading.Thread(target=_run_stream, daemon=True)
        stream_thread.start()

        await stop_event.wait()
        ctx.logger.info("DingTalkChannel 监听结束")

    async def send_reply(self, ctx, reply_data):
        """通过钉钉 API 发送回复"""
        # reply_data 可能是字符串或 dict
        if isinstance(reply_data, dict):
            text = reply_data.get("text", str(reply_data))
        else:
            text = str(reply_data)

        # 使用保存的 callback 回复
        callback = getattr(self, '_last_callback', None)
        if callback and hasattr(callback, 'reply'):
            try:
                await callback.reply(text)
                ctx.logger.info(f"钉钉回复发送成功")
            except Exception as e:
                ctx.logger.error(f"钉钉回复发送异常: {e}")
        else:
            ctx.logger.warning("无法发送钉钉回复：没有可用的 callback 上下文")

    async def finalize(self, ctx, success):
        """清理资源"""
        # 钉钉 SDK 的客户端在 daemon 线程中运行，主进程退出时自动终止
        ctx.logger.info("DingTalkChannel 已停止")
