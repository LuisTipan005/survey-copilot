document.addEventListener('DOMContentLoaded', async () => {
    const profileInput = document.getElementById('userProfile');
    const saveBtn = document.getElementById('saveProfileBtn');
    const scanBtn = document.getElementById('scanBtn');
    const openDashboardBtn = document.getElementById('openDashboardBtn');
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
    // 4. Open Settings Dashboard
    if (openDashboardBtn) {
        openDashboardBtn.addEventListener('click', () => {
            chrome.tabs.create({ url: chrome.runtime.getURL("dashboard.html") });
        });
    }

    // 5. Trigger Scan — targets Moodle quiz pop-up if one is open, otherwise the active tab
    scanBtn.addEventListener('click', async () => {
        actionStatus.textContent = 'Buscando ventana del quiz...';
        actionStatus.style.color = '';

        // Delegate scanning to the centralized background script
        const result = await new Promise(resolve => {
            chrome.runtime.sendMessage({ action: "TRIGGER_SCAN" }, resolve);
        });

        if (!result || !result.success) {
            const errorMsg = result?.error || "Desconocido";
            actionStatus.textContent = 'Error: ' + errorMsg;
            actionStatus.style.color = '#f44336';
            return;
        }

        if (result.wasInjected) {
            actionStatus.textContent = 'Scripts inyectados. Escaneando...';
        } else {
            actionStatus.textContent = 'Escaneando...';
        }
    });
});