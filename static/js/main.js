/**
 * Main JavaScript for Real-Time Attendance System
 * Client-side functionality and API interactions
 */

// ============================================
// Configuration
// ============================================
const API_BASE = '';
const UPDATE_INTERVAL = 2000;

// ============================================
// Utility Functions
// ============================================

/**
 * Make an API request with error handling
 */
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        throw error;
    }
}

/**
 * Show a toast notification
 */
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '1100';
        document.body.appendChild(container);
    }
    
    const toastId = `toast-${Date.now()}`;
    const bgClass = {
        'success': 'bg-success',
        'error': 'bg-danger',
        'warning': 'bg-warning',
        'info': 'bg-info'
    }[type] || 'bg-info';
    
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast align-items-center text-white ${bgClass} border-0`;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    container.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast, { delay: 3000 });
    bsToast.show();
    
    toast.addEventListener('hidden.bs.toast', () => toast.remove());
}

/**
 * Format a date for display
 */
function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

/**
 * Format time for display
 */
function formatTime(timeStr) {
    return timeStr;
}

// ============================================
// System Control Functions
// ============================================

/**
 * Start the attendance system
 */
async function startSystem() {
    try {
        const btn = document.getElementById('btn-start');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting...';
        }
        
        const result = await apiRequest('/api/start', { method: 'POST' });
        
        if (result.status === 'started' || result.status === 'already_running') {
            showToast('System started successfully', 'success');
            updateSystemStatus(true);
        } else {
            throw new Error(result.message || 'Failed to start');
        }
    } catch (error) {
        showToast('Failed to start system: ' + error.message, 'error');
        updateSystemStatus(false);
    }
}

/**
 * Stop the attendance system
 */
async function stopSystem() {
    try {
        const btn = document.getElementById('btn-stop');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Stopping...';
        }
        
        const result = await apiRequest('/api/stop', { method: 'POST' });
        
        showToast('System stopped', 'info');
        updateSystemStatus(false);
    } catch (error) {
        showToast('Failed to stop system: ' + error.message, 'error');
    }
}

/**
 * Update UI based on system status
 */
function updateSystemStatus(isRunning) {
    const startBtn = document.getElementById('btn-start');
    const stopBtn = document.getElementById('btn-stop');
    const statusBadge = document.getElementById('system-status');
    
    if (startBtn) {
        startBtn.disabled = isRunning;
        startBtn.innerHTML = '<i class="bi bi-play-fill"></i> Start';
    }
    
    if (stopBtn) {
        stopBtn.disabled = !isRunning;
        stopBtn.innerHTML = '<i class="bi bi-stop-fill"></i> Stop';
    }
    
    if (statusBadge) {
        if (isRunning) {
            statusBadge.className = 'badge bg-success me-2';
            statusBadge.innerHTML = '<i class="bi bi-circle-fill"></i> Running';
        } else {
            statusBadge.className = 'badge bg-secondary me-2';
            statusBadge.innerHTML = '<i class="bi bi-circle-fill"></i> Offline';
        }
    }
}

// ============================================
// Dataset Functions
// ============================================

/**
 * Encode/re-encode the face dataset
 */
async function encodeDataset() {
    if (!confirm('This will re-encode all faces in the dataset. Continue?')) {
        return;
    }
    
    try {
        showToast('Encoding dataset... This may take a while.', 'info');
        
        const result = await apiRequest('/api/encode', { method: 'POST' });
        
        if (result.status === 'success') {
            showToast('Dataset encoded successfully!', 'success');
        } else {
            throw new Error(result.error || 'Encoding failed');
        }
    } catch (error) {
        showToast('Failed to encode dataset: ' + error.message, 'error');
    }
}

// ============================================
// Data Loading Functions
// ============================================

/**
 * Load attendance records
 */
async function loadAttendance(date = null) {
    try {
        let endpoint = '/api/attendance';
        if (date) {
            endpoint += `?date=${date}`;
        }
        
        const result = await apiRequest(endpoint);
        return result.records;
    } catch (error) {
        console.error('Failed to load attendance:', error);
        return [];
    }
}

/**
 * Load student list
 */
async function loadStudents() {
    try {
        const result = await apiRequest('/api/students');
        return result.students;
    } catch (error) {
        console.error('Failed to load students:', error);
        return [];
    }
}

/**
 * Load system stats
 */
async function loadStats() {
    try {
        return await apiRequest('/api/stats');
    } catch (error) {
        console.error('Failed to load stats:', error);
        return {};
    }
}

/**
 * Load engagement data
 */
async function loadEngagement() {
    try {
        return await apiRequest('/api/engagement');
    } catch (error) {
        console.error('Failed to load engagement:', error);
        return {};
    }
}

// ============================================
// Time Display
// ============================================

/**
 * Update the current time display
 */
function updateCurrentTime() {
    const timeElement = document.getElementById('current-time');
    if (timeElement) {
        const now = new Date();
        timeElement.textContent = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
}

// ============================================
// Initialization
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('Attendance System initialized');
    
    // Update time every second
    updateCurrentTime();
    setInterval(updateCurrentTime, 1000);
    
    // Check system status on load
    loadStats().then(stats => {
        if (stats.is_running !== undefined) {
            updateSystemStatus(stats.is_running);
        }
    });
    
    // Add keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Ctrl+Shift+S to start
        if (e.ctrlKey && e.shiftKey && e.key === 'S') {
            e.preventDefault();
            startSystem();
        }
        // Ctrl+Shift+X to stop
        if (e.ctrlKey && e.shiftKey && e.key === 'X') {
            e.preventDefault();
            stopSystem();
        }
    });
});

// ============================================
// Export for use in templates
// ============================================
window.AttendanceSystem = {
    startSystem,
    stopSystem,
    encodeDataset,
    loadAttendance,
    loadStudents,
    loadStats,
    loadEngagement,
    showToast,
    formatDate,
    formatTime
};
