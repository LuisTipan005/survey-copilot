document.addEventListener('DOMContentLoaded', async () => {
    const profileInput = document.getElementById('userProfile');
    const saveBtn = document.getElementById('saveProfileBtn');
    const scanBtn = document.getElementById('scanBtn');
    const statusDot = document.getElementById('backendStatus');
    const statusText = document.getElementById('statusText');
    const saveFeedback = document.getElementById('saveFeedback');
    const actionStatus = document.getElementById('actionStatus');

    // 1. Check Backend Health
    try {
        const response = await fetch('http://localhost:8000/api/health');
        if (response.ok) {
            statusDot.className = 'dot green';
            statusText.textContent = 'Backend Online';
        }
    } catch (error) {
        statusDot.className = 'dot red';
        statusText.textContent = 'Backend Offline';
        scanBtn.disabled = true;
        scanBtn.style.opacity = '0.5';
    }

    // 2. Load saved profile from storage
    chrome.storage.local.get(['userProfile'], (result) => {
        if (result.userProfile) {
            profileInput.value = result.userProfile;
        }
    });

    // 3. Save profile to storage
    saveBtn.addEventListener('click', () => {
        const profileText = profileInput.value;
        chrome.storage.local.set({ userProfile: profileText }, () => {
            saveFeedback.textContent = 'Profile saved!';
            setTimeout(() => { saveFeedback.textContent = ''; }, 2000);
        });
    });

    // 4. Trigger Scan on the active tab
    scanBtn.addEventListener('click', async () => {
        actionStatus.textContent = 'Injecting script...';
        
        // Get the active tab
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        
        if (!tab) return;

        // Send message to the content script of that tab
        chrome.tabs.sendMessage(tab.id, { action: "START_SCAN" }, (response) => {
            if (chrome.runtime.lastError) {
                actionStatus.textContent = 'Please reload the page first.';
                actionStatus.style.color = '#f44336';
            } else {
                actionStatus.textContent = 'Scanning...';
            }
        });
    });
});