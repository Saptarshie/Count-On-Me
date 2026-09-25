import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import DashboardView from './components/DashboardView';
import LiveFeedView from './components/LiveFeedView';
import AttendanceView from './components/AttendanceView';
import StudentsView from './components/StudentsView';
import AnalyticsView from './components/AnalyticsView';
import RegisterView from './components/RegisterView';
import { api, getEventsStreamUrl } from './api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [sysStats, setSysStats] = useState(null);

  const fetchStats = async () => {
    try {
      const data = await api.getStats();
      if (data) {
        setSysStats(prev => ({
          ...prev,
          ...data,
        }));
      }
    } catch (err) {
      // Backend may be starting up
    }
  };

  // Real-time telemetry via Server-Sent Events (SSE)
  useEffect(() => {
    fetchStats();

    let eventSource = null;
    let reconnectTimeout = null;
    let fallbackInterval = null;

    const connectSSE = () => {
      if (typeof EventSource === 'undefined') {
        fallbackInterval = setInterval(fetchStats, 2000);
        return;
      }

      try {
        const streamUrl = getEventsStreamUrl();
        eventSource = new EventSource(streamUrl);

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data) {
              setSysStats(prev => ({
                ...prev,
                ...data,
                present_students: data.present_count ?? prev?.present_students ?? 0,
                present_count: data.present_count ?? prev?.present_count ?? 0,
                total_students: data.total_students ?? prev?.total_students ?? 0,
                absent_count: data.absent_count ?? prev?.absent_count ?? 0,
                attendance_percentage: data.attendance_percentage ?? prev?.attendance_percentage ?? 0,
                average_engagement: data.average_engagement ?? prev?.average_engagement ?? 0,
                tracked_students: data.tracked_students ?? prev?.tracked_students ?? {},
              }));
            }
          } catch (e) {
            console.error('SSE JSON error:', e);
          }
        };

        eventSource.onerror = () => {
          // Close and retry after delay
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          if (!fallbackInterval) {
            fallbackInterval = setInterval(fetchStats, 4000);
          }
          reconnectTimeout = setTimeout(connectSSE, 4000);
        };

        eventSource.onopen = () => {
          if (fallbackInterval) {
            clearInterval(fallbackInterval);
            fallbackInterval = null;
          }
        };
      } catch (err) {
        if (!fallbackInterval) {
          fallbackInterval = setInterval(fetchStats, 3000);
        }
      }
    };

    connectSSE();

    // Background slow sync for deep database queries
    const bgSync = setInterval(fetchStats, 10000);

    return () => {
      if (eventSource) eventSource.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (fallbackInterval) clearInterval(fallbackInterval);
      clearInterval(bgSync);
    };
  }, []);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        sysStats={sysStats}
        onRefresh={fetchStats}
      />

      {/* Main Content Area */}
      <main style={{
        flex: 1,
        maxWidth: '1400px',
        width: '100%',
        margin: '0 auto',
        padding: '24px 20px 80px 20px',
      }}>
        {activeTab === 'dashboard' && (
          <DashboardView
            stats={sysStats}
            setActiveTab={setActiveTab}
            onRefresh={fetchStats}
          />
        )}

        {activeTab === 'live' && (
          <LiveFeedView
            stats={sysStats}
            setActiveTab={setActiveTab}
            onRefresh={fetchStats}
          />
        )}

        {activeTab === 'attendance' && (
          <AttendanceView onSessionChange={fetchStats} />
        )}

        {activeTab === 'students' && (
          <StudentsView
            setActiveTab={setActiveTab}
          />
        )}

        {activeTab === 'analytics' && (
          <AnalyticsView
            stats={sysStats}
          />
        )}

        {activeTab === 'register' && (
          <RegisterView
            onStudentRegistered={() => {
              fetchStats();
              setActiveTab('students');
            }}
          />
        )}
      </main>
    </div>
  );
}
