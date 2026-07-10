const API_BASE = 'http://localhost:8000/api/config';

document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const modelSelect = document.getElementById('model-select');
    const saveModelBtn = document.getElementById('save-model-btn');
    const modelLoader = document.getElementById('model-loader');
    
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadProgress = document.getElementById('upload-progress');
    const docList = document.getElementById('doc-list');
    const emptyState = document.getElementById('empty-state');
    
    const historyList = document.getElementById('history-list');
    const historyEmptyState = document.getElementById('history-empty-state');
    const clearHistoryBtn = document.getElementById('clear-history-btn');
    
    // Initial fetches
    fetchModel();
    fetchDocuments();
    fetchHistory();

    // Model Selection
    saveModelBtn.addEventListener('click', async () => {
        const model = modelSelect.value;
        setLoading(saveModelBtn, modelLoader, true);
        
        try {
            const response = await fetch(`${API_BASE}/model`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model })
            });
            
            if (response.ok) {
                showToast('Model saved successfully!', 'success');
            } else {
                throw new Error('Failed to save model');
            }
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            setLoading(saveModelBtn, modelLoader, false);
        }
    });

    // Clear History
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', () => {
            if (confirm("Are you sure you want to clear your entire quiz history?")) {
                chrome.storage.local.set({ quizHistory: [] }, () => {
                    fetchHistory();
                    showToast('History cleared successfully!', 'success');
                });
            }
        });
    }

    // File Upload Drag & Drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    });

    // Helper Functions
    async function fetchModel() {
        try {
            const response = await fetch(`${API_BASE}/model`);
            if (response.ok) {
                const data = await response.json();
                
                // Add model to dropdown if not exists (for custom models)
                let exists = false;
                for(let i = 0; i < modelSelect.options.length; i++) {
                    if (modelSelect.options[i].value === data.model) exists = true;
                }
                
                if (!exists && data.model) {
                    const opt = document.createElement('option');
                    opt.value = data.model;
                    opt.textContent = data.model;
                    modelSelect.appendChild(opt);
                }
                
                modelSelect.value = data.model;
            }
        } catch (error) {
            console.error('Failed to fetch model:', error);
            showToast('Failed to connect to backend.', 'error');
        }
    }

    async function fetchDocuments() {
        try {
            const response = await fetch(`${API_BASE}/documents`);
            if (response.ok) {
                const data = await response.json();
                renderDocuments(data.documents);
            }
        } catch (error) {
            console.error('Failed to fetch documents:', error);
        }
    }

    function fetchHistory() {
        if (typeof chrome !== 'undefined' && chrome.storage) {
            chrome.storage.local.get({ quizHistory: [] }, (result) => {
                renderHistory(result.quizHistory);
            });
        } else {
            console.warn("chrome.storage not available, cannot load history.");
        }
    }

    async function handleFiles(files) {
        const formData = new FormData();
        let hasPdf = false;
        
        for (let file of files) {
            if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
                formData.append('file', file);
                hasPdf = true;
            }
        }

        if (!hasPdf) {
            showToast('Please select valid PDF files.', 'error');
            return;
        }

        uploadProgress.style.display = 'block';
        dropZone.style.display = 'none';

        try {
            const response = await fetch(`${API_BASE}/upload-pdf`, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                showToast('Documents indexed successfully!', 'success');
                fetchDocuments();
            } else {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Upload failed');
            }
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            uploadProgress.style.display = 'none';
            dropZone.style.display = 'block';
            fileInput.value = ''; // clear input
        }
    }

    async function deleteDocument(filename) {
        if (!confirm(`Are you sure you want to remove ${filename} from the index?`)) return;
        
        try {
            const response = await fetch(`${API_BASE}/documents/${encodeURIComponent(filename)}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                showToast('Document removed successfully!', 'success');
                fetchDocuments();
            } else {
                throw new Error('Failed to delete document');
            }
        } catch (error) {
            showToast(error.message, 'error');
        }
    }

    function renderDocuments(docs) {
        docList.innerHTML = '';
        
        if (!docs || docs.length === 0) {
            docList.appendChild(emptyState);
            return;
        }

        docs.forEach(doc => {
            const div = document.createElement('div');
            div.className = 'doc-item';
            div.innerHTML = `
                <div class="doc-info">
                    <svg class="doc-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <line x1="16" y1="13" x2="8" y2="13"></line>
                        <line x1="16" y1="17" x2="8" y2="17"></line>
                        <polyline points="10 9 9 9 8 9"></polyline>
                    </svg>
                    <span>${doc.filename}</span>
                </div>
                <button class="danger" style="padding: 6px 12px; font-size: 0.85rem;">Delete</button>
            `;
            
            div.querySelector('button').addEventListener('click', () => deleteDocument(doc.filename));
            docList.appendChild(div);
        });
    }

    function renderHistory(history) {
        historyList.innerHTML = '';
        
        if (!history || history.length === 0) {
            historyList.appendChild(historyEmptyState);
            return;
        }

        history.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-item';
            
            const date = new Date(item.timestamp);
            const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
            
            div.innerHTML = `
                <div class="history-header">
                    <span>${dateStr}</span>
                    <span style="font-size: 0.75rem; background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px;">Quiz Evaluation</span>
                </div>
                <div class="history-details">
                    <div class="history-stat">
                        <span style="font-size: 0.75rem; color: var(--text-muted);">Questions</span>
                        <span class="history-stat-val">${item.questionsAnalyzed}</span>
                    </div>
                    <div class="history-stat">
                        <span style="font-size: 0.75rem; color: var(--text-muted);">Model</span>
                        <span class="history-stat-val" style="color: #a78bfa;">${item.modelUsed}</span>
                    </div>
                    <div class="history-stat">
                        <span style="font-size: 0.75rem; color: var(--text-muted);">Latency</span>
                        <span class="history-stat-val" style="color: #60a5fa;">${item.processingTime}ms</span>
                    </div>
                </div>
            `;
            
            historyList.appendChild(div);
        });
    }

    function setLoading(btn, loader, isLoading) {
        const textSpan = btn.querySelector('.btn-text');
        if (isLoading) {
            btn.disabled = true;
            textSpan.style.display = 'none';
            loader.style.display = 'inline-block';
        } else {
            btn.disabled = false;
            textSpan.style.display = 'inline';
            loader.style.display = 'none';
        }
    }

    function showToast(message, type) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
});
