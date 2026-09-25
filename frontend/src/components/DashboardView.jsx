import React, { useState, useEffect } from 'react';
import { 
  UserCheck, 
  UserX, 
  PieChart, 
  Activity, 
  Play, 
  Square, 
  Download, 
  Clock, 
  HelpCircle, 
  Check, 
  X, 
  Layers, 
  Search, 
  ArrowRight,
  Sparkles,
  RefreshCw,
  FolderOpen
} from 'lucide-react';
import { api, getExportCsvUrl, getUnknownImageUrl, getBatchExportCsvUrl } from '../api';

export default function DashboardView({ stats, setActiveTab, onRefresh }) {
  const [attendanceRecords, setAttendanceRecords] = useState([]);
  const [realtimeEngagement, setRealtimeEngagement] = useState({});
  const [unknownFaces, setUnknownFaces] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [registeringFace, setRegisteringFace] = useState(null);
  const [studentNameInput, setStudentNameInput] = useState('');
  
  // Batch attendance state
  const [batchFolder, setBatchFolder] = useState('');
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const [batchError, setBatchError] = useState(null);

  // Poll live data every 3 seconds
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 3000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      // 1. Get today's attendance
      const attData = await api.getAttendance();
      if (attData?.records) setAttendanceRecords(attData.records);

      // 2. Get real-time engagement
      const engData = await api.getEngagement();
      if (engData) setRealtimeEngagement(engData);

      // 3. Get unknown faces queue
      const unkData = await api.getUnknownFaces();
      if (unkData?.unknown_faces) setUnknownFaces(unkData.unknown_faces);
    } catch (e) {
      console.warn('Dashboard poll error:', e);
    }
  };

  const handleRegisterUnknown = async (filename) => {
    if (!studentNameInput.trim()) return;
    try {
      await api.registerUnknown(filename, studentNameInput.trim());
      setRegisteringFace(null);
      setStudentNameInput('');
      loadData();
      if (onRefresh) onRefresh();
    } catch (err) {
      alert(`Registration failed: ${err.message}`);
    }
  };

  const handleIgnoreUnknown = async (filename) => {
    try {
      await api.ignoreUnknown(filename);
      loadData();
    } catch (err) {
      alert(`Ignore failed: ${err.message}`);
    }
  };

  const handleRunBatch = async (e) => {
    e.preventDefault();
    if (!batchFolder.trim()) return;
    setBatchLoading(true);
    setBatchError(null);
    setBatchResult(null);

    try {
      const res = await api.runBatchAttendance(batchFolder.trim());
      setBatchResult(res);
      loadData();
      if (onRefresh) onRefresh();
    } catch (err) {
      setBatchError(err.message || 'Batch attendance processing failed.');
    } finally {
      setBatchLoading(false);
    }
  };

  const filteredAttendance = attendanceRecords.filter(r => 
    r.name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Welcome Banner & System Status */}
      <div className="glass-panel" style={{
        padding: '24px',
        background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(6, 182, 212, 0.06), rgba(18, 24, 38, 0.8))',
        border: '1px solid rgba(99, 102, 241, 0.25)',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '16px'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: '#818cf8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Real-Time Vision Platform
            </span>
            <span style={{ width: '4px', height: '4px', borderRadius: '50%', background: '#64748b' }} />
            <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
              {stats?.date || new Date().toLocaleDateString()}
            </span>
          </div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800 }}>Classroom Attendance &amp; Engagement</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '4px' }}>
            Live face tracking, liveness detection, and continuous student engagement monitoring.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button 
            className="btn btn-primary"
            onClick={() => setActiveTab('live')}
          >
            <span>Live Camera Feed</span>
            <ArrowRight size={16} />
          </button>
          <a 
            href={getExportCsvUrl()} 
            download
            className="btn btn-secondary"
          >
            <Download size={16} />
            <span>Export CSV</span>
          </a>
        </div>
      </div>

      {/* 4 Top KPI Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '16px'
      }}>
        {/* Present Card */}
        <div className="glass-panel" style={{ padding: '20px', position: 'relative', overflow: 'hidden' }}>
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '4px',
            height: '100%',
            background: 'linear-gradient(to bottom, #10b981, #059669)'
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Present Today</span>
              <h2 style={{ fontSize: '2.2rem', fontWeight: 800, color: '#34d399', marginTop: '4px' }}>
                {stats?.present_count ?? 0}
              </h2>
            </div>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(16, 185, 129, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#34d399'
            }}>
              <UserCheck size={24} />
            </div>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '8px' }}>
            Out of {stats?.total_students ?? 0} enrolled students
          </div>
        </div>

        {/* Absent Card */}
        <div className="glass-panel" style={{ padding: '20px', position: 'relative', overflow: 'hidden' }}>
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '4px',
            height: '100%',
            background: 'linear-gradient(to bottom, #f43f5e, #e11d48)'
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Absent Today</span>
              <h2 style={{ fontSize: '2.2rem', fontWeight: 800, color: '#fb7185', marginTop: '4px' }}>
                {stats?.absent_count ?? 0}
              </h2>
            </div>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(244, 63, 94, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fb7185'
            }}>
              <UserX size={24} />
            </div>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '8px' }}>
            Requires follow-up / check
          </div>
        </div>

        {/* Attendance Percentage */}
        <div className="glass-panel" style={{ padding: '20px', position: 'relative', overflow: 'hidden' }}>
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '4px',
            height: '100%',
            background: 'linear-gradient(to bottom, #06b6d4, #0284c7)'
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Attendance Rate</span>
              <h2 style={{ fontSize: '2.2rem', fontWeight: 800, color: '#38bdf8', marginTop: '4px' }}>
                {(stats?.attendance_percentage ?? 0).toFixed(1)}%
              </h2>
            </div>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(6, 182, 212, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#38bdf8'
            }}>
              <PieChart size={24} />
            </div>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '8px' }}>
            Session participation rate
          </div>
        </div>

        {/* Average Engagement */}
        <div className="glass-panel" style={{ padding: '20px', position: 'relative', overflow: 'hidden' }}>
          <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '4px',
            height: '100%',
            background: 'linear-gradient(to bottom, #8b5cf6, #6366f1)'
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>Avg Engagement</span>
              <h2 style={{ fontSize: '2.2rem', fontWeight: 800, color: '#a78bfa', marginTop: '4px' }}>
                {(stats?.average_engagement ?? 0).toFixed(1)}%
              </h2>
            </div>
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '12px',
              background: 'rgba(139, 92, 246, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#a78bfa'
            }}>
              <Activity size={24} />
            </div>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '8px' }}>
            EAR, head-pose &amp; blink metrics
          </div>
        </div>
      </div>

      {/* Main Grid: Attendance Table & Live Engagement Panel */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))',
        gap: '24px'
      }}>
        {/* Attendance Records */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
            <div>
              <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Clock size={18} color="#818cf8" />
                Today's Attendance
              </h3>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                {filteredAttendance.length} records marked
              </span>
            </div>

            <div style={{ position: 'relative', minWidth: '180px' }}>
              <Search size={14} color="var(--text-dim)" style={{ position: 'absolute', left: '10px', top: '10px' }} />
              <input
                type="text"
                className="input-field"
                placeholder="Search student..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: '32px', paddingRight: '12px', paddingTop: '6px', paddingBottom: '6px', fontSize: '0.8rem' }}
              />
            </div>
          </div>

          <div style={{ overflowX: 'auto', flex: 1 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', textAlign: 'left', color: 'var(--text-dim)' }}>
                  <th style={{ padding: '10px 8px' }}>Student</th>
                  <th style={{ padding: '10px 8px' }}>Time</th>
                  <th style={{ padding: '10px 8px' }}>Engagement</th>
                  <th style={{ padding: '10px 8px' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredAttendance.length > 0 ? (
                  filteredAttendance.map((rec) => {
                    const score = rec.engagement_score ?? 0;
                    const scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
                    return (
                      <tr key={rec.id || rec.name} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                        <td style={{ padding: '12px 8px', fontWeight: 600, color: 'var(--text-main)' }}>
                          {rec.name}
                        </td>
                        <td style={{ padding: '12px 8px', color: 'var(--text-muted)' }}>
                          {rec.time}
                        </td>
                        <td style={{ padding: '12px 8px', minWidth: '130px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{
                              flex: 1,
                              height: '6px',
                              background: 'rgba(255,255,255,0.08)',
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
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: scoreColor, width: '32px' }}>
                              {Math.round(score)}%
                            </span>
                          </div>
                        </td>
                        <td style={{ padding: '12px 8px' }}>
                          <span className="badge badge-success">
                            {rec.status || 'Present'}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={4} style={{ textAlign: 'center', padding: '36px 0', color: 'var(--text-dim)' }}>
                      No attendance marked yet today. Start the system to begin recording.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Real-time Tracked Engagement Cards */}
        <div className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={18} color="#06b6d4" />
              Live Engagement Stream
            </h3>
            {stats?.is_running && (
              <span className="badge badge-info">
                {Object.keys(realtimeEngagement).length} Faces Active
              </span>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, overflowY: 'auto', maxHeight: '420px' }}>
            {Object.keys(realtimeEngagement).length > 0 ? (
              Object.entries(realtimeEngagement).map(([name, metrics]) => {
                const isAttentive = metrics.is_attentive;
                const isSleeping = metrics.is_sleeping;
                const statusColor = isSleeping ? '#f87171' : isAttentive ? '#34d399' : '#fbbf24';
                const statusText = isSleeping ? 'Drowsy / Sleeping' : isAttentive ? 'Attentive' : 'Distracted';

                return (
                  <div key={name} style={{
                    padding: '14px',
                    borderRadius: 'var(--radius-md)',
                    background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid var(--border-subtle)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{name}</span>
                      <span className={`badge ${isSleeping ? 'badge-danger' : isAttentive ? 'badge-success' : 'badge-warning'}`}>
                        {statusText}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      <div>
                        <span>Score: </span>
                        <strong style={{ color: statusColor }}>{(metrics.score ?? 0).toFixed(0)}%</strong>
                      </div>
                      <div>
                        <span>EAR: </span>
                        <strong>{(metrics.ear ?? 0).toFixed(2)}</strong>
                      </div>
                      <div>
                        <span>Blink/min: </span>
                        <strong>{metrics.blink_rate ?? 0}</strong>
                      </div>
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{
                textAlign: 'center',
                padding: '48px 20px',
                color: 'var(--text-dim)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px'
              }}>
                <Activity size={36} color="var(--text-dim)" />
                <p style={{ fontSize: '0.85rem' }}>
                  {stats?.is_running 
                    ? 'No faces currently tracked in camera view.'
                    : 'System is currently stopped. Start the system to monitor student engagement.'}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Unknown Faces Review Queue */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HelpCircle size={18} color="#f59e0b" />
              Unknown Faces Review Queue
            </h3>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginTop: '2px' }}>
              Unrecognized faces captured during live sessions. Register them as enrolled students with one click.
            </p>
          </div>
          <span className="badge badge-warning">
            {unknownFaces.length} Pending
          </span>
        </div>

        {unknownFaces.length > 0 ? (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: '16px'
          }}>
            {unknownFaces.map((face) => (
              <div key={face.filename} style={{
                borderRadius: 'var(--radius-md)',
                background: 'rgba(15, 23, 42, 0.7)',
                border: '1px solid var(--border-subtle)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column'
              }}>
                <div style={{ height: '140px', background: '#090d16', position: 'relative' }}>
                  <img
                    src={getUnknownImageUrl(face.filename)}
                    alt="Unknown face"
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                </div>
                <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                    {face.created ? new Date(face.created).toLocaleTimeString() : 'Recent'}
                  </span>

                  {registeringFace === face.filename ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="Student name"
                        value={studentNameInput}
                        onChange={(e) => setStudentNameInput(e.target.value)}
                        autoFocus
                        style={{ padding: '6px 8px', fontSize: '0.75rem' }}
                      />
                      <div style={{ display: 'flex', gap: '4px' }}>
                        <button
                          className="btn btn-success"
                          style={{ flex: 1, padding: '4px', fontSize: '0.75rem' }}
                          onClick={() => handleRegisterUnknown(face.filename)}
                        >
                          <Check size={12} />
                          <span>Save</span>
                        </button>
                        <button
                          className="btn btn-secondary"
                          style={{ padding: '4px 8px' }}
                          onClick={() => setRegisteringFace(null)}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        className="btn btn-primary"
                        style={{ flex: 1, padding: '6px 8px', fontSize: '0.75rem' }}
                        onClick={() => {
                          setRegisteringFace(face.filename);
                          setStudentNameInput('');
                        }}
                      >
                        Register
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '6px 8px' }}
                        onClick={() => handleIgnoreUnknown(face.filename)}
                        title="Dismiss"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
            No unknown faces pending review.
          </div>
        )}
      </div>

      {/* Multi-Image Batch Attendance Section */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Layers size={18} color="#8b5cf6" />
              Multi-Image Attendance &amp; Cross-Image Face Deduplication
            </h3>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginTop: '2px' }}>
              Upload or process a folder of classroom photos. Detects faces, extracts embeddings, deduplicates across photos, and marks unique students present.
            </p>
          </div>
        </div>

        <form onSubmit={handleRunBatch} style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '16px' }}>
          <div style={{ flex: 1, minWidth: '260px' }}>
            <input
              type="text"
              className="input-field"
              placeholder="Enter folder path (e.g. ref/sharukh or classroom_photos)"
              value={batchFolder}
              onChange={(e) => setBatchFolder(e.target.value)}
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={batchLoading || !batchFolder.trim()}
          >
            {batchLoading ? (
              <>
                <RefreshCw size={16} className="animate-spin" />
                <span>Processing Faces...</span>
              </>
            ) : (
              <>
                <FolderOpen size={16} />
                <span>Process Folder</span>
              </>
            )}
          </button>
        </form>

        {batchError && (
          <div style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#f87171',
            fontSize: '0.85rem',
            marginBottom: '16px'
          }}>
            {batchError}
          </div>
        )}

        {batchResult && (
          <div style={{
            background: 'rgba(15, 23, 42, 0.7)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)',
            padding: '20px'
          }}>
            {/* Quick Metrics Bar */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
              gap: '12px',
              textAlign: 'center',
              marginBottom: '20px'
            }}>
              <div>
                <h4 style={{ fontSize: '1.4rem', color: '#f8fafc' }}>{batchResult.images_processed ?? 0}</h4>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Images</span>
              </div>
              <div>
                <h4 style={{ fontSize: '1.4rem', color: '#38bdf8' }}>{batchResult.faces_detected ?? 0}</h4>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Faces Found</span>
              </div>
              <div>
                <h4 style={{ fontSize: '1.4rem', color: '#34d399' }}>{batchResult.unique_people ?? 0}</h4>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Unique People</span>
              </div>
              <div>
                <h4 style={{ fontSize: '1.4rem', color: '#fb7185' }}>{batchResult.duplicates_removed ?? 0}</h4>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Duplicates Culled</span>
              </div>
              <div>
                <h4 style={{ fontSize: '1.4rem', color: '#fbbf24' }}>{batchResult.unknown_faces ?? 0}</h4>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Unknown</span>
              </div>
            </div>

            {/* Students Identified List */}
            {batchResult.students && batchResult.students.length > 0 && (
              <div style={{ overflowX: 'auto', marginBottom: '16px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', textAlign: 'left' }}>
                      <th style={{ padding: '8px' }}>Student</th>
                      <th style={{ padding: '8px' }}>Occurrences</th>
                      <th style={{ padding: '8px' }}>Confidence</th>
                      <th style={{ padding: '8px' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batchResult.students.map((st, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '10px 8px', fontWeight: 600 }}>{st.name}</td>
                        <td style={{ padding: '10px 8px' }}>{st.occurrences} photo(s)</td>
                        <td style={{ padding: '10px 8px' }}>{(st.confidence * 100).toFixed(0)}%</td>
                        <td style={{ padding: '10px 8px' }}>
                          <span className="badge badge-success">Present</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Download Batch CSV */}
            {batchResult.csv && (
              <a
                href={getBatchExportCsvUrl(batchResult.csv)}
                download
                className="btn btn-secondary"
                style={{ fontSize: '0.8rem' }}
              >
                <Download size={14} />
                <span>Download Deduplicated Batch CSV</span>
              </a>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
