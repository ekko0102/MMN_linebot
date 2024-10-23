from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import openai
import time
import traceback
import requests

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

# 用來保存每個使用者的對話上下文
session_dict = {}

def GPT_response(chat_id, text):
    try:
        # 如果該使用者已有上下文，將其加入對話
        if chat_id in session_dict:
            messages = session_dict[chat_id]
        else:
            messages = []
        
        # 將使用者的新訊息加入對話
        messages.append({
            "role": "user",
            "content": text
        })

        # 呼叫 OpenAI API，並將整個對話歷程傳入
        response = openai.ChatCompletion.create(
            model=ASSISTANT_ID,
            messages=messages
        )

        # 將回應加入對話歷程
        assistant_message = response['choices'][0]['message']['content']
        messages.append({
            "role": "assistant",
            "content": assistant_message
        })

        # 更新 session_dict，保存這次對話
        session_dict[chat_id] = messages

        return assistant_message
    except Exception as e:
        print("Error in GPT_response:", e)
        raise

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
        # 立即回覆一個"正在處理"的消息
        line_bot_api.reply_message(event.reply_token, TextSendMessage("我們正在處理你的請求，請稍等..."))

        # 使用者訊息處理
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
