import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  PieChart, 
  TrendingUp, 
  CheckCircle, 
  AlertTriangle, 
  Award, 
  Zap, 
  Smile, 
  Frown,
  Activity
} from 'lucide-react';
import { api } from '../api';

export default function AnalyticsView({ stats }) {
  const [attendanceRecords, setAttendanceRecords] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAnalytics();
  }, []);

  const loadAnalytics = async () => {
    try {
      const data = await api.getAttendance();
      setAttendanceRecords(data?.records || []);
    } catch (e) {
      console.warn('Analytics load error:', e);
    } finally {
      setLoading(false);
    }
  };

  const presentCount = stats?.present_count ?? attendanceRecords.length;
  const totalStudents = stats?.total_students ?? Math.max(presentCount, 1);
  const absentCount = Math.max(0, totalStudents - presentCount);
  const attendancePct = stats?.attendance_percentage ?? ((presentCount / totalStudents) * 100);
  const avgEngagement = stats?.average_engagement ?? 0;

  // Breakdown of attendance records by engagement tier
  const attentiveStudents = attendanceRecords.filter(r => (r.engagement_score || 0) >= 70);
  const distractedStudents = attendanceRecords.filter(r => (r.engagement_score || 0) >= 40 && (r.engagement_score || 0) < 70);
  const drowsyStudents = attendanceRecords.filter(r => (r.engagement_score || 0) < 40);

  // Top engaged students
  const rankedStudents = [...attendanceRecords].sort((a, b) => (b.engagement_score || 0) - (a.engagement_score || 0));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Top Banner */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            background: 'linear-gradient(135deg, #8b5cf6, #ec4899)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#ffffff'
          }}>
            <BarChart3 size={24} />
          </div>
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800 }}>Analytics &amp; Engagement Intelligence</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Comprehensive performance breakdown across student attendance, attention spans, and classroom focus.
            </p>
          </div>
        </div>
      </div>

      {/* High-level KPI Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '16px'
      }}>
        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Class Attendance Rate</span>
            <PieChart size={18} color="#38bdf8" />
          </div>
          <h2 style={{ fontSize: '2rem', fontWeight: 800, color: '#38bdf8', marginTop: '6px' }}>
            {attendancePct.toFixed(1)}%
          </h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
            {presentCount} present / {absentCount} absent
          </span>
        </div>

        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Average Attention</span>
            <Activity size={18} color="#a78bfa" />
          </div>
          <h2 style={{ fontSize: '2rem', fontWeight: 800, color: '#a78bfa', marginTop: '6px' }}>
            {avgEngagement.toFixed(1)}%
          </h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
            Based on facial landmarks &amp; EAR
          </span>
        </div>

        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Attentive Students</span>
            <Smile size={18} color="#34d399" />
          </div>
          <h2 style={{ fontSize: '2rem', fontWeight: 800, color: '#34d399', marginTop: '6px' }}>
            {attentiveStudents.length}
          </h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
            Score &ge; 70% threshold
          </span>
        </div>

        <div className="glass-panel" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Needs Attention / Drowsy</span>
            <AlertTriangle size={18} color="#f87171" />
          </div>
          <h2 style={{ fontSize: '2rem', fontWeight: 800, color: '#f87171', marginTop: '6px' }}>
            {drowsyStudents.length}
          </h2>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
            Eye closure / head dropped
          </span>
        </div>
      </div>

      {/* Visual Analytics Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: '20px'
      }}>
        
        {/* Engagement Distribution Progress Bars */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <TrendingUp size={18} color="#818cf8" />
            Classroom Engagement Tiers
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Highly Attentive */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#34d399', fontWeight: 600 }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
                  Highly Attentive (&ge; 70%)
                </span>
                <span style={{ fontWeight: 700 }}>
                  {attentiveStudents.length} ({attendanceRecords.length ? Math.round((attentiveStudents.length / attendanceRecords.length) * 100) : 0}%)
                </span>
              </div>
              <div style={{ height: '10px', background: 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden' }}>
                <div style={{
                  width: `${attendanceRecords.length ? (attentiveStudents.length / attendanceRecords.length) * 100 : 0}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #10b981, #059669)',
                  borderRadius: '999px'
                }} />
              </div>
            </div>

            {/* Moderately Distracted */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#fbbf24', fontWeight: 600 }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#f59e0b' }} />
                  Moderately Distracted (40% - 69%)
                </span>
                <span style={{ fontWeight: 700 }}>
                  {distractedStudents.length} ({attendanceRecords.length ? Math.round((distractedStudents.length / attendanceRecords.length) * 100) : 0}%)
                </span>
              </div>
              <div style={{ height: '10px', background: 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden' }}>
                <div style={{
                  width: `${attendanceRecords.length ? (distractedStudents.length / attendanceRecords.length) * 100 : 0}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #f59e0b, #d97706)',
                  borderRadius: '999px'
                }} />
              </div>
            </div>

            {/* Drowsy / Disengaged */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '6px' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontWeight: 600 }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ef4444' }} />
                  Low Focus / Drowsy (&lt; 40%)
                </span>
                <span style={{ fontWeight: 700 }}>
                  {drowsyStudents.length} ({attendanceRecords.length ? Math.round((drowsyStudents.length / attendanceRecords.length) * 100) : 0}%)
                </span>
              </div>
              <div style={{ height: '10px', background: 'rgba(255,255,255,0.06)', borderRadius: '999px', overflow: 'hidden' }}>
                <div style={{
                  width: `${attendanceRecords.length ? (drowsyStudents.length / attendanceRecords.length) * 100 : 0}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #ef4444, #dc2626)',
                  borderRadius: '999px'
                }} />
              </div>
            </div>
          </div>

          <div style={{
            padding: '14px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(99, 102, 241, 0.08)',
            border: '1px solid rgba(99, 102, 241, 0.2)',
            fontSize: '0.8rem',
            color: 'var(--text-muted)',
            lineHeight: 1.5
          }}>
            <strong style={{ color: '#818cf8', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
              <Zap size={14} /> Focus Insight
            </strong>
            {avgEngagement >= 70 
              ? 'Excellent engagement! Students are actively looking at the instructor with optimal blink rates.' 
              : avgEngagement >= 50
              ? 'Average classroom focus. Consider introducing an interactive activity or Q&A segment.'
              : 'Noticeable drop in student attention detected. Review drowsiness alerts in the live stream.'}
          </div>
        </div>

        {/* Student Focus Leaderboard */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <Award size={18} color="#fbbf24" />
            Student Focus Leaderboard
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', maxHeight: '340px' }}>
            {rankedStudents.length > 0 ? (
              rankedStudents.map((st, idx) => {
                const score = Math.round(st.engagement_score || 0);
                const scoreColor = score >= 70 ? '#34d399' : score >= 40 ? '#fbbf24' : '#f87171';
                return (
                  <div key={idx} style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid var(--border-subtle)'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{
                        width: '24px',
                        height: '24px',
                        borderRadius: '50%',
                        background: idx === 0 ? 'rgba(251, 191, 36, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                        color: idx === 0 ? '#fbbf24' : 'var(--text-dim)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '0.75rem',
                        fontWeight: 700
                      }}>
                        {idx + 1}
                      </span>
                      <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{st.name}</span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontWeight: 800, fontSize: '0.95rem', color: scoreColor }}>
                        {score}%
                      </span>
                      <span className={`badge ${score >= 70 ? 'badge-success' : score >= 40 ? 'badge-warning' : 'badge-danger'}`} style={{ fontSize: '0.7rem' }}>
                        {score >= 70 ? 'Attentive' : score >= 40 ? 'Fair' : 'Low'}
                      </span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{ textAlign: 'center', padding: '36px 0', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
                No student engagement records to rank yet.
              </div>
            )}
          </div>
        </div>

      </div>

    </div>
  );
}
