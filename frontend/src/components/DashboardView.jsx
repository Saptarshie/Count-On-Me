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
  FolderOpen,
  UserPlus,
  Trash2,
  Users,
  Image,
  AlertCircle
} from 'lucide-react';
import { api, getExportCsvUrl, getUnknownImageUrl, getBatchExportCsvUrl } from '../api';

export default function DashboardView({ stats, setActiveTab, onRefresh }) {
  const [attendanceRecords, setAttendanceRecords] = useState([]);
  const [realtimeEngagement, setRealtimeEngagement] = useState({});
  const [unknownFaces, setUnknownFaces] = useState([]);
  const [faceClusters, setFaceClusters] = useState([]);
  const [viewMode, setViewMode] = useState('clusters'); // 'clusters' | 'all'
  const [clusteringLoading, setClusteringLoading] = useState(false);
  const [clearingLoading, setClearingLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // Register Modal state with multi-face support & false-positive deletion
  const [modalOpen, setModalOpen] = useState(false);
  const [modalFaces, setModalFaces] = useState([]);
  const [regForm, setRegForm] = useState({
    name: '',
    student_id: '',
    department: 'Computer Science',
    email: ''
  });
  const [regSubmitting, setRegSubmitting] = useState(false);
  const [regFeedback, setRegFeedback] = useState({ type: '', message: '' });
  
  // Batch attendance state
  const [batchFolder, setBatchFolder] = useState('');
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState(null);
  const [batchError, setBatchError] = useState(null);

  // Poll live data every 3 seconds (load clusters on initial mount)
  useEffect(() => {
    loadData(true);
    const interval = setInterval(() => loadData(false), 3000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async (includeClusters = false) => {
    try {
      // 1. Get today's attendance
      const attData = await api.getAttendance();
      if (attData?.records) setAttendanceRecords(attData.records);

      // 2. Get real-time engagement
      const engData = await api.getEngagement();
      if (engData) setRealtimeEngagement(engData);

      // 3. Get unknown faces queue
      const unkData = await api.getUnknownFaces(includeClusters);
      if (unkData?.unknown_faces) setUnknownFaces(unkData.unknown_faces);
      if (includeClusters && unkData?.clusters) {
        setFaceClusters(unkData.clusters);
      }
    } catch (e) {
      console.warn('Dashboard poll error:', e);
    }
  };

  const handleClusterify = async () => {
    setClusteringLoading(true);
    try {
      const res = await api.clusterifyUnknownFaces();
      if (res?.clusters) {
        setFaceClusters(res.clusters);
        setViewMode('clusters');
      }
      const unkData = await api.getUnknownFaces();
      if (unkData?.unknown_faces) setUnknownFaces(unkData.unknown_faces);
    } catch (err) {
      alert(`Clusterify failed: ${err.message}`);
    } finally {
      setClusteringLoading(false);
    }
  };

  const handleClearQueue = async () => {
    if (!window.confirm('Are you sure you want to clear all unknown faces from the review queue? This cannot be undone.')) {
      return;
    }
    setClearingLoading(true);
    try {
      await api.clearUnknownFaces();
      setUnknownFaces([]);
      setFaceClusters([]);
      if (onRefresh) onRefresh();
    } catch (err) {
      alert(`Clear queue failed: ${err.message}`);
    } finally {
      setClearingLoading(false);
    }
  };

  const handleOpenRegisterModal = (faces) => {
    if (!faces || faces.length === 0) return;
    setModalFaces([...faces]);
    setRegForm({
      name: '',
      student_id: '',
      department: 'Computer Science',
      email: ''
    });
    setRegFeedback({ type: '', message: '' });
    setModalOpen(true);
  };

  const handleRegisterFaceClick = (face) => {
    // If clustered, find the person's cluster so all their faces are shown in the modal
    if (faceClusters && faceClusters.length > 0) {
      const parentCluster = faceClusters.find(c => 
        c.faces?.some(f => f.filename === face.filename)
      );
      if (parentCluster && parentCluster.faces?.length > 0) {
        handleOpenRegisterModal(parentCluster.faces);
        return;
      }
    }
    // Otherwise single image
    handleOpenRegisterModal([face]);
  };

  const handleRemoveFaceFromBatch = (filename) => {
    setModalFaces(prev => prev.filter(f => f.filename !== filename));
  };

  const handleSubmitRegister = async (e) => {
    e.preventDefault();
    if (!regForm.name.trim()) {
      setRegFeedback({ type: 'error', message: 'Student name is required.' });
      return;
    }
    if (modalFaces.length === 0) {
      setRegFeedback({ type: 'error', message: 'At least one face crop is required.' });
      return;
    }

    setRegSubmitting(true);
    setRegFeedback({ type: '', message: '' });

    try {
      const payload = {
        filenames: modalFaces.map(f => f.filename),
        name: regForm.name.trim(),
        student_id: regForm.student_id.trim() || `STU_${regForm.name.trim().toUpperCase().replace(/\s+/g, '_')}`,
        department: regForm.department.trim(),
        email: regForm.email.trim()
      };

      const res = await api.registerUnknownCluster(payload);
      setRegFeedback({
        type: 'success',
        message: res.message || `Successfully registered ${payload.name} with ${modalFaces.length} photos!`
      });

      // Filter out registered files immediately
      const registeredSet = new Set(payload.filenames);
      setUnknownFaces(prev => prev.filter(f => !registeredSet.has(f.filename)));
      setFaceClusters(prev => 
        prev.map(c => ({
          ...c,
          faces: c.faces.filter(f => !registeredSet.has(f.filename)),
          count: c.faces.filter(f => !registeredSet.has(f.filename)).length
        })).filter(c => c.faces.length > 0)
      );

      setTimeout(() => {
        setModalOpen(false);
        setRegSubmitting(false);
        loadData();
        if (onRefresh) onRefresh();
      }, 1000);

    } catch (err) {
      setRegFeedback({ type: 'error', message: err.message || 'Registration failed.' });
      setRegSubmitting(false);
    }
  };

  const handleIgnoreFace = async (filename) => {
    try {
      await api.ignoreUnknown(filename);
      setUnknownFaces(prev => prev.filter(f => f.filename !== filename));
      setFaceClusters(prev => 
        prev.map(c => ({
          ...c,
          faces: c.faces.filter(f => f.filename !== filename),
          count: c.faces.filter(f => f.filename !== filename).length
        })).filter(c => c.faces.length > 0)
      );
      if (onRefresh) onRefresh();
    } catch (err) {
      alert(`Ignore failed: ${err.message}`);
    }
  };

  const handleIgnoreCluster = async (cluster) => {
    try {
      const filenames = cluster.faces.map(f => f.filename);
      await api.ignoreUnknown(filenames);
      const set = new Set(filenames);
      setUnknownFaces(prev => prev.filter(f => !set.has(f.filename)));
      setFaceClusters(prev => prev.filter(c => c.cluster_id !== cluster.cluster_id));
      if (onRefresh) onRefresh();
    } catch (err) {
      alert(`Dismiss cluster failed: ${err.message}`);
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
              <HelpCircle size={18} color="#f59e0b" />
              Unknown Faces Review Queue
            </h3>
            <p style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginTop: '2px', marginBottom: 0 }}>
              Unrecognized faces captured during live sessions. Deduplicate into clusters or enroll them as students.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {/* View Mode Toggle (Clusters vs All Faces) */}
            {faceClusters.length > 0 && (
              <div style={{
                display: 'flex',
                background: 'rgba(15, 23, 42, 0.8)',
                padding: '3px',
                borderRadius: '8px',
                border: '1px solid var(--border-subtle)'
              }}>
                <button
                  type="button"
                  onClick={() => setViewMode('clusters')}
                  style={{
                    padding: '4px 10px',
                    fontSize: '0.75rem',
                    borderRadius: '6px',
                    border: 'none',
                    background: viewMode === 'clusters' ? 'var(--primary-color)' : 'transparent',
                    color: viewMode === 'clusters' ? '#ffffff' : 'var(--text-dim)',
                    cursor: 'pointer',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}
                >
                  <Users size={12} />
                  <span>Clusters ({faceClusters.length})</span>
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('all')}
                  style={{
                    padding: '4px 10px',
                    fontSize: '0.75rem',
                    borderRadius: '6px',
                    border: 'none',
                    background: viewMode === 'all' ? 'var(--primary-color)' : 'transparent',
                    color: viewMode === 'all' ? '#ffffff' : 'var(--text-dim)',
                    cursor: 'pointer',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}
                >
                  <Image size={12} />
                  <span>All ({unknownFaces.length})</span>
                </button>
              </div>
            )}

            {/* Clusterify Button */}
            <button
              className="btn btn-primary"
              style={{
                fontSize: '0.78rem',
                padding: '6px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                border: 'none',
                boxShadow: '0 4px 12px rgba(99, 102, 241, 0.3)'
              }}
              onClick={handleClusterify}
              disabled={clusteringLoading || unknownFaces.length === 0}
              title="Automatically cluster repeat appearances of the same person using facial embeddings"
            >
              {clusteringLoading ? (
                <>
                  <RefreshCw size={13} className="animate-spin" />
                  <span>Clustering...</span>
                </>
              ) : (
                <>
                  <Sparkles size={13} />
                  <span>Clusterify</span>
                </>
              )}
            </button>

            {/* Clear Queue Button */}
            <button
              className="btn btn-secondary"
              style={{
                fontSize: '0.78rem',
                padding: '6px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                borderColor: 'rgba(239, 68, 68, 0.4)',
                color: '#fca5a5'
              }}
              onClick={handleClearQueue}
              disabled={clearingLoading || unknownFaces.length === 0}
              title="Clear all unknown face captures from the queue"
            >
              {clearingLoading ? (
                <>
                  <RefreshCw size={13} className="animate-spin" />
                  <span>Clearing...</span>
                </>
              ) : (
                <>
                  <Trash2 size={13} />
                  <span>Clear Queue</span>
                </>
              )}
            </button>

            <span className="badge badge-warning" style={{ fontSize: '0.75rem' }}>
              {unknownFaces.length} Pending
            </span>
          </div>
        </div>

        {/* Content Area: Empty State vs Clusters View vs All Faces View */}
        {unknownFaces.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '36px', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
            <HelpCircle size={32} style={{ margin: '0 auto 8px auto', opacity: 0.4, display: 'block' }} />
            No unknown faces pending review.
          </div>
        ) : viewMode === 'clusters' && faceClusters.length > 0 ? (
          /* Clusters View */
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: '16px'
          }}>
            {faceClusters.map((cluster, cIdx) => (
              <div key={cluster.cluster_id || cIdx} style={{
                borderRadius: 'var(--radius-md)',
                background: 'rgba(15, 23, 42, 0.75)',
                border: '1px solid var(--border-subtle)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                transition: 'transform 0.2s ease, border-color 0.2s ease',
                position: 'relative'
              }}>
                {/* Cluster Header Badge */}
                <div style={{
                  padding: '8px 12px',
                  background: 'rgba(30, 41, 59, 0.6)',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-main)' }}>
                    Person #{cIdx + 1}
                  </span>
                  <span style={{
                    fontSize: '0.68rem',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: cluster.count > 1 ? 'rgba(99, 102, 241, 0.25)' : 'rgba(100, 116, 139, 0.25)',
                    color: cluster.count > 1 ? '#a5b4fc' : 'var(--text-dim)',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                  }}>
                    <Users size={10} />
                    {cluster.count} {cluster.count === 1 ? 'crop' : 'crops'}
                  </span>
                </div>

                {/* Main Representative Photo */}
                <div style={{ height: '140px', background: '#090d16', position: 'relative' }}>
                  <img
                    src={getUnknownImageUrl(cluster.representative)}
                    alt="Representative face"
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                  <span style={{
                    position: 'absolute',
                    bottom: '6px',
                    left: '8px',
                    fontSize: '0.68rem',
                    background: 'rgba(0, 0, 0, 0.65)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    color: 'var(--text-dim)',
                    backdropFilter: 'blur(4px)'
                  }}>
                    {cluster.faces?.[0]?.created ? new Date(cluster.faces[0].created).toLocaleTimeString() : 'Recent'}
                  </span>
                </div>

                {/* Sub-strip preview thumbnails if cluster has multiple photos */}
                {cluster.faces && cluster.faces.length > 1 && (
                  <div style={{
                    display: 'flex',
                    gap: '4px',
                    padding: '6px 10px',
                    background: 'rgba(10, 15, 30, 0.5)',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                    overflowX: 'auto',
                    alignItems: 'center'
                  }}>
                    {cluster.faces.slice(1, 5).map((f, i) => (
                      <img
                        key={f.filename || i}
                        src={getUnknownImageUrl(f.filename)}
                        alt="Face thumbnail"
                        style={{
                          width: '30px',
                          height: '30px',
                          borderRadius: '4px',
                          objectFit: 'cover',
                          border: '1px solid rgba(255, 255, 255, 0.1)',
                          flexShrink: 0
                        }}
                      />
                    ))}
                    {cluster.faces.length > 5 && (
                      <span style={{
                        fontSize: '0.65rem',
                        color: 'var(--text-dim)',
                        background: 'rgba(255,255,255,0.06)',
                        padding: '4px 6px',
                        borderRadius: '4px',
                        flexShrink: 0
                      }}>
                        +{cluster.faces.length - 5}
                      </span>
                    )}
                  </div>
                )}

                {/* Action Buttons */}
                <div style={{ padding: '10px 12px', display: 'flex', gap: '8px' }}>
                  <button
                    className="btn btn-primary"
                    style={{ flex: 1, padding: '6px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                    onClick={() => handleOpenRegisterModal(cluster.faces)}
                    title="Review face crops and enroll this student"
                  >
                    <UserPlus size={13} />
                    <span>Register ({cluster.count})</span>
                  </button>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: '6px 10px' }}
                    onClick={() => handleIgnoreCluster(cluster)}
                    title="Dismiss this entire cluster"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* All Individual Faces View */
          <div>
            {faceClusters.length === 0 && unknownFaces.length > 0 && (
              <div style={{
                padding: '12px 16px',
                marginBottom: '16px',
                borderRadius: '8px',
                background: 'rgba(99, 102, 241, 0.1)',
                border: '1px solid rgba(99, 102, 241, 0.25)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '10px'
              }}>
                <div style={{ fontSize: '0.8rem', color: '#c7d2fe' }}>
                  💡 <strong>Tip:</strong> You have {unknownFaces.length} pending face captures. Click <strong>Clusterify</strong> above to automatically group identical people together!
                </div>
                <button
                  className="btn btn-primary"
                  style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                  onClick={handleClusterify}
                  disabled={clusteringLoading}
                >
                  <Sparkles size={12} />
                  <span>Clusterify Now</span>
                </button>
              </div>
            )}

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

                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        className="btn btn-primary"
                        style={{ flex: 1, padding: '6px 8px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                        onClick={() => handleRegisterFaceClick(face)}
                        title="Enroll student using this face crop (or cluster)"
                      >
                        <UserPlus size={13} />
                        <span>Register</span>
                      </button>
                      <button
                        className="btn btn-secondary"
                        style={{ padding: '6px 8px' }}
                        onClick={() => handleIgnoreFace(face.filename)}
                        title="Dismiss"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
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

      {/* Interactive Registration Modal with False-Positive Deletion */}
      {modalOpen && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(5, 8, 22, 0.85)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '20px'
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget && !regSubmitting) {
              setModalOpen(false);
            }
          }}
        >
          <div style={{
            width: '100%',
            maxWidth: '680px',
            maxHeight: '90vh',
            overflowY: 'auto',
            background: 'linear-gradient(135deg, rgba(26, 31, 55, 0.96), rgba(15, 20, 38, 0.98))',
            border: '1px solid rgba(255, 255, 255, 0.15)',
            borderRadius: 'var(--radius-lg, 16px)',
            boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(99, 102, 241, 0.2)',
            padding: '28px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            position: 'relative'
          }}>
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ fontSize: '1.25rem', fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <UserPlus size={20} color="#8b5cf6" />
                  Register Student from Unknown Face(s)
                </h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '4px', marginBottom: 0 }}>
                  Review face crops ({modalFaces.length} selected). Remove any blurry crops or false positives (e.g. hands, background objects) before training embeddings.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: '6px', borderRadius: '50%', width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                onClick={() => setModalOpen(false)}
                disabled={regSubmitting}
              >
                <X size={16} />
              </button>
            </div>

            {/* Face Crops Grid with False-Positive Removal */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <label style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-main)' }}>
                  Selected Face Crops ({modalFaces.length})
                </label>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                  Click <X size={12} style={{ display: 'inline', verticalAlign: 'middle', color: '#ef4444' }} /> on any image to remove false positives
                </span>
              </div>

              {modalFaces.length === 0 ? (
                <div style={{
                  padding: '24px',
                  textAlign: 'center',
                  background: 'rgba(239, 68, 68, 0.1)',
                  borderRadius: '10px',
                  border: '1px dashed #ef4444',
                  color: '#fca5a5',
                  fontSize: '0.85rem'
                }}>
                  All faces have been removed from this batch. Please close this modal or cancel.
                </div>
              ) : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(85px, 1fr))',
                  gap: '10px',
                  maxHeight: '220px',
                  overflowY: 'auto',
                  padding: '10px',
                  background: 'rgba(10, 15, 30, 0.6)',
                  borderRadius: '10px',
                  border: '1px solid rgba(255, 255, 255, 0.08)'
                }}>
                  {modalFaces.map((f, idx) => (
                    <div
                      key={f.filename || idx}
                      style={{
                        position: 'relative',
                        borderRadius: '8px',
                        overflow: 'hidden',
                        border: '1px solid rgba(255, 255, 255, 0.15)',
                        aspectRatio: '1 / 1',
                        background: '#070b14'
                      }}
                    >
                      <img
                        src={getUnknownImageUrl(f.filename)}
                        alt="Crop thumbnail"
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        onError={(e) => { e.target.style.display = 'none'; }}
                      />
                      <button
                        type="button"
                        title="Remove false positive"
                        onClick={() => handleRemoveFaceFromBatch(f.filename)}
                        disabled={regSubmitting}
                        style={{
                          position: 'absolute',
                          top: '4px',
                          right: '4px',
                          width: '22px',
                          height: '22px',
                          borderRadius: '50%',
                          background: 'rgba(239, 68, 68, 0.9)',
                          border: 'none',
                          color: '#ffffff',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          boxShadow: '0 2px 4px rgba(0,0,0,0.6)',
                          transition: 'transform 0.15s ease, background 0.15s ease'
                        }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Registration Form */}
            <form onSubmit={handleSubmitRegister} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '4px', display: 'block' }}>
                    Student Full Name *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="e.g. Saptarshi"
                    value={regForm.name}
                    onChange={(e) => {
                      const val = e.target.value;
                      setRegForm(prev => ({
                        ...prev,
                        name: val,
                        student_id: (!prev.student_id || prev.student_id === `STU_${prev.name.toUpperCase().replace(/\s+/g, '_')}`)
                          ? `STU_${val.toUpperCase().replace(/\s+/g, '_')}`
                          : prev.student_id
                      }));
                    }}
                    required
                    autoFocus
                    disabled={regSubmitting}
                    style={{ width: '100%', padding: '10px 12px' }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '4px', display: 'block' }}>
                    Student ID / Roll Number *
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="e.g. STU_SAPTARSHI or CS2026_01"
                    value={regForm.student_id}
                    onChange={(e) => setRegForm(prev => ({ ...prev, student_id: e.target.value }))}
                    required
                    disabled={regSubmitting}
                    style={{ width: '100%', padding: '10px 12px' }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '4px', display: 'block' }}>
                    Department
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="e.g. Computer Science"
                    value={regForm.department}
                    onChange={(e) => setRegForm(prev => ({ ...prev, department: e.target.value }))}
                    disabled={regSubmitting}
                    style={{ width: '100%', padding: '10px 12px' }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '4px', display: 'block' }}>
                    Email (Optional)
                  </label>
                  <input
                    type="email"
                    className="input-field"
                    placeholder="e.g. student@college.edu"
                    value={regForm.email}
                    onChange={(e) => setRegForm(prev => ({ ...prev, email: e.target.value }))}
                    disabled={regSubmitting}
                    style={{ width: '100%', padding: '10px 12px' }}
                  />
                </div>
              </div>

              {/* Feedback Alert */}
              {regFeedback.message && (
                <div style={{
                  padding: '10px 14px',
                  borderRadius: '8px',
                  fontSize: '0.82rem',
                  background: regFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(34, 197, 94, 0.15)',
                  border: `1px solid ${regFeedback.type === 'error' ? '#ef4444' : '#22c55e'}`,
                  color: regFeedback.type === 'error' ? '#fca5a5' : '#86efac',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  {regFeedback.type === 'error' ? <AlertCircle size={16} /> : <Check size={16} />}
                  <span>{regFeedback.message}</span>
                </div>
              )}

              {/* Action Buttons */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setModalOpen(false)}
                  disabled={regSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={regSubmitting || modalFaces.length === 0 || !regForm.name.trim()}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    minWidth: '180px',
                    justifyContent: 'center',
                    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                    border: 'none',
                    boxShadow: '0 4px 14px rgba(99, 102, 241, 0.35)'
                  }}
                >
                  {regSubmitting ? (
                    <>
                      <RefreshCw size={15} className="animate-spin" />
                      <span>Encoding &amp; Enrolling...</span>
                    </>
                  ) : (
                    <>
                      <UserPlus size={15} />
                      <span>Enroll Student ({modalFaces.length} photos)</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
