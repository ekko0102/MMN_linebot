from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import openai
import traceback
import requests
import redis
import json

app = Flask(__name__)


# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OpenAI API Key 初始化设置
openai_api_key = os.getenv('OPENAI_API_KEY')
if not openai_api_key:
    raise ValueError("未在环境变量中设置 OpenAI API 密钥")
openai.api_key = openai_api_key

# 自定义助手的模型 ID
ASSISTANT_ID = os.getenv('OPENAI_MODEL_ID')

# 设置 Redis 连接
redis_url = os.getenv('REDIS_URL')
r = redis.Redis.from_url(redis_url)

def get_user_context(chat_id):
    """从 Redis 中获取用户的对话上下文"""
    context = r.get(f"context:{chat_id}")
    if context:
        return json.loads(context)
    else:
        # 如果需要，可以在这里初始化系统提示
        return []

def save_user_context(chat_id, messages):
    """将用户的对话上下文保存到 Redis"""
    # 限制上下文长度，防止消息过多
    MAX_CONTEXT_MESSAGES = 10
    messages = messages[-MAX_CONTEXT_MESSAGES:]
    r.set(f"context:{chat_id}", json.dumps(messages))

def GPT_response(chat_id, user_message):
    try:
        # 获取用户的对话上下文
        messages = get_user_context(chat_id)

        # 将用户的新消息添加到上下文中
        messages.append({"role": "user", "content": user_message})

        # 调用 OpenAI ChatCompletion API，使用自定义助手
        response = openai.ChatCompletion.create(
            model=ASSISTANT_ID,  # 使用您的自定义助手模型 ID
            messages=messages,
            # 您可以根据需要调整温度等参数
        )

        # 获取助手的回复
        assistant_message = response['choices'][0]['message']['content']

        # 将助手的回复添加到上下文中
        messages.append({"role": "assistant", "content": assistant_message})

        # 将更新后的上下文保存到 Redis
        save_user_context(chat_id, messages)

        return assistant_message
    except Exception as e:
        print("GPT_response 错误：", e)
        raise

def send_loading_animation(chat_id, loading_seconds=5):
    url = 'https://api.line.me/v2/bot/chat/loading/start'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("CHANNEL_ACCESS_TOKEN")}'
    }
    data = {
        "chatId": chat_id,
        "loadingSeconds": loading_seconds
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code != 202:
        print(f"发送加载动画失败：{response.status_code}, {response.text}")
    else:
        print("加载动画发送成功")
    return response.status_code, response.text

def get_chat_id(event):
    if event.source.type == 'user':
        return event.source.user_id
    elif event.source.type == 'group':
        return event.source.group_id
    elif event.source.type == 'room':
        return event.source.room_id
    else:
        return None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("请求正文：" + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    chat_id = get_chat_id(event)

    try:
        # 发送加载动画
        send_loading_animation(chat_id, loading_seconds=5)

        # 处理用户消息并获取 GPT 回复
        GPT_answer = GPT_response(chat_id, msg)

        # 将 GPT 的回复发送给用户
        line_bot_api.push_message(chat_id, TextSendMessage(GPT_answer))
    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage('发生错误，请稍后再试。')
        )

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    if event.source.type == 'group':
        gid = event.source.group_id
        for member in event.joined.members:
            uid = member.user_id
            profile = line_bot_api.get_group_member_profile(gid, uid)
            name = profile.display_name
            message = TextSendMessage(text=f'{name}，欢迎加入群组！')
            line_bot_api.push_message(gid, message)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
