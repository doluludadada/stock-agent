``` mermaid
sequenceDiagram
    actor User
    participant LINE_Server

    box "stock-agent"
        participant LineWebhook as POST /v1/webhook/line
        participant Pipeline as Pipeline.reply_to_chat
        participant LinePlatformAdapter
    end

    User->>+LINE_Server: 1. Send message
    LINE_Server->>+LineWebhook: 2. Forward webhook (HTTP POST)

    Note over LineWebhook: Verify X-Line-Signature, parse the payload

    LineWebhook->>+Pipeline: 3. reply_to_chat(user_id, content)

    Note over Pipeline: Load the conversation, ask the AI, save the conversation

    Pipeline->>+LinePlatformAdapter: 4. send_message(user_id, message)
    LinePlatformAdapter->>+LINE_Server: 5. Push the reply (Messaging API)
    deactivate LinePlatformAdapter
    LINE_Server->>+User: 6. Deliver the reply
    deactivate LINE_Server
    deactivate Pipeline
    deactivate LineWebhook
```
