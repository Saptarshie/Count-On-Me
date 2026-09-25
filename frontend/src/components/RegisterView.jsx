import React, { useState, useRef, useEffect } from 'react';
import { 
  Camera, 
  Upload, 
  CheckCircle, 
  AlertCircle, 
  Trash2, 
  Sparkles, 
  RefreshCw, 
  UserPlus, 
  Smartphone,
  ShieldCheck
} from 'lucide-react';
import { api } from '../api';

export default function RegisterView({ onStudentRegistered }) {
  // Form state
  const [name, setName] = useState('');
  const [studentId, setStudentId] = useState('');
  const [email, setEmail] = useState('');
  const [department, setDepartment] = useState('Computer Science');

  // Photo state
  const [capturedImages, setCapturedImages] = useState([]); // array of base64 data URLs
  const [isCapturing, setIsCapturing] = useState(false);
  const [captureProgress, setCaptureProgress] = useState(0);
  const [poseInstruction, setPoseInstruction] = useState('Position your face in the frame');
  
  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [resultMessage, setResultMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  // Webcam references
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const captureIntervalRef = useRef(null);
  const fileInputRef = useRef(null);

  // Stop webcam stream when component unmounts
  useEffect(() => {
    return () => {
      stopWebcam();
    };
  }, []);

  const startWebcam = async () => {
    try {
      setErrorMessage(null);
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
    } catch (err) {
      console.warn('Webcam access error:', err);
      setErrorMessage(
        'Could not access live webcam. If testing from a smartphone over HTTP, use the "Upload / Mobile Camera" button below!'
      );
    }
  };

  const stopWebcam = () => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsCapturing(false);
  };

  const captureSingleFrame = () => {
    if (!videoRef.current) return null;
    const canvas = document.createElement('canvas');
    canvas.width = videoRef.current.videoWidth || 640;
    canvas.height = videoRef.current.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.85);
  };

  const startAutoCapture = async () => {
    if (!streamRef.current) {
      await startWebcam();
    }
    
    setIsCapturing(true);
    let count = 0;
    const targetCount = 10;
    setCaptureProgress(0);

    const poses = [
      'Look directly at the camera (Center)',
      'Look slightly to your left',
      'Look slightly to your right',
      'Tilt your head slightly up',
      'Tilt your head slightly down',
      'Smile naturally',
      'Neutral expression',
      'Slight head tilt',
      'Blink naturally',
      'Almost done, stay still!'
    ];

    captureIntervalRef.current = setInterval(() => {
      if (count < targetCount) {
        setPoseInstruction(poses[count] || 'Move face slightly');
        const frame = captureSingleFrame();
        if (frame) {
          setCapturedImages(prev => [...prev, frame]);
          count++;
          setCaptureProgress(Math.round((count / targetCount) * 100));
        }
      } else {
        clearInterval(captureIntervalRef.current);
        captureIntervalRef.current = null;
        setIsCapturing(false);
        setPoseInstruction('Capture complete! Check thumbnails below.');
      }
    }, 600);
  };

  // Handle file or phone camera upload
  const handleFiles = (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = (event) => {
        setCapturedImages(prev => [...prev, event.target.result]);
      };
      reader.readAsDataURL(file);
    });
  };

  const removeImage = (idx) => {
    setCapturedImages(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setErrorMessage('Student Full Name is required.');
      return;
    }
    if (capturedImages.length === 0) {
      setErrorMessage('Please capture or upload at least 1 face image.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setResultMessage(null);

    try {
      const payload = {
        name: name.trim(),
        student_id: studentId.trim() || name.trim().toLowerCase().replace(/\s+/g, '_'),
        email: email.trim() || undefined,
        department: department || undefined,
        images: capturedImages
      };

      const res = await api.registerStudent(payload);
      setResultMessage(res.message || `Successfully registered ${name}!`);
      
      // Reset form
      setName('');
      setStudentId('');
      setEmail('');
      setCapturedImages([]);
      stopWebcam();
      
      if (onStudentRegistered) onStudentRegistered();
    } catch (err) {
      setErrorMessage(err.message || 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: '1000px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Header */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            background: 'linear-gradient(135deg, #10b981, #06b6d4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#ffffff'
          }}>
            <UserPlus size={24} />
          </div>
          <div>
            <h1 style={{ fontSize: '1.5rem', fontWeight: 800 }}>Student Face Registration</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
              Add a student profile and capture facial training samples with instant live recognition encoding.
            </p>
          </div>
        </div>
      </div>

      {/* Status Messages */}
      {resultMessage && (
        <div style={{
          padding: '16px 20px',
          borderRadius: 'var(--radius-md)',
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          color: '#34d399'
        }}>
          <CheckCircle size={20} />
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{resultMessage}</span>
        </div>
      )}

      {errorMessage && (
        <div style={{
          padding: '16px 20px',
          borderRadius: 'var(--radius-md)',
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          color: '#f87171'
        }}>
          <AlertCircle size={20} />
          <span style={{ fontSize: '0.85rem' }}>{errorMessage}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '24px',
          alignItems: 'start'
        }}>
          
          {/* Column 1: Student Information */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '12px' }}>
              <ShieldCheck size={18} color="#818cf8" />
              Student Profile
            </h3>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                Full Name *
              </label>
              <input
                type="text"
                className="input-field"
                placeholder="e.g. Rahul Sharma"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                Student ID (Optional)
              </label>
              <input
                type="text"
                className="input-field"
                placeholder="Auto-generated if blank (e.g. CS2026_01)"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                Email Address (Optional)
              </label>
              <input
                type="email"
                className="input-field"
                placeholder="student@university.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '6px' }}>
                Department
              </label>
              <select
                className="input-field"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                <option value="Computer Science">Computer Science &amp; Engineering</option>
                <option value="Data Science & AI">Data Science &amp; AI</option>
                <option value="Electronics">Electronics &amp; Communication</option>
                <option value="Mechanical">Mechanical Engineering</option>
                <option value="Civil">Civil Engineering</option>
                <option value="Other">Other / General</option>
              </select>
            </div>
          </div>

          {/* Column 2: Photo Capture & Mobile Upload */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '12px' }}>
              <h3 style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Camera size={18} color="#06b6d4" />
                Facial Photo Capture
              </h3>
              <span className="badge badge-info">
                {capturedImages.length} captured
              </span>
            </div>

            {/* Live Video Preview Box */}
            <div style={{
              width: '100%',
              height: '240px',
              borderRadius: 'var(--radius-md)',
              background: '#040711',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              overflow: 'hidden',
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <video
                ref={videoRef}
                playsInline
                muted
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />

              {/* Pose Guidance Banner */}
              {isCapturing && (
                <div style={{
                  position: 'absolute',
                  bottom: '12px',
                  left: '12px',
                  right: '12px',
                  background: 'rgba(9, 13, 22, 0.85)',
                  backdropFilter: 'blur(8px)',
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid rgba(99, 102, 241, 0.4)',
                  textAlign: 'center',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  color: '#818cf8'
                }}>
                  {poseInstruction}
                </div>
              )}
            </div>

            {/* Progress Bar during capture */}
            {isCapturing && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                  <span>Capturing samples...</span>
                  <span>{captureProgress}%</span>
                </div>
                <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '999px', overflow: 'hidden' }}>
                  <div style={{
                    width: `${captureProgress}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #6366f1, #06b6d4)',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
              </div>
            )}

            {/* Capture Action Buttons */}
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              {!isCapturing ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={startAutoCapture}
                  style={{ flex: 1 }}
                >
                  <Camera size={16} />
                  <span>Start Auto-Capture</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={stopWebcam}
                  style={{ flex: 1 }}
                >
                  <span>Stop Capture</span>
                </button>
              )}

              {/* Mobile Phone Camera / File Upload Button */}
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => fileInputRef.current?.click()}
                title="Capture with phone camera or upload images from gallery"
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Smartphone size={16} color="#38bdf8" />
                <span>Phone / Files</span>
              </button>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                capture="user"
                onChange={handleFiles}
                style={{ display: 'none' }}
              />
            </div>

            <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', lineHeight: 1.4 }}>
              <strong>Tip for Phone Testing:</strong> Click "Phone / Files" to take selfies directly from your phone's native camera or select multiple face photos.
            </p>
          </div>
        </div>

        {/* Thumbnail Carousel / Grid */}
        {capturedImages.length > 0 && (
          <div className="glass-panel" style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Captured Photos ({capturedImages.length})</h3>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setCapturedImages([])}
                style={{ padding: '4px 10px', fontSize: '0.75rem' }}
              >
                Clear All
              </button>
            </div>

            <div style={{
              display: 'flex',
              gap: '12px',
              overflowX: 'auto',
              paddingBottom: '8px'
            }}>
              {capturedImages.map((imgSrc, idx) => (
                <div key={idx} style={{
                  position: 'relative',
                  width: '90px',
                  height: '90px',
                  flexShrink: 0,
                  borderRadius: 'var(--radius-sm)',
                  overflow: 'hidden',
                  border: '1px solid var(--border-subtle)'
                }}>
                  <img
                    src={imgSrc}
                    alt={`Face sample ${idx + 1}`}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  <button
                    type="button"
                    onClick={() => removeImage(idx)}
                    style={{
                      position: 'absolute',
                      top: '4px',
                      right: '4px',
                      background: 'rgba(239, 68, 68, 0.85)',
                      border: 'none',
                      borderRadius: '50%',
                      width: '20px',
                      height: '20px',
                      color: '#ffffff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: 'pointer'
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Submit Button */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="submit"
            className="btn btn-success"
            disabled={submitting || capturedImages.length === 0 || !name.trim()}
            style={{ padding: '12px 28px', fontSize: '1rem' }}
          >
            {submitting ? (
              <>
                <RefreshCw size={18} className="animate-spin" />
                <span>Encoding &amp; Saving Student...</span>
              </>
            ) : (
              <>
                <CheckCircle size={18} />
                <span>Complete Registration</span>
              </>
            )}
          </button>
        </div>

      </form>
    </div>
  );
}
