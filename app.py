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


app = Flask(__name__)

# Redis 連接設定
# 使用 Render 提供的 REDIS_URL 進行連接
redis_url = os.getenv('REDIS_URL')
if not redis_url:
    raise ValueError("REDIS_URL 環境變數未設置")
# 初始化 Redis 客戶端，直接使用 URL
redis_db = redis.StrictRedis.from_url(redis_url, decode_responses=True)

# redis_host = os.getenv('REDIS_HOST', 'localhost')
# redis_port = os.getenv('REDIS_PORT', 6379)
# redis_db = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)

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

def GPT_response(user_id, text):
    try:
        thread_id = redis_db.get(f"thread_id:{user_id}")
        client = openai.OpenAI()

        if not thread_id:
            thread = client.beta.threads.create(
                messages=[{"role": "user", "content": text}]
            )
            thread_id = thread.id
            redis_db.set(f"thread_id:{user_id}", thread_id)
        else:
            # 檢查當前是否有未完成的 `run`
            active_run = client.beta.threads.runs.list(thread_id=thread_id).data
            if active_run and any(run.status != "completed" for run in active_run):
                print("當前 thread 的運行尚未完成，請稍候再試。")
                return "當前正在處理中，請稍候再試。"

            # 發送訊息至 thread
            response = client.beta.threads.messages.create(
                thread_id=thread_id, role="user", content=text
            )
            print("API 回傳訊息：", response)

        # 繼續執行 thread
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID)
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            time.sleep(1)
        
        message_response = client.beta.threads.messages.list(thread_id=thread_id)
        messages = message_response.data
        latest_message = messages[0]
        print("最新的訊息內容：", latest_message.content[0].text.value)
        return latest_message.content[0].text.value

    except Exception as e:
        print("Error in GPT_response:", e)
        raise

def send_loading_animation(chat_id):
    url = 'https://api.line.me/v2/bot/chat/loading/start'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("CHANNEL_ACCESS_TOKEN")}'
    }
    data = {
        "chatId": chat_id,
        "loadingSeconds": 5  # 設定動畫持續時間為5秒
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
    try:
        # 獲取 chat_id
        chat_id = get_chat_id(event)
        
        if chat_id:
            # 發送載入動畫
            send_loading_animation(chat_id)
        
        # 處理用戶訊息，使用 user_id 當作 Redis key
        user_id = chat_id
        GPT_answer = GPT_response(user_id, msg)
        
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
