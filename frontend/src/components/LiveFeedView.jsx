import React, { useState, useEffect, useRef } from 'react';
import { 
  Video, 
  VideoOff, 
  Play, 
  Square, 
  Maximize2, 
  RefreshCw, 
  Eye, 
  Activity, 
  CheckCircle2, 
  AlertTriangle,
  Sliders,
  Sparkles,
  BookOpen,
  ChevronRight
} from 'lucide-react';
import { api, getVideoFeedUrl } from '../api';

export default function LiveFeedView({ stats, setActiveTab, onRefresh }) {
  const [streamError, setStreamError] = useState(false);
  const [streamKey, setStreamKey] = useState(Date.now());
  const [loading, setLoading] = useState(false);
  const [trackedStudents, setTrackedStudents] = useState({});
  const [activityLog, setActivityLog] = useState([]);
  
  // Local toggles
  const [detectionConf, setDetectionConf] = useState(50);
  const [recognitionThresh, setRecognitionThresh] = useState(60);
  const [autoAttendance, setAutoAttendance] = useState(true);

  const videoContainerRef = useRef(null);

  // Automatically refresh stream key whenever stream becomes active or toggled
  useEffect(() => {
    if (stats?.is_running) {
      setStreamError(false);
      setStreamKey(Date.now());
    }
  }, [stats?.is_running]);

  // Real-time tracking from SSE stream passed via stats props
  useEffect(() => {
    if (stats?.tracked_students && typeof stats.tracked_students === 'object') {
      setTrackedStudents(stats.tracked_students);

      Object.entries(stats.tracked_students).forEach(([name, data]) => {
        setActivityLog((prev) => {
          const lastLogged = prev.find(p => p.studentName === name);
          const now = Date.now();
          if (!lastLogged || (now - lastLogged.timeMs > 10000)) {
            const timeStr = new Date().toLocaleTimeString();
            const curScore = Math.round(data.score ?? data.engagement_score ?? 85);
            return [
              {
                id: now + Math.random(),
                studentName: name,
                timeMs: now,
                time: timeStr,
                type: 'detect',
                text: `${name} in view (Engagement: ${curScore}%)`
              },
              ...prev.slice(0, 19)
            ];
          }
          return prev;
        });
      });
    }
  }, [stats?.tracked_students]);

  // Fallback slow poll if SSE is not active
  useEffect(() => {
    const interval = setInterval(async () => {
      if (!stats?.tracked_students || Object.keys(stats.tracked_students).length === 0) {
        try {
          const engData = await api.getEngagement();
          if (engData && Object.keys(engData).length > 0) {
            setTrackedStudents(engData);
          }
        } catch (e) {
          // silent fallback
        }
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [stats?.tracked_students]);

  const handleImageError = () => {
    // If the system is running, the devtunnel/network dropped a packet
    // Auto-retry reconnecting the stream after a brief pause
    if (stats?.is_running) {
      setTimeout(() => {
        setStreamKey(Date.now());
        setStreamError(false);
      }, 1200);
    } else {
      setStreamError(true);
    }
  };

  const handleStart = async () => {
    setLoading(true);
    try {
      await api.startSystem();
      setStreamError(false);
      setStreamKey(Date.now());
      if (onRefresh) onRefresh();
    } catch (e) {
      alert(`Could not start camera: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await api.stopSystem();
      if (onRefresh) onRefresh();
    } catch (e) {
      alert(`Could not stop camera: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const reloadStream = () => {
    setStreamError(false);
    setStreamKey(Date.now());
  };

  const toggleFullscreen = () => {
    if (!videoContainerRef.current) return;
    if (!document.fullscreenElement) {
      videoContainerRef.current.requestFullscreen().catch(err => alert(err.message));
    } else {
      document.exitFullscreen();
    }
  };

  const feedUrl = `${getVideoFeedUrl()}?t=${streamKey}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* Top Controls Header */}
      <div className="glass-panel" style={{
        padding: '16px 20px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: stats?.is_running ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: stats?.is_running ? '#34d399' : '#f87171'
          }}>
            {stats?.is_running ? <Video size={22} /> : <VideoOff size={22} />}
          </div>
          <div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Live Video Stream</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.78rem', color: 'var(--text-dim)' }}>
              {stats?.is_running ? (
                <>
                  <span className="pulse-indicator" />
                  <span style={{ color: '#34d399', fontWeight: 600 }}>Streaming Active</span>
                  <span>•</span>
                  <span>FPS: {Math.round(stats?.fps || 0)}</span>
                </>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>Camera stream is offline</span>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          {stats?.is_running ? (
            <button
              className="btn btn-danger"
              onClick={handleStop}
              disabled={loading}
            >
              <Square size={16} fill="currentColor" />
              <span>Stop Stream</span>
            </button>
          ) : (
            <button
              className="btn btn-success"
              onClick={handleStart}
              disabled={loading}
            >
              <Play size={16} fill="currentColor" />
              <span>Start Stream</span>
            </button>
          )}

          <button
            className="btn btn-secondary"
            onClick={reloadStream}
            title="Reload Video Stream"
          >
            <RefreshCw size={16} />
          </button>

          <button
            className="btn btn-secondary"
            onClick={toggleFullscreen}
            title="Toggle Fullscreen"
          >
            <Maximize2 size={16} />
          </button>
        </div>
      </div>

      {/* Active Classroom Session Notification Bar */}
      <div className="glass-panel" style={{
        padding: '12px 18px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '10px',
        background: 'rgba(99, 102, 241, 0.08)',
        border: '1px solid rgba(99, 102, 241, 0.25)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'rgba(99, 102, 241, 0.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#818cf8'
          }}>
            <BookOpen size={16} />
          </div>
          <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.05em' }}>
              Target Session for Live Attendance:
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '2px' }}>
              <span style={{ fontWeight: 800, color: '#f8fafc', fontSize: '0.95rem' }}>
                {stats?.active_session ? `${stats.active_session.course} - ${stats.active_session.title}` : 'Default Session'}
              </span>
              {stats?.active_session?.room && (
                <span className="badge" style={{ background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)', fontSize: '0.7rem' }}>
                  {stats.active_session.room}
                </span>
              )}
            </div>
          </div>
        </div>

        {setActiveTab && (
          <button
            onClick={() => setActiveTab('attendance')}
            className="btn btn-secondary"
            style={{ fontSize: '0.8rem', padding: '6px 12px' }}
          >
            <span>Change Session / View Roster</span>
            <ChevronRight size={14} />
          </button>
        )}
      </div>

      {/* Main Grid: Stream on Left, Live Tracking on Right */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: '20px',
        alignItems: 'start'
      }}>
        
        {/* Camera Player Card */}
        <div 
          ref={videoContainerRef}
          className="glass-panel" 
          style={{
            overflow: 'hidden',
            borderRadius: 'var(--radius-lg)',
            background: '#040711',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            position: 'relative',
            minHeight: '380px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
        >
          {stats?.is_running && !streamError ? (
            <img
              key={streamKey}
              src={feedUrl}
              alt="Live Camera Feed"
              onError={handleImageError}
              style={{
                width: '100%',
                height: 'auto',
                display: 'block',
                maxHeight: '640px',
                objectFit: 'contain'
              }}
            />
          ) : (
            <div style={{
              textAlign: 'center',
              padding: '40px 20px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16px'
            }}>
              <div style={{
                width: '64px',
                height: '64px',
                borderRadius: '50%',
                background: 'rgba(255, 255, 255, 0.05)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-dim)'
              }}>
                <VideoOff size={32} />
              </div>
              <div>
                <h3 style={{ fontSize: '1.2rem', marginBottom: '4px' }}>Camera Offline</h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '320px' }}>
                  {streamError 
                    ? 'Video connection lost. Click Start Stream or reload.'
                    : 'The camera is currently stopped. Click below to launch detection.'}
                </p>
              </div>
              <button className="btn btn-primary" onClick={handleStart} disabled={loading}>
                <Play size={16} fill="currentColor" />
                <span>Start Camera</span>
              </button>
            </div>
          )}

          {/* Video Overlay Indicators */}
          {stats?.is_running && !streamError && (
            <div style={{
              position: 'absolute',
              top: '14px',
              left: '14px',
              background: 'rgba(9, 13, 22, 0.75)',
              backdropFilter: 'blur(8px)',
              padding: '6px 12px',
              borderRadius: '999px',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '0.75rem',
              fontWeight: 600
            }}>
              <span className="pulse-indicator" />
              <span>LIVE AI INFERENCE</span>
            </div>
          )}
        </div>

        {/* Live Detected Students & Realtime Engagement */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Active Faces Panel */}
          <div className="glass-panel" style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Eye size={18} color="#818cf8" />
                Live Detected Faces
              </h3>
              <span className="badge badge-neutral">
                {Object.keys(trackedStudents).length} in view
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '280px', overflowY: 'auto' }}>
              {Object.keys(trackedStudents).length > 0 ? (
                Object.entries(trackedStudents).map(([name, data]) => {
                  const score = Math.round(data.score ?? data.engagement_score ?? 0);
                  const isSleeping = Boolean(data.is_sleeping || data.status === 'Sleeping' || data.status === 'Drowsy');
                  const isAttentive = Boolean(data.is_attentive || data.status === 'Attentive' || score >= 60);
                  const badgeClass = isSleeping ? 'badge-danger' : isAttentive ? 'badge-success' : 'badge-warning';
                  const label = isSleeping ? 'Drowsy' : isAttentive ? 'Attentive' : 'Distracted';
                  const earVal = Number(data.ear ?? data.average_ear ?? data.eye_metrics?.average_ear ?? 0.28).toFixed(2);
                  const eyesClosed = Boolean(data.is_blinking ?? data.eye_metrics?.is_blinking);
                  const blinks = Math.round(data.blink_rate ?? 0);

                  return (
                    <div key={name} style={{
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-md)',
                      background: 'rgba(15, 23, 42, 0.65)',
                      border: '1px solid var(--border-subtle)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>{name}</span>
                        <span className={`badge ${badgeClass}`}>{label} ({score}%)</span>
                      </div>
                      <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                        <span>Blink: <strong style={{ color: 'var(--text-main)' }}>{blinks}/m</strong></span>
                        <span>EAR: <strong style={{ color: 'var(--text-main)' }}>{earVal}</strong></span>
                        <span>Eyes: <strong style={{ color: eyesClosed ? '#fbbf24' : '#34d399' }}>
                          {eyesClosed ? 'Closed' : 'Open'}
                        </strong></span>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div style={{ textAlign: 'center', padding: '24px', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
                  No student faces detected currently.
                </div>
              )}
            </div>
          </div>

          {/* Activity Event Log */}
          <div className="glass-panel" style={{ padding: '20px' }}>
            <h3 style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
              <Activity size={18} color="#06b6d4" />
              Live Activity Feed
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto' }}>
              {activityLog.length > 0 ? (
                activityLog.map((act) => (
                  <div key={act.id} style={{
                    padding: '8px 12px',
                    borderRadius: '8px',
                    background: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    fontSize: '0.8rem'
                  }}>
                    <CheckCircle2 size={14} color="#34d399" />
                    <span style={{ color: 'var(--text-dim)', fontSize: '0.72rem' }}>{act.time}</span>
                    <span style={{ color: 'var(--text-main)' }}>{act.text}</span>
                  </div>
                ))
              ) : (
                <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-dim)', fontSize: '0.8rem' }}>
                  Awaiting activity events...
                </div>
              )}
            </div>
          </div>

        </div>
      </div>

      {/* Stream & Detection Settings Card */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <Sliders size={18} color="#8b5cf6" />
          Detection &amp; Recognition Tuning
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px' }}>
              Detection Confidence: {detectionConf}%
            </label>
            <input
              type="range"
              min="10"
              max="95"
              value={detectionConf}
              onChange={(e) => setDetectionConf(Number(e.target.value))}
              style={{ width: '100%', accentColor: 'var(--primary)' }}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>
              Confidence threshold for MediaPipe face detection
            </span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px' }}>
              Recognition Distance Threshold: {recognitionThresh}%
            </label>
            <input
              type="range"
              min="30"
              max="90"
              value={recognitionThresh}
              onChange={(e) => setRecognitionThresh(Number(e.target.value))}
              style={{ width: '100%', accentColor: 'var(--primary)' }}
            />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>
              Stricter match distance prevents false student identity matches
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <input
              type="checkbox"
              id="auto-mark"
              checked={autoAttendance}
              onChange={(e) => setAutoAttendance(e.target.checked)}
              style={{ width: '18px', height: '18px', accentColor: 'var(--primary)' }}
            />
            <label htmlFor="auto-mark" style={{ fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer' }}>
              Auto Mark Attendance in Database
              <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-dim)', fontWeight: 400 }}>
                Prevents duplicate marks via 30min cooldown
              </span>
            </label>
          </div>
        </div>
      </div>

    </div>
  );
}
