def GPT_response(chat_id, text):
    try:
        client = openai.OpenAI()
        
        # 檢查是否已有上下文，沒有則初始化
        if chat_id not in session_dict:
            session_dict[chat_id] = []  # 初始化該 chat_id 的上下文

        # 獲取該使用者的上下文對話
        messages = session_dict[chat_id]
        
        # 新的用戶訊息加入對話歷程
        messages.append({
            "role": "user",
            "content": text
        })

        # 創建新的線程並發送對話歷程
        thread = client.beta.threads.create(
            messages=messages
        )
        # 提交線程並創建一個執行
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)

        # 等待執行完成
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            time.sleep(1)
        
        # 獲取最新的回應消息
        message_response = client.beta.threads.messages.list(thread_id=thread.id)
        messages = message_response.data
        latest_message = messages[0].content[0].text.value

        # 保存回應到上下文
        session_dict[chat_id].append({
            "role": "assistant",
            "content": latest_message
        })

        return latest_message
    except Exception as e:
        print("Error in GPT_response:", e)
        raise
