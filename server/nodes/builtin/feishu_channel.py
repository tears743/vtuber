"""
FeishuChannel 节点 — 飞书通道监听器

基于飞书 WebSocket 长连接接收消息，不需要公网回调地址。
使用飞书官方 Python SDK（lark-oapi）的 WebSocket 模式。

依赖: lark-oapi（pip install lark-oapi）
协议: 飞书长连接（WebSocket 全双工通道）

工作流模式: listener
用法:
    {"id": "feishu_1", "type": "feishu_channel", "config": {"app_id": "cli_xxx", "app_secret": "xxx"}}
"""
import asyncio
import json
import threading

from server.nodes.base import NodeInput, NodeOutput, ListenerNode
from server.nodes.registry import node


@node(
    "feishu_channel",
    version="1.0.0",
    icon="🐦",
    color="#00D6B9",
    author="videofactory",
)
class FeishuChannelNode(ListenerNode):
    """飞书通道 — 基于 WebSocket 长连接收发消息

    通过飞书 SDK 建立全双工 WebSocket 通道，
    无需公网 IP/域名，无需内网穿透。
    仅支持企业自建应用。
    """

    label = "飞书通道"
    category = "监听器"
    description = "飞书机器人消息收发，基于 WebSocket 长连接，无需公网回调"
    bidirectional = True

    inputs = [
        NodeInput(name="reply", type="Reply", label="回复内容",
                  connected=True, required=False,
                  description="来自下游节点的回复"),
    ]

    outputs = [
        NodeOutput(name="message", type="Message", label="收到的消息",
                   description="包含 text/chat_id/message_id/sender 等字段"),
    ]

    config_schema = {
        "app_id": {
            "type": "string",
            "label": "App ID",
            "default": "",
            "description": "飞书应用 App ID（格式: cli_xxxxxxxx）",
        },
        "app_secret": {
            "type": "string",
            "label": "App Secret",
            "default": "",
            "description": "飞书应用 App Secret",
        },
    }

    async def prepare(self, ctx):
        """验证配置"""
        app_id = self.get_config("app_id", "")
        app_secret = self.get_config("app_secret", "")

        if not app_id or not app_secret:
            ctx.logger.error("app_id 和 app_secret 必须配置")
            raise ValueError("飞书应用凭证未配置")

        self._app_id = app_id
        self._app_secret = app_secret
        self._lark_client = None
        self._ws_client = None
        self._emit_callback = None
        ctx.logger.info("FeishuChannel 初始化完成")

    async def listen(self, ctx, emit):
        """通过飞书 WebSocket 长连接接收消息"""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError:
            ctx.logger.error("缺少依赖: lark-oapi. 请运行 pip install lark-oapi")
            return

        self._emit_callback = emit
        self._ctx = ctx

        # 创建 Lark API Client（用于发送回复）
        self._lark_client = lark.Client.builder() \
            .app_id(self._app_id) \
            .app_secret(self._app_secret) \
            .build()

        # 创建事件处理器
        event_handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_message_receive) \
            .build()

        # 创建并启动 WebSocket 客户端
        self._ws_client = lark.ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        ctx.logger.info("FeishuChannel 开始监听消息（WebSocket 长连接）")

        # ws_client.start() 是阻塞调用，放到线程中运行
        # 通过 asyncio.Event 控制生命周期
        stop_event = asyncio.Event()

        def _run_ws():
            try:
                self._ws_client.start()
            except Exception as e:
                ctx.logger.error(f"飞书 WebSocket 异常: {e}")
            finally:
                # 通知主协程
                asyncio.run_coroutine_threadsafe(stop_event.set(), asyncio.get_event_loop())

        ws_thread = threading.Thread(target=_run_ws, daemon=True)
        ws_thread.start()

        # 等待停止信号
        await stop_event.wait()
        ctx.logger.info("FeishuChannel 监听结束")

    def _on_message_receive(self, data) -> None:
        """飞书消息接收回调（在 SDK 线程中调用）"""
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # 解析消息内容
            content_str = message.content if isinstance(message.content, str) else "{}"
            try:
                content = json.loads(content_str)
            except json.JSONDecodeError:
                content = {}

            text = content.get("text", "")

            parsed = {
                "text": text,
                "chat_id": message.chat_id,
                "message_id": message.message_id,
                "message_type": message.message_type,
                "sender_id": sender.sender_id.open_id if sender and sender.sender_id else "",
                "sender_name": sender.sender_id.name if sender and sender.sender_id else "",
                "raw": {
                    "chat_id": message.chat_id,
                    "message_id": message.message_id,
                    "message_type": message.message_type,
                    "content": content,
                },
            }

            self._ctx.logger.info(
                f"收到飞书消息: chat={parsed['chat_id']}, "
                f"sender={parsed['sender_name']}, text={text[:50]}"
            )

            # 调用 emit（需要跨线程调度到 asyncio）
            if self._emit_callback:
                future = asyncio.run_coroutine_threadsafe(
                    self._emit_callback(parsed),
                    asyncio.get_event_loop(),
                )
                future.result(timeout=30)  # 等待下游处理完成（3秒内）

        except Exception as e:
            self._ctx.logger.error(f"飞书消息处理异常: {e}")

    async def send_reply(self, ctx, reply_data):
        """通过飞书 API 发送回复"""
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest, CreateMessageRequestBody,
            )
        except ImportError:
            ctx.logger.error("缺少依赖: lark-oapi")
            return

        # reply_data 可能是字符串或 dict
        if isinstance(reply_data, dict):
            text = reply_data.get("text", str(reply_data))
            chat_id = reply_data.get("chat_id", "")
            reply_msg_id = reply_data.get("message_id", "")
        else:
            text = str(reply_data)
            chat_id = ""
            reply_msg_id = ""

        if not chat_id:
            ctx.logger.error("飞书回复缺少 chat_id")
            return

        # 构建消息内容
        content = json.dumps({"text": text})

        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(content)
                .build()
            ).build()

        response = self._lark_client.im.v1.message.create(request)

        if response.success():
            ctx.logger.info(f"飞书回复发送成功: chat={chat_id}")
        else:
            ctx.logger.error(
                f"飞书回复发送失败: code={response.code}, msg={response.msg}"
            )

    async def finalize(self, ctx, success):
        """清理资源"""
        # 飞书 SDK 的 WebSocket 客户端没有显式的 stop 方法
        # 线程是 daemon=True，主进程退出时自动终止
        ctx.logger.info("FeishuChannel 已停止")
