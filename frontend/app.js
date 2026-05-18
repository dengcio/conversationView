const API_BASE = window.location.protocol === 'file:'
    ? 'http://localhost:8000/api'
    : '/api';

let currentConvId = null;
let importMode = 'text';

document.addEventListener('DOMContentLoaded', () => {
    loadConversations();
});

// ============================================
// Conversation list
// ============================================

async function loadConversations() {
    try {
        const response = await fetch(`${API_BASE}/conversations`);
        const conversations = await response.json();

        const list = document.getElementById('conversation-list');
        const count = document.getElementById('conv-count');
        count.textContent = `${conversations.length} 个对话`;

        list.innerHTML = '';
        conversations.forEach(conv => {
            const div = document.createElement('div');
            div.className = 'conv-item';
            if (conv.id === currentConvId) div.classList.add('active');
            const badge = conv.is_analyzed
                ? '<span class="conv-badge">已分析</span>'
                : '<span class="conv-badge pending">待分析</span>';
            div.innerHTML = `
                <div class="conv-title">${escapeHtml(conv.title)}</div>
                <div class="conv-meta">
                    <span>${conv.message_count} 条</span>
                    <span>${conv.source}</span>
                    ${badge}
                    <span style="margin-left:auto">${conv.created_at}</span>
                </div>
            `;
            div.onclick = () => loadConversation(conv.id);
            list.appendChild(div);
        });
    } catch (error) {
        console.error('Failed to load conversations:', error);
    }
}

// ============================================
// Conversation detail
// ============================================

async function loadConversation(id) {
    currentConvId = id;

    document.querySelectorAll('.conv-item').forEach(el => {
        el.classList.toggle('active', false);
    });

    try {
        const response = await fetch(`${API_BASE}/conversations/${id}`);
        if (!response.ok) throw new Error('Conversation not found');
        const conv = await response.json();

        document.querySelectorAll('.conv-item').forEach(el => {
            const titleEl = el.querySelector('.conv-title');
            if (titleEl && titleEl.textContent === conv.title) {
                el.classList.add('active');
            }
        });

        renderConversation(conv);
    } catch (error) {
        console.error('Failed to load conversation:', error);
        document.getElementById('conversation-view').innerHTML =
            '<p class="placeholder">读取失败，请确认后端服务已启动</p>';
    }
}

function renderConversation(conv) {
    const view = document.getElementById('conversation-view');

    let html = `
        <div class="conv-detail-header">
            <h2>${escapeHtml(conv.title)}</h2>
            <div class="conv-info">
                ${conv.source} · ${conv.message_count} 条消息 · ${conv.created_at}
            </div>
            <div>
                <button class="btn-danger" onclick="deleteConversation(${conv.id})" style="margin-right:8px">删除</button>
                ${!conv.is_analyzed
                    ? `<button class="btn-primary analyze-btn" onclick="analyzeConversation(${conv.id})">AI 分析此对话</button>`
                    : ''}
            </div>
        </div>
        <div class="messages-section">
            <h3 style="margin-bottom:14px;color:#666;font-size:15px">原始对话</h3>
            ${conv.messages.map(m => `
                <div class="message ${m.role}">
                    <div class="msg-role">${m.role === 'user' ? '用户' : m.role === 'assistant' ? '助手' : m.role}</div>
                    <div class="msg-content">${escapeHtml(m.content)}</div>
                </div>
            `).join('')}
        </div>
    `;

    if (conv.analysis && conv.analysis.length > 0) {
        html += `
            <div id="analysis-section">
                <h3>AI 分析结果</h3>
                ${conv.analysis.map(a => `
                    <div class="analysis-card">
                        <div class="card-header">
                            <span class="card-title">${escapeHtml(a.title || '')}</span>
                            <span class="card-score">${'★'.repeat(a.value_score)}${'☆'.repeat(5 - a.value_score)}</span>
                        </div>
                        <div class="card-summary">${escapeHtml(a.summary || '')}</div>
                        ${a.tags && a.tags.length > 0 ? `
                            <div class="card-tags">
                                ${a.tags.map(t => `<span class="tag">🏷 ${escapeHtml(t)}</span>`).join('')}
                            </div>
                        ` : ''}
                        ${a.keywords && a.keywords.length > 0 ? `
                            <div class="card-keywords">
                                ${a.keywords.map(k => `<span class="keyword">🔑 ${escapeHtml(k)}</span>`).join('')}
                            </div>
                        ` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    view.innerHTML = html;
}

// ============================================
// Import - modal and mode switching
// ============================================

function switchImportMode(mode) {
    importMode = mode;
    document.querySelectorAll('.import-tab').forEach(t => {
        const isActive = (t.textContent.includes('粘贴') && mode === 'text') ||
                         (t.textContent.includes('链接') && mode === 'link');
        t.classList.toggle('active', isActive);
    });
    document.getElementById('import-panel-text').style.display = mode === 'text' ? 'block' : 'none';
    document.getElementById('import-panel-link').style.display = mode === 'link' ? 'block' : 'none';
}

function openImportModal() {
    importMode = 'text';
    document.querySelectorAll('.import-tab').forEach((t, i) => t.classList.toggle('active', i === 0));
    document.getElementById('import-panel-text').style.display = 'block';
    document.getElementById('import-panel-link').style.display = 'none';
    document.getElementById('import-text').value = '';
    document.getElementById('import-title').value = '';
    document.getElementById('import-link').value = '';
    document.getElementById('import-link-title').value = '';
    document.getElementById('import-overlay').style.display = 'flex';
}

function closeImportModal() {
    document.getElementById('import-overlay').style.display = 'none';
}

async function handleImport(andAnalyze) {
    if (importMode === 'link') {
        await importFromLink(andAnalyze);
    } else {
        await importConversation(andAnalyze);
    }
}

// ---- Text import ----

async function importConversation(andAnalyze) {
    const source = document.getElementById('import-source').value;
    const title = document.getElementById('import-title').value.trim();
    const rawText = document.getElementById('import-text').value.trim();

    if (!rawText) {
        alert('请粘贴对话内容');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                raw_text: rawText,
                source: source,
                title: title || null
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '导入失败');
        }

        const result = await response.json();
        closeImportModal();
        await loadConversations();
        await loadConversation(result.conversation_id);

        if (andAnalyze) {
            await analyzeConversation(result.conversation_id);
        }
    } catch (error) {
        alert('导入失败: ' + error.message);
    }
}

// ---- Link import ----

async function importFromLink(andAnalyze) {
    const url = document.getElementById('import-link').value.trim();
    const title = document.getElementById('import-link-title').value.trim();

    if (!url) {
        alert('请输入分享链接');
        return;
    }

    const overlay = document.getElementById('loading-overlay');
    const text = document.getElementById('loading-text');
    overlay.style.display = 'flex';
    text.textContent = '正在获取链接内容...';

    try {
        const response = await fetch(`${API_BASE}/import-from-link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                title: title || null
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '获取链接失败');
        }

        const result = await response.json();
        overlay.style.display = 'none';
        closeImportModal();
        await loadConversations();
        await loadConversation(result.conversation_id);

        if (andAnalyze) {
            await analyzeConversation(result.conversation_id);
        }
    } catch (error) {
        overlay.style.display = 'none';
        alert('链接导入失败: ' + error.message);
    }
}

// ============================================
// AI Analysis
// ============================================

async function analyzeConversation(id) {
    const overlay = document.getElementById('loading-overlay');
    const text = document.getElementById('loading-text');
    overlay.style.display = 'flex';
    text.textContent = 'AI 正在分析对话内容...';

    try {
        const response = await fetch(`${API_BASE}/conversations/${id}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chunk_mode: 'auto' })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '分析失败');
        }

        overlay.style.display = 'none';
        await loadConversations();
        await loadConversation(id);
    } catch (error) {
        overlay.style.display = 'none';
        alert('分析失败: ' + error.message);
    }
}

// ============================================
// Delete
// ============================================

async function deleteConversation(id) {
    if (!confirm('确定要删除这个对话吗？关联的消息和分析结果也会被删除。')) {
        return;
    }

    try {
        await fetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' });
        currentConvId = null;
        document.getElementById('conversation-view').innerHTML = '<p class="placeholder">选择一个对话查看内容</p>';
        await loadConversations();
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

// ============================================
// Utilities
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
