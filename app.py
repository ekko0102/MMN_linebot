from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
import os
import time
import traceback
from openai import OpenAI

# 初始化Flask應用
app = Flask(__name__)
static_tmp_path = os.path.join(os.path.dirname(__file__), 'static', 'tmp')

# 初始化LineBotApi和WebhookHandler
line_bot_api = LineBotApi(os.getenv('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('CHANNEL_SECRET'))

# 初始化OpenAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')
client = OpenAI()

# OpenAI助手ID
ASSISTANT_ID = "asst_H4JiVadUvQzVI77CrgsdOk62"

# 定義OpenAI助手的回應函數
def GPT_response(text):
    # 創建線程並提交給助理
    thread = client.beta.threads.create(
        messages=[{
            "role": "user",
            "content": text
        }]
    )
    run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)
    
    # 等待回應完成
    while run.status != "completed":
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        print(f"🏃 Run Status: {run.status}")
        time.sleep(1)
    
    # 獲取最新的訊息回應
    message_response = client.beta.threads.messages.list(thread_id=thread.id)
    messages = message_response.data
    
    # 返回最新的訊息內容
    latest_message = messages[0]
    return latest_message['content']

# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    # 取得 X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # 取得 request body 為文字
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    
    # 處理 webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 處理訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    try:
        GPT_answer = GPT_response(msg)
        print(GPT_answer)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(GPT_answer))
    except:
        print(traceback.format_exc())
        line_bot_api.reply_message(event.reply_token, TextSendMessage('你所使用的OPENAI API key額度可能已經超過，請於後台Log內確認錯誤訊息'))

@handler.add(PostbackEvent)
def handle_message(event):
    print(event.postback.data)

@handler.add(MemberJoinedEvent)
def welcome(event):
    uid = event.joined.members[0].user_id
    gid = event.source.group_id
    profile = line_bot_api.get_group_member_profile(gid, uid)
    name = profile.display_name
    message = TextSendMessage(text=f'{name}歡迎加入')
    line_bot_api.reply_message(event.reply_token, message)

# 啟動Flask應用
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
