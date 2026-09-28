import React, { useState, useEffect, useRef } from 'react';
import { 
  Users, 
  UserPlus, 
  Search, 
  Trash2, 
  Mail, 
  GraduationCap, 
  X, 
  Plus,
  Camera,
  Save,
  CheckCircle,
  AlertCircle
} from 'lucide-react';
import { api, getStudentPhotoUrl } from '../api';

const DEPARTMENTS = ['Computer Science', 'Data Science & AI', 'Electronics', 'Mechanical', 'Civil', 'Other'];

function StudentAvatar({ studentId, name, size = 48, radius = 14, cacheKey = 0 }) {
  const [failed, setFailed] = useState(false);
  const boxStyle = {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: `${radius}px`,
    overflow: 'hidden',
    border: '1px solid rgba(99, 102, 241, 0.3)',
    background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(6, 182, 212, 0.2))',
    color: '#818cf8',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: `${Math.round(size * 0.38)}px`,
    fontWeight: 800,
    flexShrink: 0
  };
  if (failed) {
    return <div style={boxStyle}>{name?.[0]?.toUpperCase() || 'S'}</div>;
  }
  return (
    <div style={boxStyle}>
      <img
        src={`${getStudentPhotoUrl(studentId, 0)}?v=${cacheKey}`}
        alt={name || 'student'}
        onError={() => setFailed(true)}
        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
      />
    </div>
  );
}

export default function StudentsView({ setActiveTab }) {
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [deptFilter, setDeptFilter] = useState('ALL');
  const [showAddModal, setShowAddModal] = useState(false);
  const [photosRev, setPhotosRev] = useState(0);
  
  // Quick Add Modal Form
  const [newName, setNewName] = useState('');
  const [newId, setNewId] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newDept, setNewDept] = useState('Computer Science');
  const [addLoading, setAddLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // Detail modal (view/edit student + reference photos)
  const [detail, setDetail] = useState(null);
  const detailFileRef = useRef(null);

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
      setPhotosRev(r => r + 1);
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

  // ---------------- detail modal ----------------

  const openDetail = async (st) => {
    setDetail({
      student: st,
      photos: [],
      form: {
        name: st.name || '',
        email: st.email || '',
        department: st.department || 'Computer Science'
      },
      loadingPhotos: true,
      saving: false,
      photoBusy: false,
      msg: null
    });
    try {
      const d = await api.getStudentPhotos(st.student_id);
      setDetail(prev => prev ? { ...prev, photos: d?.photos || [], loadingPhotos: false } : prev);
    } catch (err) {
      setDetail(prev => prev ? { ...prev, loadingPhotos: false, msg: { text: `Failed to load photos: ${err.message}`, isError: true } } : prev);
    }
  };

  const closeDetail = () => {
    setDetail(null);
    setPhotosRev(r => r + 1);
    fetchStudents();
  };

  const refreshDetailPhotos = async (studentId) => {
    const d = await api.getStudentPhotos(studentId);
    setPhotosRev(r => r + 1);
    setDetail(prev => prev ? { ...prev, photos: d?.photos || [] } : prev);
  };

  const handleDetailFiles = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length || !detail) return;
    const studentId = detail.student.student_id;
    setDetail(prev => prev ? { ...prev, photoBusy: true, msg: null } : prev);
    try {
      const images = await Promise.all(files.map(f => new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (ev) => resolve(ev.target.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(f);
      })));
      const valid = images.filter(Boolean);
      if (!valid.length) throw new Error('Could not read selected files');
      const res = await api.addStudentPhotos(studentId, valid);
      await refreshDetailPhotos(studentId);
      setDetail(prev => prev ? {
        ...prev,
        photoBusy: false,
        msg: {
          text: `${res.added} photo(s) added — face model re-encoded automatically.`,
          isError: false
        }
      } : prev);
    } catch (err) {
      setDetail(prev => prev ? {
        ...prev,
        photoBusy: false,
        msg: { text: `Add photos failed: ${err.message}`, isError: true }
      } : prev);
    }
  };

  const handleDeletePhoto = async (index) => {
    if (!detail) return;
    if (!window.confirm(`Delete reference photo #${index + 1}? The face model will be re-encoded.`)) return;
    const studentId = detail.student.student_id;
    setDetail(prev => prev ? { ...prev, photoBusy: true, msg: null } : prev);
    try {
      const res = await api.deleteStudentPhoto(studentId, index);
      await refreshDetailPhotos(studentId);
      setDetail(prev => prev ? {
        ...prev,
        photoBusy: false,
        msg: {
          text: res.remaining === 0
            ? 'Last photo removed — student will not be recognized until a photo is added.'
            : `Photo deleted — face model re-encoded (${res.remaining} remaining).`,
          isError: res.remaining === 0
        }
      } : prev);
    } catch (err) {
      setDetail(prev => prev ? {
        ...prev,
        photoBusy: false,
        msg: { text: `Delete failed: ${err.message}`, isError: true }
      } : prev);
    }
  };

  const handleSaveDetail = async () => {
    if (!detail) return;
    const { student, form } = detail;
    if (!form.name.trim()) {
      setDetail(prev => prev ? { ...prev, msg: { text: 'Name cannot be empty', isError: true } } : prev);
      return;
    }
    setDetail(prev => prev ? { ...prev, saving: true, msg: null } : prev);
    try {
      await api.updateStudent(student.student_id, {
        name: form.name.trim(),
        email: form.email.trim() || null,
        department: form.department || null
      });
      setPhotosRev(r => r + 1);
      fetchStudents();
      setDetail(prev => prev ? {
        ...prev,
        saving: false,
        student: { ...prev.student, name: form.name.trim(), email: form.email.trim() || null, department: form.department || null },
        msg: { text: 'Student details saved.', isError: false }
      } : prev);
    } catch (err) {
      setDetail(prev => prev ? {
        ...prev,
        saving: false,
        msg: { text: `Save failed: ${err.message}`, isError: true }
      } : prev);
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
            Tap a student to view or edit details and manage reference photos.
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
            <div
              key={st.student_id || st.id}
              className="glass-panel glass-panel-interactive"
              onClick={() => openDetail(st)}
              style={{
                padding: '20px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: '16px',
                transition: 'all 0.2s ease',
                cursor: 'pointer'
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <StudentAvatar studentId={st.student_id} name={st.name} cacheKey={photosRev} />
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

              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                borderTop: '1px solid var(--border-subtle)',
                paddingTop: '12px'
              }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-dim)' }}>Tap card to view / edit</span>
                <button
                  className="btn btn-secondary"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(st.student_id, st.name);
                  }}
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

      {/* Student Detail Modal (view/edit details + reference photos) */}
      {detail && (
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
          padding: '16px'
        }}>
          <div className="glass-panel" style={{
            maxWidth: '540px',
            width: '100%',
            maxHeight: '92vh',
            overflowY: 'auto',
            padding: '24px',
            background: 'var(--bg-card-solid)',
            position: 'relative'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <StudentAvatar studentId={detail.student.student_id} name={detail.form.name} size={40} radius={10} cacheKey={photosRev} />
                Student Details
              </h3>
              <button 
                onClick={closeDetail}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            {detail.msg && (
              <div style={{
                padding: '10px 12px',
                borderRadius: '8px',
                background: detail.msg.isError ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                color: detail.msg.isError ? '#f87171' : '#34d399',
                fontSize: '0.8rem',
                marginBottom: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                {detail.msg.isError ? <AlertCircle size={15} /> : <CheckCircle size={15} />}
                <span>{detail.msg.text}</span>
              </div>
            )}

            {/* Editable details */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '18px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Full Name
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={detail.form.name}
                  onChange={(e) => setDetail(prev => ({ ...prev, form: { ...prev.form, name: e.target.value } }))}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Student ID
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={detail.student.student_id}
                  disabled
                  style={{ opacity: 0.6, fontFamily: 'monospace' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Department
                  </label>
                  <select
                    className="input-field"
                    value={detail.form.department}
                    onChange={(e) => setDetail(prev => ({ ...prev, form: { ...prev.form, department: e.target.value } }))}
                  >
                    {[...new Set([...DEPARTMENTS, detail.form.department].filter(Boolean))].map(d => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Email
                  </label>
                  <input
                    type="email"
                    className="input-field"
                    placeholder="student@university.edu"
                    value={detail.form.email}
                    onChange={(e) => setDetail(prev => ({ ...prev, form: { ...prev.form, email: e.target.value } }))}
                  />
                </div>
              </div>
            </div>

            {/* Reference photos (embeddings + detection source) */}
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '14px', marginBottom: '16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <h4 style={{ fontSize: '0.95rem', fontWeight: 700 }}>
                  Reference Photos ({detail.photos.length})
                </h4>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={detail.photoBusy}
                  onClick={() => detailFileRef.current?.click()}
                  style={{ padding: '6px 12px', fontSize: '0.78rem' }}
                >
                  <Camera size={14} />
                  <span>{detail.photoBusy ? 'Working...' : 'Add Photo(s)'}</span>
                </button>
                <input
                  ref={detailFileRef}
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={handleDetailFiles}
                  style={{ display: 'none' }}
                />
              </div>

              {detail.loadingPhotos ? (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>Loading photos...</p>
              ) : detail.photos.length === 0 ? (
                <div style={{
                  padding: '18px',
                  textAlign: 'center',
                  borderRadius: 'var(--radius-md)',
                  border: '1px dashed rgba(99, 102, 241, 0.4)',
                  color: 'var(--text-dim)',
                  fontSize: '0.8rem'
                }}>
                  No reference photos yet. The student will not be recognized until at least one is added.
                </div>
              ) : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))',
                  gap: '10px'
                }}>
                  {detail.photos.map((p) => (
                    <div key={p.index} style={{
                      position: 'relative',
                      aspectRatio: '1 / 1',
                      borderRadius: 'var(--radius-sm)',
                      overflow: 'hidden',
                      border: '1px solid var(--border-subtle)'
                    }}>
                      <img
                        src={`${getStudentPhotoUrl(detail.student.student_id, p.index)}?v=${photosRev}`}
                        alt={p.name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                      <button
                        type="button"
                        onClick={() => handleDeletePhoto(p.index)}
                        disabled={detail.photoBusy}
                        style={{
                          position: 'absolute',
                          top: '4px',
                          right: '4px',
                          background: 'rgba(239, 68, 68, 0.85)',
                          border: 'none',
                          borderRadius: '50%',
                          width: '22px',
                          height: '22px',
                          color: '#ffffff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: 'pointer'
                        }}
                        title="Delete this reference photo"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', marginTop: '10px', lineHeight: 1.4 }}>
                <strong>Reference photos</strong> power recognition and detection. Adding or deleting photos
                automatically re-encodes the face model for this student.
              </p>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
              <button
                className="btn btn-secondary"
                onClick={() => handleDelete(detail.student.student_id, detail.form.name)}
                style={{ color: '#f87171' }}
              >
                <Trash2 size={15} />
                <span>Delete Student</span>
              </button>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  className="btn btn-secondary"
                  onClick={closeDetail}
                >
                  Close
                </button>
                <button
                  className="btn btn-success"
                  onClick={handleSaveDetail}
                  disabled={detail.saving}
                >
                  <Save size={15} />
                  <span>{detail.saving ? 'Saving...' : 'Save Changes'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

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
                  {DEPARTMENTS.filter(d => d !== 'Other').map(d => (
                    <option key={d} value={d}>{d}</option>
                  ))}
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
