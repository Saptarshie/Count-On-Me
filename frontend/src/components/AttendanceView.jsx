import React, { useState, useEffect } from 'react';
import { 
  Calendar, 
  Download, 
  Search, 
  UserCheck, 
  Activity, 
  Clock, 
  CalendarDays,
  FileSpreadsheet
} from 'lucide-react';
import { api, getExportCsvUrl } from '../api';

export default function AttendanceView() {
  const [selectedDate, setSelectedDate] = useState(() => {
    return new Date().toISOString().split('T')[0];
  });
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchRecords(selectedDate);
  }, [selectedDate]);

  const fetchRecords = async (dateStr) => {
    setLoading(true);
    try {
      const data = await api.getAttendance(dateStr);
      setRecords(data?.records || []);
    } catch (err) {
      console.error('Error fetching attendance:', err);
    } finally {
      setLoading(false);
    }
  };

  const filteredRecords = records.filter(r => 
    r.name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const avgEngagement = records.length > 0 
    ? (records.reduce((acc, r) => acc + (r.engagement_score || 0), 0) / records.length).toFixed(1)
    : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* Top Header */}
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
            Attendance History &amp; Records
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Filter classroom sessions by date, view individual engagement, and export CSV reports.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Date Selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Calendar size={18} color="var(--text-dim)" />
            <input
              type="date"
              className="input-field"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{ width: 'auto', padding: '8px 12px', fontSize: '0.85rem' }}
            />
          </div>

          {/* Export CSV Button */}
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

      {/* Date Metrics Bar */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '16px'
      }}>
        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: 'rgba(16, 185, 129, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#34d399'
          }}>
            <UserCheck size={20} />
          </div>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Students Present</span>
            <h3 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#34d399' }}>{records.length}</h3>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: 'rgba(139, 92, 246, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#a78bfa'
          }}>
            <Activity size={20} />
          </div>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Session Avg Engagement</span>
            <h3 style={{ fontSize: '1.5rem', fontWeight: 800, color: '#a78bfa' }}>{avgEngagement}%</h3>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: 'rgba(6, 182, 212, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#38bdf8'
          }}>
            <Clock size={20} />
          </div>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Filtered Date</span>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f8fafc' }}>{selectedDate}</h3>
          </div>
        </div>
      </div>

      {/* Attendance Table Panel */}
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700 }}>
            Session Roster ({filteredRecords.length})
          </h2>

          <div style={{ position: 'relative', minWidth: '220px' }}>
            <Search size={14} color="var(--text-dim)" style={{ position: 'absolute', left: '10px', top: '12px' }} />
            <input
              type="text"
              className="input-field"
              placeholder="Search name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ paddingLeft: '32px' }}
            />
          </div>
        </div>

        {/* Table */}
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', textAlign: 'left' }}>
                <th style={{ padding: '12px 10px', width: '40px' }}>#</th>
                <th style={{ padding: '12px 10px' }}>Student Name</th>
                <th style={{ padding: '12px 10px' }}>Time</th>
                <th style={{ padding: '12px 10px' }}>Engagement Score</th>
                <th style={{ padding: '12px 10px' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecords.length > 0 ? (
                filteredRecords.map((rec, i) => {
                  const score = rec.engagement_score ?? 0;
                  const scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
                  return (
                    <tr key={rec.id || i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      <td style={{ padding: '12px 10px', color: 'var(--text-dim)' }}>{i + 1}</td>
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
                            {rec.name?.[0]?.toUpperCase() || 'S'}
                          </div>
                          <span style={{ fontWeight: 600 }}>{rec.name}</span>
                        </div>
                      </td>
                      <td style={{ padding: '12px 10px', color: 'var(--text-muted)' }}>
                        {rec.time}
                      </td>
                      <td style={{ padding: '12px 10px', minWidth: '160px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            flex: 1,
                            height: '8px',
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
                        </div>
                      </td>
                      <td style={{ padding: '12px 10px' }}>
                        <span className="badge badge-success">
                          {rec.status || 'Present'}
                        </span>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-dim)' }}>
                    {loading ? 'Loading attendance...' : `No records found for ${selectedDate}.`}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
