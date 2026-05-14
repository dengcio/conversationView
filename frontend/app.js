// Configuration
const API_BASE = 'http://127.0.0.1:8000/api';

// State
let sessions = [];
let currentSessionKey = null;

// Load sessions on page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadSessions();
});

// Load all sessions
async function loadSessions() {
    try {
        const response = await fetch(`${API_BASE}/sessions?limit=100`);
        sessions = await response.json();
        
        const sessionList = document.getElementById('session-list');
        sessionList.innerHTML = '';
        
        sessions.forEach(session => {
            const div = document.createElement('div');
            div.className = 'session-item';
            div.dataset.sessionKey = session.sessionKey;
            div.innerHTML = `
                <div class="session-key">${session.sessionKey}</div>
                <div class="session-meta">
                    ${session.kind || 'unknown'} | 
                    ${session.messageCount || 0} messages
                </div>
            `;
            div.onclick = () => loadSessionHistory(session.sessionKey);
            sessionList.appendChild(div);
        });
    } catch (error) {
        console.error('Error loading sessions:', error);
        alert('加载会话失败: ' + error.message);
    }
}

// Load session history
async function loadSessionHistory(sessionKey) {
    currentSessionKey = sessionKey;
    
    // Update active state
    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionKey === sessionKey);
    });
    
    try {
        const response = await fetch(`${API_BASE}/sessions/${sessionKey}/history?limit=100`);
        const data = await response.json();
        
        const conversationView = document.getElementById('conversation-view');
        
        if (!data.messages || data.messages.length === 0) {
            conversationView.innerHTML = '<p class="placeholder">该会话没有消息</p>';
            return;
        }
        
        conversationView.innerHTML = '';
        
        data.messages.forEach(msg => {
            const div = document.createElement('div');
            div.className = `message ${msg.role}`;
            
            const content = msg.content || msg.text || JSON.stringify(msg);
            const timestamp = msg.timestamp || '';
            
            div.innerHTML = `
                <div class="message-role">${msg.role} ${timestamp ? `(${new Date(timestamp).toLocaleString()})` : ''}</div>
                <div class="message-content">${formatContent(content)}</div>
                <div class="message-actions">
                    <button onclick="saveChunk('${sessionKey}', '${encodeURIComponent(content)}', '${msg.role}')">
                        保存分块
                    </button>
                </div>
            `;
            
            conversationView.appendChild(div);
        });
        
        // Load chunks for this session
        await loadChunks(sessionKey);
        
    } catch (error) {
        console.error('Error loading history:', error);
        alert('加载对话历史失败: ' + error.message);
    }
}

// Format content (handle markdown, code blocks, etc.)
function formatContent(content) {
    if (typeof content !== 'string') {
        return `<pre>${JSON.stringify(content, null, 2)}</pre>`;
    }
    
    // Escape HTML
    let formatted = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Code blocks
    formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    
    // Inline code
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Line breaks
    formatted = formatted.replace(/\n/g, '<br>');
    
    return formatted;
}

// Save a chunk
window.saveChunk = async (sessionKey, content, role) => {
    const notes = prompt('添加笔记（可选）:');
    const tags = prompt('添加标签（逗号分隔，可选）:');
    
    try {
        const response = await fetch(`${API_BASE}/chunks`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_key: sessionKey,
                content: decodeURIComponent(content),
                role: role,
                timestamp: new Date().toISOString(),
                tags: tags ? tags.split(',').map(t => t.trim()) : [],
                notes: notes || null
            })
        });
        
        const result = await response.json();
        alert('分块已保存！ID: ' + result.chunk_id);
        
        // Reload chunks
        await loadChunks(sessionKey);
        
    } catch (error) {
        console.error('Error saving chunk:', error);
        alert('保存分块失败: ' + error.message);
    }
};

// Load chunks for a session
async function loadChunks(sessionKey) {
    try {
        const response = await fetch(`${API_BASE}/chunks?session_key=${sessionKey}`);
        const chunks = await response.json();
        
        const chunkPanel = document.getElementById('chunk-panel');
        const chunkList = document.getElementById('chunk-list');
        
        if (chunks.length === 0) {
            chunkPanel.style.display = 'none';
            return;
        }
        
        chunkPanel.style.display = 'block';
        chunkList.innerHTML = '';
        
        chunks.forEach(chunk => {
            const div = document.createElement('div');
            div.className = 'chunk-item';
            div.innerHTML = `
                <div class="chunk-content">${formatContent(chunk.content)}</div>
                <div class="chunk-meta">
                    <span>角色: ${chunk.role}</span>
                    <span>标签: ${(chunk.tags || []).join(', ')}</span>
                </div>
                ${chunk.notes ? `<div class="chunk-notes">笔记: ${chunk.notes}</div>` : ''}
                <div class="chunk-actions">
                    <button onclick="deleteChunk(${chunk.id})">删除</button>
                </div>
            `;
            chunkList.appendChild(div);
        });
        
    } catch (error) {
        console.error('Error loading chunks:', error);
    }
}

// Delete a chunk
window.deleteChunk = async (chunkId) => {
    if (!confirm('确定要删除这个分块吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/chunks/${chunkId}`, {
            method: 'DELETE'
        });
        
        alert('分块已删除');
        
        // Reload chunks
        await loadChunks(currentSessionKey);
        
    } catch (error) {
        console.error('Error deleting chunk:', error);
        alert('删除分块失败: ' + error.message);
    }
};

// Search conversations
window.searchConversations = async () => {
    const query = document.getElementById('search-input').value.trim();
    
    if (!query) {
        alert('请输入搜索关键词');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/search?query=${encodeURIComponent(query)}&limit=20`);
        const results = await response.json();
        
        const conversationView = document.getElementById('conversation-view');
        
        if (!results.results || results.results.length === 0) {
            conversationView.innerHTML = '<p class="placeholder">没有找到相关结果</p>';
            return;
        }
        
        conversationView.innerHTML = '<div class="search-results"></div>';
        const searchResults = conversationView.querySelector('.search-results');
        
        results.results.forEach(result => {
            const div = document.createElement('div');
            div.className = 'search-result-item';
            div.innerHTML = `
                <h4>Score: ${result.score?.toFixed(2) || 'N/A'}</h4>
                <p>${formatContent(result.content || JSON.stringify(result))}</p>
            `;
            searchResults.appendChild(div);
        });
        
    } catch (error) {
        console.error('Error searching:', error);
        alert('搜索失败: ' + error.message);
    }
};

// Allow Enter key to trigger search
document.getElementById('search-input')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        searchConversations();
    }
});
