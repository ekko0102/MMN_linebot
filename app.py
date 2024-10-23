from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import openai
import time
import traceback
import requests
import redis
import json

app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# Channel Access Token
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
# Channel Secret
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))
# OPENAI API Key初始化設定
openai_api_key = os.getenv('OPENAI_API_KEY')
if not openai_api_key:
    raise ValueError("OpenAI API key is not set in environment variables")
openai.api_key = openai_api_key

ASSISTANT_ID = os.getenv('OPENAI_MODEL_ID')

# 設定 Redis 連接
redis_url = os.getenv('REDIS_URL')
r = redis.Redis.from_url(redis_url)

def get_user_context(chat_id):
    """從 Redis 中獲取用戶的上下文記錄"""
    context = r.get(chat_id)
    if context:
        return json.loads(context)
    return []

def save_user_context(chat_id, messages):
    """將用戶上下文記錄保存到 Redis 中"""
    r.set(chat_id, json.dumps(messages))

def GPT_response(chat_id, text):
    try:
        client = openai.OpenAI()

        # 從 Redis 中獲取該使用者的上下文
        messages = get_user_context(chat_id)
        
        # 新的用戶訊息加入對話歷程
        messages.append({
            "role": "user",
            "content": text
        })

        # 呼叫 OpenAI API
        thread = client.beta.threads.create(messages=messages)
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)

        # 等待執行完成
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            time.sleep(1)

        # 獲取 GPT 最新的回應
        message_response = client.beta.threads.messages.list(thread_id=thread.id)
        latest_message = message_response.data[0].content[0].text.value

        # 將 GPT 的回應加入上下文
        messages.append({
            "role": "assistant",
            "content": latest_message
        })

        # 保存更新後的上下文到 Redis
        save_user_context(chat_id, messages)

        return latest_message
    except Exception as e:
        print("Error in GPT_response:", e)
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
        print(f"傳送載入動畫失敗： {response.status_code}，{response.text}")
    else:
        print("載入動畫已成功發送")
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
    app.logger.info("Request body: " + body)
    
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
        # 發送載入動畫
        send_loading_animation(chat_id, loading_seconds=5)

        # 處理用戶訊息，並將其保存到 Redis
        GPT_answer = GPT_response(chat_id, msg)

        # 發送 GPT 回覆結果
        line_bot_api.push_message(chat_id, TextSendMessage(GPT_answer))
    except Exception as e:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('你所使用的 OPENAI API key 額度可能已經超過，請於後台 Log 內確認錯誤訊息'))

@handler.add(PostbackEvent)
def handle_postback(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name} 歡迎加入')
    line_bot_api.push_message(gid, message)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
