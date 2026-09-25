import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import DashboardView from './components/DashboardView';
import LiveFeedView from './components/LiveFeedView';
import AttendanceView from './components/AttendanceView';
import StudentsView from './components/StudentsView';
import AnalyticsView from './components/AnalyticsView';
import RegisterView from './components/RegisterView';
import { api } from './api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [sysStats, setSysStats] = useState(null);

  // Poll system stats every 2.5 seconds
  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 2500);
    return () => clearInterval(interval);
  }, []);

  const fetchStats = async () => {
    try {
      const data = await api.getStats();
      if (data) {
        setSysStats(data);
      }
    } catch (err) {
      // Backend may be offline or starting up
    }
  };

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
            onRefresh={fetchStats}
          />
        )}

        {activeTab === 'attendance' && (
          <AttendanceView />
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
