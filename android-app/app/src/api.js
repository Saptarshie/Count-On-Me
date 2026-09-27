/**
 * API client for Classroom Attendance & Engagement System
 * Supports three modes:
 *   1. Native Android app  -> local NanoHTTPD server inside the APK (127.0.0.1:8971), fully offline
 *   2. Custom backend URL   -> direct connection to a PC running the Flask backend (dev mode)
 *   3. Relative (browser)   -> Vite dev proxy on localhost:3000
 */

// Local in-app server (embedded in the APK). Must match LocalServer.PORT in Kotlin.
const NATIVE_BASE_URL = 'http://127.0.0.1:8971';

const isNativeAndroid = () => {
  try {
    return typeof window !== 'undefined'
      && typeof window.Capacitor !== 'undefined'
      && typeof window.Capacitor.isNativePlatform === 'function'
      && window.Capacitor.isNativePlatform();
  } catch (e) { return false; }
};

export const isNativeMode = () => isNativeAndroid();

const getBaseUrl = () => {
  // In the Android shell, the embedded local server always serves first;
  // a custom URL still wins so devs can point the app at the PC backend.
  const customUrl = localStorage.getItem('count_on_me_backend_url');
  if (customUrl && customUrl.trim()) {
    return customUrl.trim().replace(/\/+$/, '');
  }
  if (isNativeAndroid()) {
    return NATIVE_BASE_URL;
  }
  return '';
};

export const setCustomBackendUrl = (url) => {
  if (!url || !url.trim()) {
    localStorage.removeItem('count_on_me_backend_url');
  } else {
    localStorage.setItem('count_on_me_backend_url', url.trim().replace(/\/+$/, ''));
  }
};

export const getCustomBackendUrl = () => {
  return localStorage.getItem('count_on_me_backend_url') || '';
};

export const getVideoFeedUrl = () => {
  const base = getBaseUrl();
  return `${base}/video_feed`;
};

// Single-frame snapshot of the live engine — deterministic fallback for the
// native shell (some Android WebViews don't render MJPEG in <img>).
export const getVideoSnapshotUrl = () => {
  const base = getBaseUrl();
  return `${base}/video_snapshot.jpg`;
};

// Hand a server file (CSV export) to the native DownloadManager.
export const saveFileNative = async (url, filename) => {
  if (isNativeMode() && window.Capacitor?.Plugins?.SaveFile) {
    await window.Capacitor.Plugins.SaveFile.saveFile({ url, filename });
    return true;
  }
  return false;
};

export const getEventsStreamUrl = () => {
  const base = getBaseUrl();
  return `${base}/api/stream/events`;
};

export const getExportCsvUrl = (sessionId, dateStr) => {
  const base = getBaseUrl();
  const params = new URLSearchParams();
  if (sessionId) params.append('session_id', sessionId);
  if (dateStr) params.append('date', dateStr);
  const q = params.toString();
  return `${base}/api/export/csv${q ? `?${q}` : ''}`;
};

export const getUnknownImageUrl = (filename) => {
  const base = getBaseUrl();
  return `${base}/unknown/${filename}`;
};

export const getBatchExportCsvUrl = (csvFilename) => {
  const base = getBaseUrl();
  // if backend gave relative or filename
  const fname = csvFilename.split(/[\/\\]/).pop();
  return `${base}/exports/${fname}`;
};

// In the native Android shell the web app itself is served from the local
// server, so the base URL of the current page IS the API base.
export const getWebAppOrigin = () => {
  if (isNativeAndroid()) return NATIVE_BASE_URL;
  return window.location.origin;
};

async function request(endpoint, options = {}) {
  const base = getBaseUrl();
  const url = `${base}${endpoint}`;
  
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const res = await fetch(url, {
      ...options,
      headers,
    });
    
    // Handle CSV or blob responses
    if (options.asBlob) {
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.blob();
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || data.message || `Request failed with status ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`API Error on [${options.method || 'GET'} ${url}]:`, err);
    throw err;
  }
}

export const api = {
  // Stats & System Control
  getStats: (sessionId) => {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return request(`/api/stats${query}`);
  },
  startSystem: () => request('/api/start', { method: 'POST' }),
  stopSystem: () => request('/api/stop', { method: 'POST' }),
  flipCamera: () => request('/api/camera/flip', { method: 'POST' }),
  encodeDataset: () => request('/api/encode', { method: 'POST' }),

  // Sessions Management
  getSessions: (dateStr) => {
    const query = dateStr ? `?date=${encodeURIComponent(dateStr)}` : '';
    return request(`/api/sessions${query}`);
  },
  createSession: (sessionData) => request('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(sessionData)
  }),
  getActiveSession: () => request('/api/sessions/active'),
  setActiveSession: (sessionId) => request('/api/sessions/active', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId })
  }),
  deleteSession: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE'
  }),

  // Attendance
  getAttendance: (filter) => {
    let query = '';
    if (typeof filter === 'string') {
      query = filter ? `?date=${encodeURIComponent(filter)}` : '';
    } else if (filter && typeof filter === 'object') {
      const p = new URLSearchParams();
      if (filter.session_id) p.append('session_id', filter.session_id);
      if (filter.date) p.append('date', filter.date);
      const s = p.toString();
      query = s ? `?${s}` : '';
    }
    return request(`/api/attendance${query}`);
  },
  updateAttendanceStatus: (recordId, status, engagementScore) => request(`/api/attendance/${recordId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, engagement_score: engagementScore })
  }),
  manualMarkAttendance: (payload) => request('/api/attendance/manual', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  deleteAttendanceRecord: (recordId) => request(`/api/attendance/${recordId}`, {
    method: 'DELETE'
  }),

  // Real-time Engagement
  getEngagement: () => request('/api/engagement'),

  // Students
  getStudents: () => request('/api/students'),
  addStudent: (student) => request('/api/students', { method: 'POST', body: JSON.stringify(student) }),
  deleteStudent: (studentId) => request(`/api/students/${encodeURIComponent(studentId)}`, { method: 'DELETE' }),

  // Full Registration (Images + DB + Live Encodings)
  registerStudent: (payload) => request('/api/register-student', { method: 'POST', body: JSON.stringify(payload) }),

  // Unknown Faces Review Queue & Clustering
  getUnknownFaces: (cluster = false) => request(`/api/unknown-faces${cluster ? '?cluster=true' : ''}`),
  clusterifyUnknownFaces: () => request('/api/unknown-faces/clusterify', { method: 'POST' }),
  clearUnknownFaces: () => request('/api/unknown-faces/clear', { method: 'POST' }),
  registerUnknown: (payload) => request('/api/unknown-faces/register', { 
    method: 'POST', 
    body: JSON.stringify(typeof payload === 'string' ? { filename: payload } : payload) 
  }),
  registerUnknownCluster: (payload) => request('/api/unknown-faces/register-cluster', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  ignoreUnknown: (filenames) => request('/api/unknown-faces/ignore', { 
    method: 'POST', 
    body: JSON.stringify(Array.isArray(filenames) ? { filenames } : { filename: filenames }) 
  }),

  // Batch Multi-Image Attendance
  runBatchAttendance: (folder) => request('/api/batch-attendance', {
    method: 'POST',
    body: JSON.stringify({ folder })
  }),

  // Detection & Recognition Tuning
  getTuning: () => request('/api/tuning'),
  updateTuning: (tuningData) => request('/api/tuning', {
    method: 'POST',
    body: JSON.stringify(tuningData)
  }),
};

