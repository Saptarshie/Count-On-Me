import React, { useState, useEffect } from 'react';
import { 
  Calendar, 
  CalendarDays, 
  Download, 
  Search, 
  UserCheck, 
  Activity, 
  Clock, 
  Plus, 
  Trash2, 
  Edit3, 
  CheckCircle2, 
  AlertCircle, 
  X, 
  Radio, 
  BookOpen, 
  Check, 
  UserPlus, 
  Sliders,
  ChevronRight,
  Sparkles
} from 'lucide-react';
import { api, getExportCsvUrl } from '../api';

export default function AttendanceView({ onSessionChange }) {
  const [selectedDate, setSelectedDate] = useState(() => {
    return new Date().toISOString().split('T')[0];
  });
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [selectedSessionId, setSelectedSessionId] = useState('all');
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [toastMsg, setToastMsg] = useState(null);

  // Modals state
  const [newSessionModalOpen, setNewSessionModalOpen] = useState(false);
  const [markStudentModalOpen, setMarkStudentModalOpen] = useState(false);
  const [editScoreModalOpen, setEditScoreModalOpen] = useState(null); // record object or null
  const [allStudentsList, setAllStudentsList] = useState([]);

  // Form states
  const [newSessionForm, setNewSessionForm] = useState({
    course: 'Physics',
    title: 'Lecture 1: General Mechanics',
    date: selectedDate,
    start_time: '09:00',
    end_time: '10:30',
    room: 'Room 101',
    set_active: true
  });

  const [markForm, setMarkForm] = useState({
    student_name: '',
    status: 'Present',
    engagement_score: 100
  });

  const showToast = (text, isError = false) => {
    setToastMsg({ text, isError });
    setTimeout(() => setToastMsg(null), 3500);
  };

  // Sync date changes with new session form
  useEffect(() => {
    setNewSessionForm(prev => ({ ...prev, date: selectedDate }));
    fetchSessions(selectedDate);
  }, [selectedDate]);

  // Load students for autocomplete
  useEffect(() => {
    api.getStudents()
      .then(res => setAllStudentsList(res?.students || []))
      .catch(() => {});
  }, []);

  // Fetch sessions for date
  const fetchSessions = async (dateStr) => {
    setLoading(true);
    try {
      const data = await api.getSessions(dateStr);
      const list = data?.sessions || [];
      setSessions(list);
      setActiveSessionId(data?.active_session_id || null);

      // Select default session
      if (list.length > 0) {
        // If current selectedSessionId is in list, keep it. Else if active session is in list, pick it, else pick first
        setSelectedSessionId(prev => {
          if (prev !== 'all' && list.some(s => s.session_id === prev)) return prev;
          if (data?.active_session_id && list.some(s => s.session_id === data.active_session_id)) {
            return data.active_session_id;
          }
          return list[0].session_id;
        });
      } else {
        setSelectedSessionId('all');
      }
    } catch (err) {
      console.error('Error fetching sessions:', err);
      showToast(`Failed to load sessions: ${err.message}`, true);
    } finally {
      setLoading(false);
    }
  };

  // Fetch records whenever session or date changes
  useEffect(() => {
    fetchRecords();
  }, [selectedSessionId, selectedDate]);

  const fetchRecords = async () => {
    setLoading(true);
    try {
      let data;
      if (selectedSessionId === 'all') {
        data = await api.getAttendance({ date: selectedDate });
      } else {
        data = await api.getAttendance({ session_id: selectedSessionId });
      }
      setRecords(data?.records || []);
    } catch (err) {
      console.error('Error fetching records:', err);
    } finally {
      setLoading(false);
    }
  };

  // Switch active session for live camera
  const handleSetActiveSession = async (sessionId) => {
    try {
      const res = await api.setActiveSession(sessionId);
      if (res?.status === 'success') {
        setActiveSessionId(sessionId);
        showToast('Live camera is now recording attendance for this session!');
        fetchSessions(selectedDate);
        if (onSessionChange) onSessionChange();
      }
    } catch (err) {
      showToast(`Could not set active session: ${err.message}`, true);
    }
  };

  // Create new session
  const handleCreateSession = async (e) => {
    e.preventDefault();
    if (!newSessionForm.title.trim()) {
      showToast('Session title is required', true);
      return;
    }
    try {
      const res = await api.createSession({
        ...newSessionForm,
        date: selectedDate
      });
      if (res?.status === 'success') {
        showToast(`Created session "${res.session.title}"!`);
        setNewSessionModalOpen(false);
        await fetchSessions(selectedDate);
        setSelectedSessionId(res.session.session_id);
        if (onSessionChange) onSessionChange();
      }
    } catch (err) {
      showToast(`Failed to create session: ${err.message}`, true);
    }
  };

  // Delete session
  const handleDeleteSession = async (sessionId, sessionTitle) => {
    if (!window.confirm(`Delete session "${sessionTitle}"?\n\nWARNING: This will permanently delete this session and all student attendance records logged under it.`)) {
      return;
    }

    try {
      const res = await api.deleteSession(sessionId);
      if (res?.status === 'success') {
        showToast(`Session "${sessionTitle}" deleted successfully`);
        await fetchSessions(selectedDate);
        if (onSessionChange) onSessionChange();
      }
    } catch (err) {
      showToast(`Failed to delete session: ${err.message}`, true);
    }
  };

  // Update student status (Manual Correction)
  const handleUpdateStatus = async (recordId, newStatus) => {
    try {
      // Optimistic update
      setRecords(prev => prev.map(r => r.id === recordId ? { ...r, status: newStatus } : r));
      
      const current = records.find(r => r.id === recordId);
      const score = current ? current.engagement_score : null;
      await api.updateAttendanceStatus(recordId, newStatus, score);
      showToast(`Status updated to "${newStatus}"`);
    } catch (err) {
      showToast(`Failed to update status: ${err.message}`, true);
      fetchRecords(); // rollback
    }
  };

  // Update engagement score (Manual Correction)
  const handleSaveScore = async (e) => {
    e.preventDefault();
    if (!editScoreModalOpen) return;
    try {
      const { id, status, engagement_score } = editScoreModalOpen;
      await api.updateAttendanceStatus(id, status, engagement_score);
      setRecords(prev => prev.map(r => r.id === id ? { ...r, engagement_score: parseFloat(engagement_score) } : r));
      showToast(`Engagement score updated to ${engagement_score}%`);
      setEditScoreModalOpen(null);
    } catch (err) {
      showToast(`Failed to update score: ${err.message}`, true);
    }
  };

  // Manually mark student in current session
  const handleManualMarkStudent = async (e) => {
    e.preventDefault();
    if (!markForm.student_name.trim()) {
      showToast('Student name is required', true);
      return;
    }

    let targetSessionId = selectedSessionId !== 'all' ? selectedSessionId : activeSessionId;
    if (!targetSessionId && sessions.length > 0) {
      targetSessionId = sessions[0].session_id;
    }

    if (!targetSessionId) {
      showToast('Please create or select a session first', true);
      return;
    }

    try {
      const res = await api.manualMarkAttendance({
        session_id: targetSessionId,
        student_name: markForm.student_name.trim(),
        status: markForm.status,
        engagement_score: parseFloat(markForm.engagement_score)
      });

      if (res?.status === 'success') {
        showToast(`Attendance recorded for ${markForm.student_name}`);
        setMarkStudentModalOpen(false);
        setMarkForm({ student_name: '', status: 'Present', engagement_score: 100 });
        fetchRecords();
        fetchSessions(selectedDate);
      } else {
        showToast(res?.message || 'Failed to mark attendance', true);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, true);
    }
  };

  // Delete attendance record
  const handleDeleteRecord = async (recordId, studentName) => {
    if (!window.confirm(`Remove ${studentName}'s attendance record for this session?`)) return;
    try {
      await api.deleteAttendanceRecord(recordId);
      setRecords(prev => prev.filter(r => r.id !== recordId));
      showToast(`Record for ${studentName} removed`);
      fetchSessions(selectedDate);
    } catch (err) {
      showToast(`Failed to delete record: ${err.message}`, true);
    }
  };

  const filteredRecords = records.filter(r => 
    (r.name || r.student_name || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  const avgEngagement = records.length > 0 
    ? (records.reduce((acc, r) => acc + (r.engagement_score || 0), 0) / records.length).toFixed(1)
    : 0;

  const currentSelectedSession = sessions.find(s => s.session_id === selectedSessionId);

  // Status badge styling helper
  const getStatusBadge = (status) => {
    switch (status?.toLowerCase()) {
      case 'present':
        return { bg: 'rgba(16, 185, 129, 0.15)', color: '#34d399', border: 'rgba(16, 185, 129, 0.3)' };
      case 'late':
        return { bg: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: 'rgba(245, 158, 11, 0.3)' };
      case 'excused':
        return { bg: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: 'rgba(56, 189, 248, 0.3)' };
      case 'absent':
        return { bg: 'rgba(239, 68, 68, 0.15)', color: '#f87171', border: 'rgba(239, 68, 68, 0.3)' };
      default:
        return { bg: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', border: 'rgba(99, 102, 241, 0.3)' };
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* Toast Alert */}
      {toastMsg && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          zIndex: 9999,
          background: toastMsg.isError ? 'rgba(239, 68, 68, 0.95)' : 'rgba(16, 185, 129, 0.95)',
          color: '#ffffff',
          padding: '12px 20px',
          borderRadius: '12px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontWeight: 600,
          fontSize: '0.9rem',
          animation: 'fadeIn 0.2s ease-out'
        }}>
          {toastMsg.isError ? <AlertCircle size={18} /> : <Check size={18} />}
          <span>{toastMsg.text}</span>
        </div>
      )}

      {/* Top Header: Date Picker & Primary Session Actions */}
      <div className="glass-panel" style={{
        padding: '20px 24px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px'
      }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CalendarDays size={24} color="#818cf8" />
            Classroom Sessions &amp; Attendance
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '2px' }}>
            Manage multiple class sessions per day (e.g. Physics, Chemistry), switch camera target, and manually correct student attendance.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Date Selector */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            background: 'rgba(255, 255, 255, 0.04)',
            padding: '4px 10px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)'
          }}>
            <Calendar size={18} color="var(--text-dim)" />
            <input
              type="date"
              className="input-field"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{ width: 'auto', padding: '6px 8px', fontSize: '0.85rem', border: 'none', background: 'transparent' }}
            />
          </div>

          {/* New Session Button */}
          <button
            className="btn btn-primary"
            onClick={() => setNewSessionModalOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <Plus size={16} />
            <span>New Session</span>
          </button>

          {/* Export CSV Button */}
          <a
            href={getExportCsvUrl(selectedSessionId !== 'all' ? selectedSessionId : null, selectedDate)}
            download
            className="btn btn-secondary"
            title="Download CSV report"
          >
            <Download size={16} />
            <span className="hide-on-mobile">Export CSV</span>
          </a>
        </div>
      </div>

      {/* Multiple Sessions Bar: Tabs/Cards for this Day */}
      <div className="glass-panel" style={{ padding: '16px 20px' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '12px',
          flexWrap: 'wrap',
          gap: '8px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <BookOpen size={18} color="#818cf8" />
            <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#f8fafc' }}>
              Sessions on {selectedDate} ({sessions.length})
            </span>
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
            Click a session to view its roster or change its active status
          </span>
        </div>

        {sessions.length > 0 ? (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
            gap: '12px'
          }}>
            {/* "All Sessions" Tab */}
            <div
              onClick={() => setSelectedSessionId('all')}
              style={{
                cursor: 'pointer',
                padding: '14px 16px',
                borderRadius: 'var(--radius-md)',
                background: selectedSessionId === 'all' ? 'rgba(99, 102, 241, 0.16)' : 'rgba(255, 255, 255, 0.03)',
                border: `1.5px solid ${selectedSessionId === 'all' ? '#6366f1' : 'var(--border-subtle)'}`,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: '8px',
                transition: 'all 0.2s ease'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: '#818cf8' }}>
                  Full Day Summary
                </span>
                <span className="badge" style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>
                  All Sessions
                </span>
              </div>
              <div style={{ fontWeight: 700, fontSize: '1rem', color: '#f8fafc' }}>
                All Sessions Combined
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between' }}>
                <span>{sessions.reduce((acc, s) => acc + (s.present_count || 0), 0)} Total Marks</span>
                <span>{selectedDate}</span>
              </div>
            </div>

            {/* Individual Session Cards */}
            {sessions.map((s) => {
              const isSelected = selectedSessionId === s.session_id;
              const isLiveActive = activeSessionId === s.session_id;

              return (
                <div
                  key={s.session_id}
                  onClick={() => setSelectedSessionId(s.session_id)}
                  style={{
                    cursor: 'pointer',
                    padding: '14px 16px',
                    borderRadius: 'var(--radius-md)',
                    background: isSelected ? 'rgba(99, 102, 241, 0.16)' : 'rgba(255, 255, 255, 0.03)',
                    border: `1.5px solid ${isSelected ? '#6366f1' : isLiveActive ? 'rgba(16, 185, 129, 0.4)' : 'var(--border-subtle)'}`,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '10px',
                    transition: 'all 0.2s ease',
                    position: 'relative'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{
                        fontSize: '0.7rem',
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        padding: '2px 8px',
                        borderRadius: '6px',
                        background: 'rgba(99, 102, 241, 0.2)',
                        color: '#a5b4fc',
                        letterSpacing: '0.04em'
                      }}>
                        {s.course || 'Class'}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                        {s.room || 'Classroom'}
                      </span>
                    </div>

                    {isLiveActive ? (
                      <span style={{
                        fontSize: '0.65rem',
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: '999px',
                        background: 'rgba(16, 185, 129, 0.2)',
                        color: '#34d399',
                        border: '1px solid rgba(16, 185, 129, 0.4)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px'
                      }}>
                        <span className="pulse-indicator" style={{ width: '6px', height: '6px' }} />
                        Live Target
                      </span>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSetActiveSession(s.session_id);
                        }}
                        style={{
                          background: 'rgba(255,255,255,0.06)',
                          border: 'none',
                          color: 'var(--text-dim)',
                          fontSize: '0.68rem',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                        title="Direct live camera to record attendance in this session"
                      >
                        Set Live Target
                      </button>
                    )}
                  </div>

                  <div>
                    <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {s.title}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {s.start_time} - {s.end_time}
                    </div>
                  </div>

                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    borderTop: '1px solid rgba(255,255,255,0.04)',
                    paddingTop: '8px'
                  }}>
                    <span style={{ fontSize: '0.78rem', color: '#34d399', fontWeight: 600 }}>
                      {s.present_count || 0} Students Present
                    </span>

                    {/* Delete Session Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteSession(s.session_id, s.title);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: '#f87171',
                        cursor: 'pointer',
                        padding: '4px',
                        borderRadius: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        opacity: 0.7
                      }}
                      title={`Delete session "${s.title}"`}
                      onMouseEnter={(e) => e.currentTarget.style.opacity = 1}
                      onMouseLeave={(e) => e.currentTarget.style.opacity = 0.7}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{
            textAlign: 'center',
            padding: '24px 16px',
            color: 'var(--text-dim)',
            background: 'rgba(255, 255, 255, 0.02)',
            borderRadius: 'var(--radius-md)',
            border: '1px dashed var(--border-subtle)'
          }}>
            <p style={{ marginBottom: '10px', fontSize: '0.9rem' }}>
              No classroom sessions found for {selectedDate}.
            </p>
            <button
              className="btn btn-primary"
              style={{ fontSize: '0.8rem', padding: '6px 14px' }}
              onClick={() => setNewSessionModalOpen(true)}
            >
              <Plus size={14} />
              <span>Create First Session (e.g. Physics, Chemistry)</span>
            </button>
          </div>
        )}
      </div>

      {/* Selected Session Metrics Bar */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '16px'
      }}>
        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '42px',
            height: '42px',
            borderRadius: '10px',
            background: 'rgba(16, 185, 129, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#34d399'
          }}>
            <UserCheck size={22} />
          </div>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
              {selectedSessionId === 'all' ? 'All Sessions Present' : 'Session Present Count'}
            </span>
            <h3 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#34d399' }}>{records.length}</h3>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '42px',
            height: '42px',
            borderRadius: '10px',
            background: 'rgba(139, 92, 246, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#a78bfa'
          }}>
            <Activity size={22} />
          </div>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Average Engagement</span>
            <h3 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#a78bfa' }}>{avgEngagement}%</h3>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '42px',
            height: '42px',
            borderRadius: '10px',
            background: 'rgba(6, 182, 212, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#38bdf8'
          }}>
            <Clock size={22} />
          </div>
          <div style={{ overflow: 'hidden' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Target Session</span>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
              {currentSelectedSession ? currentSelectedSession.title : 'All Combined'}
            </h3>
          </div>
        </div>
      </div>

      {/* Attendance Roster Table with In-line Correction */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '16px',
          flexWrap: 'wrap',
          gap: '12px'
        }}>
          <div>
            <h2 style={{ fontSize: '1.15rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>Session Roster ({filteredRecords.length})</span>
              {currentSelectedSession && (
                <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#818cf8', background: 'rgba(99, 102, 241, 0.15)', padding: '2px 8px', borderRadius: '6px' }}>
                  {currentSelectedSession.course} - {currentSelectedSession.title}
                </span>
              )}
            </h2>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '2px' }}>
              Click status badges to manually correct attendance (Present, Late, Excused, Absent) or adjust engagement scores.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            {/* Search Box */}
            <div style={{ position: 'relative', minWidth: '200px' }}>
              <Search size={14} color="var(--text-dim)" style={{ position: 'absolute', left: '10px', top: '12px' }} />
              <input
                type="text"
                className="input-field"
                placeholder="Search student..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: '32px' }}
              />
            </div>

            {/* Manual Add Student Button */}
            <button
              className="btn btn-secondary"
              onClick={() => setMarkStudentModalOpen(true)}
              style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem' }}
            >
              <UserPlus size={15} />
              <span>+ Mark Student</span>
            </button>
          </div>
        </div>

        {/* Table */}
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', textAlign: 'left' }}>
                <th style={{ padding: '12px 10px', width: '40px' }}>#</th>
                <th style={{ padding: '12px 10px' }}>Student Name</th>
                {selectedSessionId === 'all' && <th style={{ padding: '12px 10px' }}>Session</th>}
                <th style={{ padding: '12px 10px' }}>Time</th>
                <th style={{ padding: '12px 10px', minWidth: '180px' }}>Engagement Score</th>
                <th style={{ padding: '12px 10px' }}>Status (Click to Correct)</th>
                <th style={{ padding: '12px 10px', textAlign: 'right', width: '90px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecords.length > 0 ? (
                filteredRecords.map((rec, i) => {
                  const studentName = rec.name || rec.student_name;
                  const score = rec.engagement_score ?? 0;
                  const scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
                  const badgeStyle = getStatusBadge(rec.status);

                  return (
                    <tr key={rec.id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      <td style={{ padding: '12px 10px', color: 'var(--text-dim)' }}>{i + 1}</td>
                      
                      {/* Student Name */}
                      <td style={{ padding: '12px 10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            width: '32px',
                            height: '32px',
                            borderRadius: '50%',
                            background: 'rgba(99, 102, 241, 0.2)',
                            color: '#818cf8',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontWeight: 700,
                            fontSize: '0.8rem'
                          }}>
                            {studentName?.[0]?.toUpperCase() || 'S'}
                          </div>
                          <div>
                            <span style={{ fontWeight: 600, color: '#f8fafc' }}>{studentName}</span>
                          </div>
                        </div>
                      </td>

                      {/* Session Name if "All" is active */}
                      {selectedSessionId === 'all' && (
                        <td style={{ padding: '12px 10px', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                          <span style={{ background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' }}>
                            {rec.course || 'Class'}: {rec.session_title || rec.session_id || 'General'}
                          </span>
                        </td>
                      )}

                      {/* Time */}
                      <td style={{ padding: '12px 10px', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                        {rec.time}
                      </td>

                      {/* Engagement Score & Edit Icon */}
                      <td style={{ padding: '12px 10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <div style={{
                            flex: 1,
                            height: '7px',
                            background: 'rgba(255, 255, 255, 0.08)',
                            borderRadius: '999px',
                            overflow: 'hidden'
                          }}>
                            <div style={{
                              width: `${Math.min(100, Math.max(0, score))}%`,
                              height: '100%',
                              background: scoreColor,
                              borderRadius: '999px'
                            }} />
                          </div>
                          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: scoreColor, minWidth: '36px' }}>
                            {Math.round(score)}%
                          </span>
                          <button
                            onClick={() => setEditScoreModalOpen(rec)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--text-dim)',
                              cursor: 'pointer',
                              padding: '2px'
                            }}
                            title="Edit engagement score"
                          >
                            <Sliders size={13} />
                          </button>
                        </div>
                      </td>

                      {/* Manual Status Dropdown / Correction */}
                      <td style={{ padding: '12px 10px' }}>
                        <select
                          value={rec.status || 'Present'}
                          onChange={(e) => handleUpdateStatus(rec.id, e.target.value)}
                          style={{
                            background: badgeStyle.bg,
                            color: badgeStyle.color,
                            border: `1px solid ${badgeStyle.border}`,
                            padding: '4px 8px',
                            borderRadius: '6px',
                            fontWeight: 700,
                            fontSize: '0.78rem',
                            cursor: 'pointer',
                            outline: 'none'
                          }}
                        >
                          <option value="Present" style={{ background: '#0f172a', color: '#34d399' }}>✓ Present</option>
                          <option value="Late" style={{ background: '#0f172a', color: '#fbbf24' }}>⏳ Late</option>
                          <option value="Excused" style={{ background: '#0f172a', color: '#38bdf8' }}>📄 Excused</option>
                          <option value="Absent" style={{ background: '#0f172a', color: '#f87171' }}>✗ Absent</option>
                        </select>
                      </td>

                      {/* Delete Action */}
                      <td style={{ padding: '12px 10px', textAlign: 'right' }}>
                        <button
                          onClick={() => handleDeleteRecord(rec.id, studentName)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-dim)',
                            cursor: 'pointer',
                            padding: '6px',
                            borderRadius: '6px'
                          }}
                          title="Delete this attendance record"
                          onMouseEnter={(e) => e.currentTarget.style.color = '#f87171'}
                          onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={selectedSessionId === 'all' ? 7 : 6} style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-dim)' }}>
                    {loading ? 'Loading attendance...' : (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                        <span>No student attendance records recorded yet.</span>
                        <button
                          className="btn btn-secondary"
                          style={{ fontSize: '0.8rem', padding: '4px 12px' }}
                          onClick={() => setMarkStudentModalOpen(true)}
                        >
                          <UserPlus size={14} />
                          <span>+ Mark Student Manually</span>
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal 1: Create New Classroom Session */}
      {newSessionModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            maxWidth: '520px',
            width: '100%',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <BookOpen size={20} color="#818cf8" />
                Create Classroom Session
              </h3>
              <button
                onClick={() => setNewSessionModalOpen(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Schedule multiple distinct class sessions on the same date (e.g. Physics, Chemistry, Math) to keep attendance separate.
            </p>

            <form onSubmit={handleCreateSession} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Quick Course Suggestions */}
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Course / Subject
                </label>
                <div style={{ display: 'flex', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
                  {['Physics', 'Chemistry', 'Mathematics', 'Computer Science', 'Biology'].map(subj => (
                    <button
                      key={subj}
                      type="button"
                      onClick={() => setNewSessionForm(f => ({ ...f, course: subj, title: `${subj} Class` }))}
                      style={{
                        background: newSessionForm.course === subj ? 'rgba(99, 102, 241, 0.3)' : 'rgba(255,255,255,0.05)',
                        border: `1px solid ${newSessionForm.course === subj ? '#818cf8' : 'var(--border-subtle)'}`,
                        color: newSessionForm.course === subj ? '#c7d2fe' : 'var(--text-muted)',
                        padding: '4px 10px',
                        borderRadius: '6px',
                        fontSize: '0.75rem',
                        cursor: 'pointer'
                      }}
                    >
                      {subj}
                    </button>
                  ))}
                </div>
                <input
                  type="text"
                  className="input-field"
                  value={newSessionForm.course}
                  onChange={(e) => setNewSessionForm({ ...newSessionForm, course: e.target.value })}
                  placeholder="e.g. Physics, Chemistry, CS101"
                  required
                />
              </div>

              {/* Title / Topic */}
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Session Title / Topic
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={newSessionForm.title}
                  onChange={(e) => setNewSessionForm({ ...newSessionForm, title: e.target.value })}
                  placeholder="e.g. Thermodynamics Lecture, Organic Chemistry Lab"
                  required
                />
              </div>

              {/* Date & Room */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                    Date
                  </label>
                  <input
                    type="date"
                    className="input-field"
                    value={newSessionForm.date}
                    onChange={(e) => setNewSessionForm({ ...newSessionForm, date: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                    Room / Lab
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={newSessionForm.room}
                    onChange={(e) => setNewSessionForm({ ...newSessionForm, room: e.target.value })}
                    placeholder="e.g. Hall A, Lab 3"
                  />
                </div>
              </div>

              {/* Start & End Times */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                    Start Time
                  </label>
                  <input
                    type="time"
                    className="input-field"
                    value={newSessionForm.start_time}
                    onChange={(e) => setNewSessionForm({ ...newSessionForm, start_time: e.target.value })}
                    required
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                    End Time
                  </label>
                  <input
                    type="time"
                    className="input-field"
                    value={newSessionForm.end_time}
                    onChange={(e) => setNewSessionForm({ ...newSessionForm, end_time: e.target.value })}
                    required
                  />
                </div>
              </div>

              {/* Set as Active for Live Camera Checkbox */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                background: 'rgba(99, 102, 241, 0.1)',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                border: '1px solid rgba(99, 102, 241, 0.25)'
              }}>
                <input
                  type="checkbox"
                  id="set_active_cb"
                  checked={newSessionForm.set_active}
                  onChange={(e) => setNewSessionForm({ ...newSessionForm, set_active: e.target.checked })}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                <label htmlFor="set_active_cb" style={{ fontSize: '0.82rem', color: '#c7d2fe', cursor: 'pointer', fontWeight: 600 }}>
                  Set as active target for live camera tracking now
                </label>
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setNewSessionModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Create Session
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal 2: Manual Student Attendance Entry */}
      {markStudentModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            maxWidth: '460px',
            width: '100%',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <UserPlus size={20} color="#34d399" />
                Mark Student Attendance
              </h3>
              <button
                onClick={() => setMarkStudentModalOpen(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Manually add or correct a student's attendance in session{' '}
              <strong style={{ color: '#818cf8' }}>
                {currentSelectedSession ? currentSelectedSession.title : (sessions[0]?.title || 'Active Session')}
              </strong>.
            </p>

            <form onSubmit={handleManualMarkStudent} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Student Name */}
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Student Name
                </label>
                <input
                  type="text"
                  list="registered_students_list"
                  className="input-field"
                  value={markForm.student_name}
                  onChange={(e) => setMarkForm({ ...markForm, student_name: e.target.value })}
                  placeholder="Select or type student name..."
                  required
                />
                <datalist id="registered_students_list">
                  {allStudentsList.map(s => (
                    <option key={s.id} value={s.name}>{s.student_id} - {s.department || ''}</option>
                  ))}
                </datalist>
              </div>

              {/* Status Select */}
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Attendance Status
                </label>
                <select
                  className="input-field"
                  value={markForm.status}
                  onChange={(e) => setMarkForm({ ...markForm, status: e.target.value })}
                >
                  <option value="Present">Present</option>
                  <option value="Late">Late</option>
                  <option value="Excused">Excused</option>
                  <option value="Absent">Absent</option>
                </select>
              </div>

              {/* Engagement Score */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <label style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                    Engagement Score
                  </label>
                  <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#818cf8' }}>
                    {markForm.engagement_score}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={markForm.engagement_score}
                  onChange={(e) => setMarkForm({ ...markForm, engagement_score: e.target.value })}
                  style={{ width: '100%', cursor: 'pointer' }}
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setMarkStudentModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-success">
                  Save Attendance
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal 3: Edit Engagement Score Modal */}
      {editScoreModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            maxWidth: '380px',
            width: '100%',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 700 }}>
                Adjust Engagement Score
              </h3>
              <button
                onClick={() => setEditScoreModalOpen(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
              Student: <strong style={{ color: '#f8fafc' }}>{editScoreModalOpen.name || editScoreModalOpen.student_name}</strong>
            </p>

            <form onSubmit={handleSaveScore} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>Score</span>
                  <span style={{ fontSize: '1rem', fontWeight: 800, color: '#818cf8' }}>
                    {Math.round(editScoreModalOpen.engagement_score || 0)}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={editScoreModalOpen.engagement_score || 0}
                  onChange={(e) => setEditScoreModalOpen({ ...editScoreModalOpen, engagement_score: parseFloat(e.target.value) })}
                  style={{ width: '100%', cursor: 'pointer' }}
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setEditScoreModalOpen(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Score
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
