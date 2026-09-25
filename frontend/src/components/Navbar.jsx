import React, { useState } from 'react';
import { 
  LayoutDashboard, 
  Video, 
  CalendarCheck, 
  Users, 
  BarChart3, 
  UserPlus, 
  Play, 
  Square, 
  Cpu, 
  Settings, 
  Check, 
  AlertCircle,
  Menu,
  X,
  Wifi,
  WifiOff
} from 'lucide-react';
import { api, getCustomBackendUrl, setCustomBackendUrl } from '../api';

export default function Navbar({ activeTab, setActiveTab, sysStats, onRefresh }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [customUrl, setCustomUrl] = useState(getCustomBackendUrl());
  const [isEncoding, setIsEncoding] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [toastMsg, setToastMsg] = useState(null);

  const showToast = (msg, isError = false) => {
    setToastMsg({ text: msg, isError });
    setTimeout(() => setToastMsg(null), 4000);
  };

  const handleStart = async () => {
    try {
      setActionLoading(true);
      await api.startSystem();
      showToast('Camera and tracking started!');
      if (onRefresh) onRefresh();
    } catch (err) {
      showToast(`Failed to start: ${err.message}`, true);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionLoading(true);
      await api.stopSystem();
      showToast('System stopped.');
      if (onRefresh) onRefresh();
    } catch (err) {
      showToast(`Failed to stop: ${err.message}`, true);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReEncode = async () => {
    if (!window.confirm('Re-encode all student face images in dataset? This may take a few moments.')) return;
    try {
      setIsEncoding(true);
      const res = await api.encodeDataset();
      showToast(res.message || 'Dataset re-encoded successfully!');
      if (onRefresh) onRefresh();
    } catch (err) {
      showToast(`Encoding failed: ${err.message}`, true);
    } finally {
      setIsEncoding(false);
    }
  };

  const handleSaveSettings = (e) => {
    e.preventDefault();
    setCustomBackendUrl(customUrl);
    setSettingsOpen(false);
    showToast('Backend URL updated! Refreshing data...');
    if (onRefresh) onRefresh();
  };

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'live', label: 'Live Camera', icon: Video },
    { id: 'attendance', label: 'Attendance', icon: CalendarCheck },
    { id: 'students', label: 'Students', icon: Users },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
    { id: 'register', label: 'Register', icon: UserPlus },
  ];

  return (
    <>
      {/* Toast Notification */}
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

      {/* Top Navbar */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        background: 'rgba(9, 13, 22, 0.85)',
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-subtle)',
        padding: '12px 20px',
      }}>
        <div style={{
          maxWidth: '1400px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px'
        }}>
          {/* Logo / Branding */}
          <div 
            onClick={() => setActiveTab('dashboard')}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '12px', 
              cursor: 'pointer',
              userSelect: 'none'
            }}
          >
            <div style={{
              width: '38px',
              height: '38px',
              borderRadius: '10px',
              background: 'linear-gradient(135deg, #6366f1, #06b6d4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 15px rgba(99, 102, 241, 0.4)'
            }}>
              <Video size={20} color="#ffffff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ 
                  fontFamily: 'var(--font-heading)', 
                  fontWeight: 800, 
                  fontSize: '1.25rem',
                  letterSpacing: '-0.02em',
                  background: 'linear-gradient(90deg, #ffffff, #cbd5e1)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent'
                }}>
                  Count-On-Me
                </span>
                <span style={{
                  fontSize: '0.65rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  padding: '2px 6px',
                  borderRadius: '6px',
                  background: 'rgba(99, 102, 241, 0.2)',
                  color: '#818cf8',
                  border: '1px solid rgba(99, 102, 241, 0.3)'
                }}>
                  AI
                </span>
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span>Smart Attendance &amp; Engagement</span>
              </div>
            </div>
          </div>

          {/* Desktop Navigation Links */}
          <nav className="hide-on-mobile" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '8px 14px',
                    borderRadius: 'var(--radius-md)',
                    border: 'none',
                    background: isActive ? 'rgba(99, 102, 241, 0.18)' : 'transparent',
                    color: isActive ? '#818cf8' : 'var(--text-muted)',
                    fontWeight: isActive ? 700 : 500,
                    fontSize: '0.875rem',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.color = '#f8fafc';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.color = 'var(--text-muted)';
                  }}
                >
                  <Icon size={16} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>

          {/* System Control & Status Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {/* System Status Pill */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '6px 12px',
              borderRadius: '9999px',
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border-subtle)',
              fontSize: '0.75rem',
              fontWeight: 600
            }}>
              {sysStats?.is_running ? (
                <>
                  <span className="pulse-indicator" />
                  <span style={{ color: '#34d399' }}>LIVE</span>
                  {sysStats.fps > 0 && (
                    <span style={{ color: 'var(--text-dim)', marginLeft: '2px' }}>
                      ({Math.round(sysStats.fps)} FPS)
                    </span>
                  )}
                </>
              ) : (
                <>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#64748b' }} />
                  <span style={{ color: 'var(--text-dim)' }}>IDLE</span>
                </>
              )}
            </div>

            {/* Quick Start / Stop Toggle */}
            {sysStats?.is_running ? (
              <button
                className="btn btn-danger"
                onClick={handleStop}
                disabled={actionLoading}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                title="Stop Camera Stream"
              >
                <Square size={14} fill="currentColor" />
                <span className="hide-on-mobile">Stop</span>
              </button>
            ) : (
              <button
                className="btn btn-success"
                onClick={handleStart}
                disabled={actionLoading}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                title="Start Camera Stream"
              >
                <Play size={14} fill="currentColor" />
                <span className="hide-on-mobile">Start</span>
              </button>
            )}

            {/* Re-encode Button */}
            <button
              className="btn btn-secondary hide-on-mobile"
              onClick={handleReEncode}
              disabled={isEncoding}
              style={{ padding: '6px 10px', fontSize: '0.8rem' }}
              title="Re-encode face dataset"
            >
              <Cpu size={14} className={isEncoding ? 'animate-spin' : ''} />
              <span>Re-encode</span>
            </button>

            {/* Settings Button */}
            <button
              className="btn btn-secondary"
              onClick={() => setSettingsOpen(true)}
              style={{ padding: '6px 10px', fontSize: '0.8rem' }}
              title="Connection Settings (Port forwarding / Direct URL)"
            >
              <Settings size={15} />
            </button>

            {/* Mobile Hamburger Toggle */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              style={{
                display: 'none',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-main)',
                cursor: 'pointer',
                padding: '6px'
              }}
              className="mobile-hamburger-btn"
            >
              {mobileMenuOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Nav Menu */}
        {mobileMenuOpen && (
          <div style={{
            padding: '16px 0 8px 0',
            borderTop: '1px solid var(--border-subtle)',
            marginTop: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px'
          }}>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id);
                    setMobileMenuOpen(false);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '10px 16px',
                    borderRadius: 'var(--radius-md)',
                    border: 'none',
                    background: isActive ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
                    color: isActive ? '#818cf8' : 'var(--text-main)',
                    fontWeight: 600,
                    fontSize: '0.95rem',
                    textAlign: 'left'
                  }}
                >
                  <Icon size={18} />
                  <span>{item.label}</span>
                </button>
              );
            })}
            <div style={{ marginTop: '8px', padding: '0 8px' }}>
              <button
                className="btn btn-secondary"
                style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => {
                  setMobileMenuOpen(false);
                  handleReEncode();
                }}
                disabled={isEncoding}
              >
                <Cpu size={16} />
                <span>Re-encode Face Dataset</span>
              </button>
            </div>
          </div>
        )}
      </header>

      {/* Settings Modal (Configurable Backend URL for phone port-forwarding) */}
      {settingsOpen && (
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
            maxWidth: '480px',
            width: '100%',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Settings size={20} color="#818cf8" />
                Backend Connection
              </h3>
              <button 
                onClick={() => setSettingsOpen(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px', lineHeight: 1.5 }}>
              By default, this frontend communicates via the local proxy (<code>http://localhost:5000</code>).
              If accessing from a phone via port forwarding or a public tunnel (e.g. ngrok/localtunnel), you can specify your backend URL here.
            </p>

            <form onSubmit={handleSaveSettings}>
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Custom Backend Base URL (leave empty for default proxy)
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={customUrl}
                  onChange={(e) => setCustomUrl(e.target.value)}
                  placeholder="e.g. http://192.168.1.10:5000 or https://your-tunnel.ngrok.app"
                />
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setCustomUrl('');
                    setCustomBackendUrl('');
                    setSettingsOpen(false);
                    showToast('Reset to default proxy');
                    if (onRefresh) onRefresh();
                  }}
                >
                  Reset Default
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Responsive mobile bottom navigation bar */}
      <nav style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: '62px',
        background: 'rgba(9, 13, 22, 0.95)',
        backdropFilter: 'blur(16px)',
        borderTop: '1px solid var(--border-subtle)',
        display: 'none',
        justifyContent: 'space-around',
        alignItems: 'center',
        zIndex: 40,
        padding: '0 8px'
      }} className="mobile-bottom-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '3px',
                background: 'transparent',
                border: 'none',
                color: isActive ? '#818cf8' : 'var(--text-dim)',
                fontSize: '0.65rem',
                fontWeight: isActive ? 700 : 500,
                cursor: 'pointer',
                padding: '6px'
              }}
            >
              <Icon size={20} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <style>{`
        @media (max-width: 768px) {
          .mobile-hamburger-btn {
            display: block !important;
          }
          .mobile-bottom-nav {
            display: flex !important;
          }
          body {
            padding-bottom: 70px;
          }
        }
      `}</style>
    </>
  );
}
