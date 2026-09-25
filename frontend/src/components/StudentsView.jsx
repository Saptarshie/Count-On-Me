import React, { useState, useEffect } from 'react';
import { 
  Users, 
  UserPlus, 
  Search, 
  Trash2, 
  Cpu, 
  Mail, 
  GraduationCap, 
  Check, 
  X, 
  AlertCircle,
  Plus
} from 'lucide-react';
import { api } from '../api';

export default function StudentsView({ setActiveTab }) {
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [deptFilter, setDeptFilter] = useState('ALL');
  const [showAddModal, setShowAddModal] = useState(false);
  
  // Quick Add Modal Form
  const [newName, setNewName] = useState('');
  const [newId, setNewId] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newDept, setNewDept] = useState('Computer Science');
  const [addLoading, setAddLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  useEffect(() => {
    fetchStudents();
  }, []);

  const fetchStudents = async () => {
    setLoading(true);
    try {
      const data = await api.getStudents();
      setStudents(data?.students || []);
    } catch (err) {
      console.error('Failed to fetch students:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (studentId, studentName) => {
    if (!window.confirm(`Are you sure you want to delete student "${studentName}"?`)) return;
    try {
      await api.deleteStudent(studentId);
      fetchStudents();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleQuickAdd = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setAddLoading(true);
    setErrorMsg(null);

    try {
      await api.addStudent({
        name: newName.trim(),
        student_id: newId.trim() || newName.trim().toLowerCase().replace(/\s+/g, '_'),
        email: newEmail.trim() || undefined,
        department: newDept || undefined
      });
      setShowAddModal(false);
      setNewName('');
      setNewId('');
      setNewEmail('');
      fetchStudents();
    } catch (err) {
      setErrorMsg(err.message || 'Failed to add student');
    } finally {
      setAddLoading(false);
    }
  };

  const departments = ['ALL', ...new Set(students.map(s => s.department).filter(Boolean))];

  const filteredStudents = students.filter(s => {
    const matchesSearch = s.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          s.student_id?.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesDept = deptFilter === 'ALL' || s.department === deptFilter;
    return matchesSearch && matchesDept;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      
      {/* Header */}
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
            <Users size={24} color="#818cf8" />
            Enrolled Students ({students.length})
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Manage registered students, student IDs, and face training datasets.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary"
            onClick={() => setShowAddModal(true)}
          >
            <Plus size={16} />
            <span>Quick Add Record</span>
          </button>

          <button
            className="btn btn-primary"
            onClick={() => setActiveTab('register')}
          >
            <UserPlus size={16} />
            <span>Register with Face Capture</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="glass-panel" style={{
        padding: '16px 20px',
        display: 'flex',
        flexWrap: 'wrap',
        gap: '14px',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ position: 'relative', flex: 1, minWidth: '240px' }}>
          <Search size={15} color="var(--text-dim)" style={{ position: 'absolute', left: '12px', top: '12px' }} />
          <input
            type="text"
            className="input-field"
            placeholder="Search by student name or ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ paddingLeft: '34px' }}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>Dept:</span>
          <select
            className="input-field"
            value={deptFilter}
            onChange={(e) => setDeptFilter(e.target.value)}
            style={{ width: 'auto', padding: '8px 12px', fontSize: '0.85rem' }}
          >
            {departments.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Student Cards Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: '16px'
      }}>
        {filteredStudents.length > 0 ? (
          filteredStudents.map((st) => (
            <div key={st.student_id || st.id} className="glass-panel" style={{
              padding: '20px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '16px',
              transition: 'all 0.2s ease'
            }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <div style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '14px',
                    background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(6, 182, 212, 0.2))',
                    border: '1px solid rgba(99, 102, 241, 0.3)',
                    color: '#818cf8',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '1.2rem',
                    fontWeight: 800
                  }}>
                    {st.name?.[0]?.toUpperCase() || 'S'}
                  </div>

                  <span className="badge badge-success">Active</span>
                </div>

                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '4px' }}>
                  {st.name}
                </h3>
                
                <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', marginBottom: '8px' }}>
                  ID: <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>{st.student_id}</span>
                </div>

                {st.department && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    <GraduationCap size={14} color="#06b6d4" />
                    <span>{st.department}</span>
                  </div>
                )}

                {st.email && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    <Mail size={14} color="var(--text-dim)" />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{st.email}</span>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                <button
                  className="btn btn-secondary"
                  onClick={() => handleDelete(st.student_id, st.name)}
                  style={{ padding: '6px 12px', fontSize: '0.75rem', color: '#f87171' }}
                  title="Delete student profile"
                >
                  <Trash2 size={14} />
                  <span>Delete</span>
                </button>
              </div>
            </div>
          ))
        ) : (
          <div style={{
            gridColumn: '1 / -1',
            textAlign: 'center',
            padding: '60px 20px',
            color: 'var(--text-dim)'
          }}>
            <Users size={40} color="var(--text-dim)" style={{ marginBottom: '12px' }} />
            <h3 style={{ fontSize: '1.1rem', color: 'var(--text-muted)' }}>
              {loading ? 'Loading students...' : 'No students found matching your criteria.'}
            </h3>
            <p style={{ fontSize: '0.85rem', marginTop: '4px' }}>
              Register a student with face capture to get started.
            </p>
          </div>
        )}
      </div>

      {/* Quick Add Modal */}
      {showAddModal && (
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
            maxWidth: '440px',
            width: '100%',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <UserPlus size={18} color="#818cf8" />
                Quick Add Student
              </h3>
              <button 
                onClick={() => setShowAddModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            {errorMsg && (
              <div style={{ padding: '10px 12px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', fontSize: '0.8rem', marginBottom: '12px' }}>
                {errorMsg}
              </div>
            )}

            <form onSubmit={handleQuickAdd} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Full Name *
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Priya Patel"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Student ID
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. CS2026_09"
                  value={newId}
                  onChange={(e) => setNewId(e.target.value)}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Department
                </label>
                <select
                  className="input-field"
                  value={newDept}
                  onChange={(e) => setNewDept(e.target.value)}
                >
                  <option value="Computer Science">Computer Science</option>
                  <option value="Electronics">Electronics</option>
                  <option value="Mechanical">Mechanical</option>
                  <option value="Civil">Civil</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Email
                </label>
                <input
                  type="email"
                  className="input-field"
                  placeholder="priya@college.edu"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowAddModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={addLoading}
                >
                  {addLoading ? 'Saving...' : 'Save Student'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
