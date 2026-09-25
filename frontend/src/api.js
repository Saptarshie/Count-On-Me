/**
 * API client for Classroom Attendance & Engagement System
 * Supports both relative proxying and direct backend URL configuration
 */

const getBaseUrl = () => {
  const customUrl = localStorage.getItem('count_on_me_backend_url');
  if (customUrl && customUrl.trim()) {
    return customUrl.trim().replace(/\/+$/, '');
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

  // Unknown Faces Review Queue
  getUnknownFaces: () => request('/api/unknown-faces'),
  registerUnknown: (filename, name) => request('/api/unknown-faces/register', { 
    method: 'POST', 
    body: JSON.stringify({ filename, name }) 
  }),
  ignoreUnknown: (filename) => request('/api/unknown-faces/ignore', { 
    method: 'POST', 
    body: JSON.stringify({ filename }) 
  }),

  // Batch Multi-Image Attendance
  runBatchAttendance: (folder) => request('/api/batch-attendance', {
    method: 'POST',
    body: JSON.stringify({ folder })
  }),
};

