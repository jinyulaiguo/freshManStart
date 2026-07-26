document.addEventListener("DOMContentLoaded", () => {
    const chatHistory = document.getElementById("chat-history");
    const traceLog = document.getElementById("trace-log");
    const queryInput = document.getElementById("query-input");
    const sendBtn = document.getElementById("send-btn");
    
    let ws = new WebSocket(`ws://${window.location.host}/ws/chat`);
    let currentAiMsgDiv = null;
    let currentAiMsgContent = null;
    let currentAiMsgRawText = "";
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === "token") {
            if (!currentAiMsgContent) {
                currentAiMsgDiv = document.createElement("div");
                currentAiMsgDiv.className = "message ai-msg";
                currentAiMsgContent = document.createElement("div");
                currentAiMsgContent.className = "msg-content";
                currentAiMsgDiv.appendChild(currentAiMsgContent);
                chatHistory.appendChild(currentAiMsgDiv);
            }
            // 使用 marked.js 渲染 Markdown
            currentAiMsgRawText += data.content;
            if (window.marked) {
                currentAiMsgContent.innerHTML = marked.parse(currentAiMsgRawText);
            } else {
                currentAiMsgContent.innerHTML = currentAiMsgRawText.replace(/\n/g, "<br>");
            }
            chatHistory.scrollTop = chatHistory.scrollHeight;
        } else if (data.type === "tool_start" || data.type === "tool_end" || data.type === "error" || data.type === "info") {
            const traceItem = document.createElement("div");
            traceItem.className = `trace-item ${data.type}`;
            const time = new Date().toLocaleTimeString();
            traceItem.innerText = `[${time}] ${data.content}`;
            traceLog.appendChild(traceItem);
            traceLog.scrollTop = traceLog.scrollHeight;
            
            if (data.type === "tool_end") {
                const outItem = document.createElement("div");
                outItem.className = "trace-item info";
                outItem.innerText = `>> Output length: ${data.output.length} chars`;
                traceLog.appendChild(outItem);
            }
        } else if (data.type === "done") {
            currentAiMsgContent = null;
            currentAiMsgRawText = "";
            sendBtn.disabled = false;
            sendBtn.innerText = "执行分析";
        }
    };
    
    ws.onclose = () => {
        const item = document.createElement("div");
        item.className = "trace-item error";
        item.innerText = "WebSocket connection closed. Please refresh.";
        traceLog.appendChild(item);
    };

    const sendMessage = () => {
        const text = queryInput.value.trim();
        if (!text) return;
        
        // Render user message
        const userDiv = document.createElement("div");
        userDiv.className = "message user-msg";
        const userContent = document.createElement("div");
        userContent.className = "msg-content";
        userContent.innerText = text;
        userDiv.appendChild(userContent);
        chatHistory.appendChild(userDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        
        // Send to server
        ws.send(JSON.stringify({ query: text }));
        queryInput.value = "";
        
        // Update UI
        sendBtn.disabled = true;
        sendBtn.innerText = "运行中...";
        currentAiMsgContent = null;
        currentAiMsgRawText = "";
    };
    
    sendBtn.addEventListener("click", sendMessage);
    
    queryInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});
