"""
WeChatChannel 节点 — 微信通道监听器

基于腾讯 iLink 协议，扫码登录后通过长轮询接收微信消息。
不需要公网回调地址。

依赖: aiohttp（pip install aiohttp）
协议: iLink Bot API（ilinkai.weixin.qq.com）

工作流模式: listener
用法:
    {"id": "wechat_1", "type": "wechat_channel", "config": {"bot_token": "..."}}
"""
import asyncio
import json

from server.nodes.base import NodeInput, NodeOutput, ListenerNode
from server.nodes.registry import node


@node(
    "wechat_channel",
    version="1.0.0",
    icon="💬",
    color="#07C160",
    author="videofactory",
)
class WeChatChannelNode(ListenerNode):
    """微信通道 — 基于 iLink 协议长轮询收发消息

    扫码登录后获取 bot_token，通过 getupdates 长轮询（hold 35s）接收消息。
    支持文本/图片/语音/文件/视频消息的接收和回复。
    """

    label = "微信通道"
    category = "监听器"
    description = "微信个人号消息收发，基于腾讯 iLink 协议，无需公网回调"
    bidirectional = True

    inputs = [
        NodeInput(name="reply", type="Reply", label="回复内容",
                  connected=True, required=False,
                  description="来自下游节点的回复（如 LLM 生成的文本）"),
    ]

    outputs = [
        NodeOutput(name="message", type="Message", label="收到的消息",
                   description="包含 text/from_user/context_token 等字段"),
    ]

    config_schema = {
        "bot_token": {
            "type": "string",
            "label": "Bot Token",
            "default": "",
            "description": "通过 openclaw channels login --channel openclaw-weixin 扫码获取",
        },
        "bot_agent": {
            "type": "string",
            "label": "Bot Agent",
            "default": "VideoFactory/1.0",
            "description": "自定义 User-Agent 标识（用于日志追踪）",
        },
        "api_base": {
            "type": "string",
            "label": "API 地址",
            "default": "https://ilinkai.weixin.qq.com/ilink/bot",
            "description": "iLink API 基础地址",
        },
    }

    # iLink API 端点
    _ENDPOINTS = {
        "getupdates": "/getupdates",
        "sendmessage": "/sendmessage",
        "getuploadurl": "/getuploadurl",
        "getconfig": "/getconfig",
        "sendtyping": "/sendtyping",
    }

    async def prepare(self, ctx):
        """初始化 HTTP 会话"""
        import aiohttp

        self._session = aiohttp.ClientSession()
        self._cursor = ""  # 长轮询游标
        ctx.logger.info("WeChatChannel 初始化完成")

    async def listen(self, ctx, emit):
        """长轮询监听微信消息"""
        token = self.get_config("bot_token", "")
        if not token:
            ctx.logger.error("bot_token 未配置，请先扫码登录")
            return

        api_base = self.get_config("api_base", "https://ilinkai.weixin.qq.com/ilink/bot")
        bot_agent = self.get_config("bot_agent", "VideoFactory/1.0")

        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {token}",
            "X-WECHAT-UIN": self._gen_uin(),
            "User-Agent": bot_agent,
        }

        ctx.logger.info("WeChatChannel 开始监听消息")

        while True:
            try:
                url = api_base + self._ENDPOINTS["getupdates"]
                payload = {
                    "get_updates_buf": self._cursor,
                    "base_info": {"channel_version": "1.0.2"},
                }

                async with self._session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as resp:
                    data = await resp.json()

                    if data.get("ret") != 0:
                        errcode = data.get("errcode", 0)
                        errmsg = data.get("errmsg", "unknown")
                        ctx.logger.error(f"iLink API 错误: errcode={errcode}, msg={errmsg}")
                        if errcode == -14:  # session timeout
                            ctx.logger.error("会话超时，需要重新扫码登录")
                            break
                        await asyncio.sleep(5)
                        continue

                    # 更新游标
                    self._cursor = data.get("get_updates_buf", self._cursor)

                    # 处理消息
                    msgs = data.get("msgs", [])
                    for msg in msgs:
                        parsed = self._parse_message(msg)
                        if parsed:
                            ctx.logger.info(
                                f"收到微信消息: from={parsed.get('from_user_id', '?')}, "
                                f"type={parsed.get('message_type', '?')}"
                            )
                            await emit(parsed)

            except asyncio.TimeoutError:
                # 长轮询超时是正常的，继续下一轮
                continue
            except asyncio.CancelledError:
                ctx.logger.info("WeChatChannel 监听被取消")
                break
            except Exception as e:
                ctx.logger.error(f"WeChatChannel 监听异常: {e}")
                await asyncio.sleep(5)

    async def send_reply(self, ctx, reply_data):
        """通过 iLink API 发送回复"""
        token = self.get_config("bot_token", "")
        api_base = self.get_config("api_base", "https://ilinkai.weixin.qq.com/ilink/bot")

        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {token}",
            "X-WECHAT-UIN": self._gen_uin(),
        }

        # reply_data 可能是字符串（纯文本）或 dict（含 context_token 等）
        if isinstance(reply_data, str):
            text = reply_data
            context_token = ""
            to_user = ""
        elif isinstance(reply_data, dict):
            text = reply_data.get("text", str(reply_data))
            context_token = reply_data.get("context_token", "")
            to_user = reply_data.get("to_user_id", "")
        else:
            text = str(reply_data)
            context_token = ""
            to_user = ""

        payload = {
            "context_token": context_token,
            "to_user_id": to_user,
            "item_list": [{
                "type": 1,  # 1=文本
                "content": text,
            }],
        }

        try:
            url = api_base + self._ENDPOINTS["sendmessage"]
            async with self._session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ret") == 0:
                    ctx.logger.info(f"微信回复发送成功")
                else:
                    ctx.logger.error(f"微信回复发送失败: {data.get('errmsg', 'unknown')}")
        except Exception as e:
            ctx.logger.error(f"微信回复发送异常: {e}")

    async def finalize(self, ctx, success):
        """关闭 HTTP 会话"""
        if hasattr(self, "_session") and self._session:
            await self._session.close()
            ctx.logger.info("WeChatChannel HTTP 会话已关闭")

    def _parse_message(self, raw_msg: dict) -> dict | None:
        """解析 iLink 消息格式为标准 Message"""
        if not isinstance(raw_msg, dict):
            return None

        msg_type = raw_msg.get("message_type", 0)
        from_user = raw_msg.get("from_user_id", "")
        to_user = raw_msg.get("to_user_id", "")
        context_token = raw_msg.get("context_token", "")

        # 提取消息内容
        text_parts = []
        item_list = raw_msg.get("item_list", [])
        for item in item_list:
            item_type = item.get("type", 0)
            if item_type == 1:  # 文本
                text_parts.append(item.get("content", ""))
            # TODO: 处理图片/语音/文件/视频类型

        return {
            "text": "\n".join(text_parts) if text_parts else "",
            "from_user_id": from_user,
            "to_user_id": to_user,
            "context_token": context_token,
            "message_type": msg_type,
            "raw": raw_msg,
        }

    def _gen_uin(self) -> str:
        """生成随机 X-WECHAT-UIN header 值"""
        import base64
        import random
        return base64.b64encode(str(random.randint(0, 2**32)).encode()).decode()
