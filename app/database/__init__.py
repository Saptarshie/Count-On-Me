"""
Database Module for Attendance and Engagement Storage.

This module provides SQLite database operations for:
- Classroom session creation and multi-session tracking on the same date
- Student registration and management
- Attendance tracking with per-session duplicate prevention
- Manual correction of student attendance status
- Engagement score logging
- Analytics and reporting

Features:
- Multi-session support per day (e.g. Physics, Chemistry, Math)
- Automatic table creation & schema migration
- Thread-safe operations
- Session deletion with cascade cleanup
- Manual status override (Present, Late, Excused, Absent)
- CSV export support

Author: AI Engineer & Antigravity
Version: 2.0.0
"""

import sqlite3
import csv
import shutil
import re
from datetime import datetime, date as date_type, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from contextlib import contextmanager
from dataclasses import dataclass, asdict
import threading
import logging

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config


# Configure module logger
logger = logging.getLogger(__name__)


@dataclass
class Student:
    """Data class for student record."""
    
    id: Optional[int] = None
    student_id: str = ""
    name: str = ""
    email: Optional[str] = None
    department: Optional[str] = None
    created_at: Optional[datetime] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'student_id': self.student_id,
            'name': self.name,
            'email': self.email,
            'department': self.department,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at or ''),
            'is_active': bool(self.is_active)
        }


@dataclass
class Session:
    """Data class for a classroom session."""
    
    id: Optional[int] = None
    session_id: str = ""
    title: str = ""
    course: Optional[str] = None
    date: Optional[date_type] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room: Optional[str] = None
    is_active: bool = False
    created_at: Optional[datetime] = None
    present_count: int = 0
    avg_engagement: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'session_id': self.session_id,
            'title': self.title,
            'course': self.course or self.title,
            'date': self.date.isoformat() if isinstance(self.date, (date_type, datetime)) else str(self.date),
            'start_time': self.start_time or '',
            'end_time': self.end_time or '',
            'room': self.room or '',
            'is_active': bool(self.is_active),
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at or ''),
            'present_count': int(self.present_count or 0),
            'avg_engagement': round(float(self.avg_engagement or 0.0), 1)
        }


@dataclass
class AttendanceRecord:
    """Data class for attendance record."""
    
    id: Optional[int] = None
    student_name: str = ""
    student_id: Optional[str] = None
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    course: Optional[str] = None
    date: Optional[date_type] = None
    time: Optional[str] = None
    engagement_score: float = 0.0
    status: str = "Present"
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.student_name,
            'student_name': self.student_name,
            'student_id': self.student_id,
            'session_id': self.session_id,
            'session_title': self.session_title or self.session_id,
            'course': self.course or '',
            'date': self.date.isoformat() if isinstance(self.date, (date_type, datetime)) else str(self.date),
            'time': self.time,
            'engagement_score': round(float(self.engagement_score or 0.0), 1),
            'status': self.status,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at or '')
        }


@dataclass
class EngagementLog:
    """Data class for engagement log entry."""
    
    id: Optional[int] = None
    student_name: str = ""
    timestamp: Optional[datetime] = None
    engagement_score: float = 0.0
    status: str = ""
    ear_value: float = 0.0
    head_pose_yaw: float = 0.0
    head_pose_pitch: float = 0.0


class DatabaseManager:
    """
    Database Manager for SQLite operations.
    
    Provides thread-safe database access with connection pooling
    and automatic schema migration.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or config.database.database_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize and migrate database
        self._init_database()
        
        logger.info(f"DatabaseManager initialized with {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """Get a database connection (thread-safe)."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._local.connection.row_factory = sqlite3.Row
        
        try:
            yield self._local.connection
        except Exception as e:
            self._local.connection.rollback()
            logger.error(f"Database error: {e}")
            raise
    
    def _init_database(self):
        """Initialize database schema and migrate to multi-session support."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Students table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT,
                    department TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            ''')
            
            # 2. Sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    course TEXT,
                    date DATE NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    room TEXT,
                    is_active BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 3. Check attendance table columns & migration
            cursor.execute("PRAGMA table_info(attendance)")
            columns = [row['name'] for row in cursor.fetchall()]
            
            if not columns:
                # Fresh attendance table with session_id support
                cursor.execute('''
                    CREATE TABLE attendance (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_name TEXT NOT NULL,
                        student_id TEXT,
                        session_id TEXT NOT NULL,
                        date DATE NOT NULL,
                        time TEXT NOT NULL,
                        engagement_score REAL DEFAULT 0.0,
                        status TEXT DEFAULT 'Present',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(student_name, session_id)
                    )
                ''')
            elif 'session_id' not in columns:
                logger.info("Migrating attendance table to multi-session schema...")
                
                # Fetch distinct dates from existing attendance records
                cursor.execute("SELECT DISTINCT date FROM attendance")
                distinct_dates = [row['date'] for row in cursor.fetchall()]
                
                for d in distinct_dates:
                    d_str = str(d)
                    slug_date = d_str.replace('-', '')
                    sess_id = f"SES_{slug_date}_GENERAL"
                    cursor.execute("SELECT id FROM sessions WHERE session_id = ?", (sess_id,))
                    if not cursor.fetchone():
                        cursor.execute('''
                            INSERT INTO sessions (session_id, title, course, date, start_time, end_time, room, is_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (sess_id, f"General Class - {d_str}", "General", d_str, "09:00", "17:00", "Main Classroom", 0))
                
                # Create migrated table with UNIQUE(student_name, session_id)
                cursor.execute('''
                    CREATE TABLE attendance_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_name TEXT NOT NULL,
                        student_id TEXT,
                        session_id TEXT NOT NULL,
                        date DATE NOT NULL,
                        time TEXT NOT NULL,
                        engagement_score REAL DEFAULT 0.0,
                        status TEXT DEFAULT 'Present',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(student_name, session_id)
                    )
                ''')
                
                cursor.execute('''
                    INSERT INTO attendance_migrated (id, student_name, student_id, session_id, date, time, engagement_score, status, created_at)
                    SELECT id, student_name, student_id, 'SES_' || replace(date, '-', '') || '_GENERAL', date, time, engagement_score, status, created_at
                    FROM attendance
                ''')
                
                cursor.execute("DROP TABLE attendance")
                cursor.execute("ALTER TABLE attendance_migrated RENAME TO attendance")
                logger.info("Successfully migrated attendance table to multi-session schema")
            
            # 4. Engagement logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS engagement_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    engagement_score REAL DEFAULT 0.0,
                    status TEXT,
                    ear_value REAL DEFAULT 0.0,
                    head_pose_yaw REAL DEFAULT 0.0,
                    head_pose_pitch REAL DEFAULT 0.0
                )
            ''')
            
            # 5. Create indices
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_engagement_timestamp ON engagement_logs(timestamp)')
            
            # 6. Ensure at least one session exists and is active for today
            today_str = date_type.today().isoformat()
            cursor.execute("SELECT id FROM sessions WHERE is_active = 1")
            if not cursor.fetchone():
                cursor.execute("SELECT session_id FROM sessions WHERE date = ? ORDER BY id DESC LIMIT 1", (today_str,))
                row_today = cursor.fetchone()
                if row_today:
                    cursor.execute("UPDATE sessions SET is_active = 1 WHERE session_id = ?", (row_today['session_id'],))
                else:
                    default_id = f"SES_{today_str.replace('-', '')}_DEFAULT"
                    cursor.execute('''
                        INSERT INTO sessions (session_id, title, course, date, start_time, end_time, room, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (default_id, f"General Class ({today_str})", "General", today_str, "09:00", "10:00", "Room 101", 1))

            conn.commit()
            logger.info("Database schema initialized and verified")


class SessionRepository:
    """Repository for classroom session management."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def create_session(self, session: Session) -> Session:
        """Create a new session. If marked active, deactivates other sessions."""
        sess_date = session.date or date_type.today()
        date_str = sess_date.isoformat() if isinstance(sess_date, (date_type, datetime)) else str(sess_date)
        
        if not session.session_id:
            slug = re.sub(r'[^a-zA-Z0-9]', '_', session.title or 'session').strip('_').upper()[:16]
            session.session_id = f"SES_{date_str.replace('-', '')}_{slug}_{datetime.now().strftime('%H%M%S')}"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if session.is_active:
                cursor.execute('UPDATE sessions SET is_active = 0')
                
            cursor.execute('''
                INSERT INTO sessions (session_id, title, course, date, start_time, end_time, room, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.session_id,
                session.title,
                session.course or session.title,
                date_str,
                session.start_time or datetime.now().strftime('%H:%M'),
                session.end_time or '',
                session.room or 'Main Classroom',
                1 if session.is_active else 0
            ))
            session.id = cursor.lastrowid
            conn.commit()
            
        logger.info(f"Created session: {session.title} ({session.session_id})")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session details with present student count and average engagement."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.*, 
                       COUNT(a.id) as present_count,
                       COALESCE(AVG(a.engagement_score), 0.0) as avg_engagement
                FROM sessions s
                LEFT JOIN attendance a ON s.session_id = a.session_id
                WHERE s.session_id = ?
                GROUP BY s.id
            ''', (session_id,))
            row = cursor.fetchone()
            if row:
                return Session(
                    id=row['id'],
                    session_id=row['session_id'],
                    title=row['title'],
                    course=row['course'],
                    date=row['date'],
                    start_time=row['start_time'],
                    end_time=row['end_time'],
                    room=row['room'],
                    is_active=bool(row['is_active']),
                    created_at=row['created_at'],
                    present_count=row['present_count'],
                    avg_engagement=row['avg_engagement']
                )
        return None

    def get_active_session(self) -> Session:
        """Get the active session for live camera attendance. Auto-creates if missing."""
        today = date_type.today()
        today_str = today.isoformat()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.*, 
                       COUNT(a.id) as present_count,
                       COALESCE(AVG(a.engagement_score), 0.0) as avg_engagement
                FROM sessions s
                LEFT JOIN attendance a ON s.session_id = a.session_id
                WHERE s.is_active = 1
                GROUP BY s.id
                LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                return Session(
                    id=row['id'],
                    session_id=row['session_id'],
                    title=row['title'],
                    course=row['course'],
                    date=row['date'],
                    start_time=row['start_time'],
                    end_time=row['end_time'],
                    room=row['room'],
                    is_active=True,
                    created_at=row['created_at'],
                    present_count=row['present_count'],
                    avg_engagement=row['avg_engagement']
                )
            
            # None active: check latest for today
            cursor.execute("SELECT session_id FROM sessions WHERE date = ? ORDER BY id DESC LIMIT 1", (today_str,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT session_id FROM sessions ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                
            if row:
                self.set_active_session(row['session_id'])
                return self.get_session(row['session_id'])
            
            # Create default session for today
            default_session = Session(
                title=f"General Class ({today_str})",
                course="General",
                date=today,
                start_time="09:00",
                end_time="10:00",
                room="Room 101",
                is_active=True
            )
            return self.create_session(default_session)

    def set_active_session(self, session_id: str) -> bool:
        """Activate a session for live camera feed attendance."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE sessions SET is_active = 0')
            cursor.execute('UPDATE sessions SET is_active = 1 WHERE session_id = ?', (session_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_sessions_by_date(self, check_date: Optional[date_type] = None) -> List[Session]:
        """Get all sessions for a specific date with live attendance stats."""
        check_date = check_date or date_type.today()
        date_str = check_date.isoformat() if isinstance(check_date, (date_type, datetime)) else str(check_date)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.*, 
                       COUNT(a.id) as present_count,
                       COALESCE(AVG(a.engagement_score), 0.0) as avg_engagement
                FROM sessions s
                LEFT JOIN attendance a ON s.session_id = a.session_id
                WHERE s.date = ?
                GROUP BY s.id
                ORDER BY s.is_active DESC, s.start_time DESC, s.id DESC
            ''', (date_str,))
            return [
                Session(
                    id=row['id'],
                    session_id=row['session_id'],
                    title=row['title'],
                    course=row['course'],
                    date=row['date'],
                    start_time=row['start_time'],
                    end_time=row['end_time'],
                    room=row['room'],
                    is_active=bool(row['is_active']),
                    created_at=row['created_at'],
                    present_count=row['present_count'],
                    avg_engagement=row['avg_engagement']
                )
                for row in cursor.fetchall()
            ]

    def get_all_sessions(self) -> List[Session]:
        """Get all sessions across all dates."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT s.*, 
                       COUNT(a.id) as present_count,
                       COALESCE(AVG(a.engagement_score), 0.0) as avg_engagement
                FROM sessions s
                LEFT JOIN attendance a ON s.session_id = a.session_id
                GROUP BY s.id
                ORDER BY s.date DESC, s.start_time DESC, s.id DESC
            ''')
            return [
                Session(
                    id=row['id'],
                    session_id=row['session_id'],
                    title=row['title'],
                    course=row['course'],
                    date=row['date'],
                    start_time=row['start_time'],
                    end_time=row['end_time'],
                    room=row['room'],
                    is_active=bool(row['is_active']),
                    created_at=row['created_at'],
                    present_count=row['present_count'],
                    avg_engagement=row['avg_engagement']
                )
                for row in cursor.fetchall()
            ]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its associated attendance records."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT is_active FROM sessions WHERE session_id = ?', (session_id,))
            row = cursor.fetchone()
            was_active = row and bool(row['is_active'])
            
            # Delete attendance records in this session
            cursor.execute('DELETE FROM attendance WHERE session_id = ?', (session_id,))
            
            # Delete the session itself
            cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
            success = cursor.rowcount > 0
            
            # If the deleted session was active, activate the next available session
            if was_active:
                cursor.execute('SELECT session_id FROM sessions ORDER BY date DESC, id DESC LIMIT 1')
                next_row = cursor.fetchone()
                if next_row:
                    cursor.execute('UPDATE sessions SET is_active = 1 WHERE session_id = ?', (next_row['session_id'],))
                    
            conn.commit()
            logger.info(f"Deleted session {session_id} and purged attendance records")
            return success


class StudentRepository:
    """Repository for student CRUD operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def add_student(self, student: Student) -> int:
        """Add a new student."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO students (student_id, name, email, department)
                VALUES (?, ?, ?, ?)
            ''', (student.student_id, student.name, student.email, student.department))
            conn.commit()
            logger.info(f"Added student: {student.name}")
            return cursor.lastrowid
    
    def get_student(self, student_id: str) -> Optional[Student]:
        """Get student by ID."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM students WHERE student_id = ?', (student_id,))
            row = cursor.fetchone()
            if row:
                return Student(
                    id=row['id'],
                    student_id=row['student_id'],
                    name=row['name'],
                    email=row['email'],
                    department=row['department'],
                    created_at=row['created_at'],
                    is_active=row['is_active']
                )
        return None
    
    def get_student_by_name(self, name: str) -> Optional[Student]:
        """Get student by name."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM students WHERE name = ?', (name,))
            row = cursor.fetchone()
            if row:
                return Student(
                    id=row['id'],
                    student_id=row['student_id'],
                    name=row['name'],
                    email=row['email'],
                    department=row['department'],
                    created_at=row['created_at'],
                    is_active=row['is_active']
                )
        return None
    
    def get_all_students(self, active_only: bool = True) -> List[Student]:
        """Get all students."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute('SELECT * FROM students WHERE is_active = 1 ORDER BY name')
            else:
                cursor.execute('SELECT * FROM students ORDER BY name')
            
            return [
                Student(
                    id=row['id'],
                    student_id=row['student_id'],
                    name=row['name'],
                    email=row['email'],
                    department=row['department'],
                    created_at=row['created_at'],
                    is_active=row['is_active']
                )
                for row in cursor.fetchall()
            ]
    
    def update_student(self, student_id: str, **kwargs) -> bool:
        """Update student information."""
        allowed_fields = {'name', 'email', 'department', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [student_id]
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE students SET {set_clause} WHERE student_id = ?', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_student(self, student_id: str, soft_delete: bool = True) -> bool:
        """Delete student (soft or hard)."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if soft_delete:
                cursor.execute('UPDATE students SET is_active = 0 WHERE student_id = ?', (student_id,))
            else:
                cursor.execute('DELETE FROM students WHERE student_id = ?', (student_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def count_students(self, active_only: bool = True) -> int:
        """Count total students."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute('SELECT COUNT(*) FROM students WHERE is_active = 1')
            else:
                cursor.execute('SELECT COUNT(*) FROM students')
            return cursor.fetchone()[0]
            
    get_student_count = count_students


class AttendanceRepository:
    """Repository for attendance operations with multi-session support."""
    
    def __init__(self, db_manager: DatabaseManager, session_repo: Optional[SessionRepository] = None):
        self.db = db_manager
        self._session_repo = session_repo

    def set_session_repo(self, session_repo: SessionRepository):
        self._session_repo = session_repo

    def mark_attendance(
        self,
        student_name: str,
        engagement_score: float = 0.0,
        status: str = "Present",
        session_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Mark attendance for a student in a specific session.
        If session_id is None, automatically resolves the active session.
        """
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Resolve active session if not provided
        if not session_id and self._session_repo:
            active = self._session_repo.get_active_session()
            session_id = active.session_id if active else None
            sess_date = active.date if active else date_type.today()
        else:
            sess_date = date_type.today()
            
        if not session_id:
            today_str = sess_date.isoformat()
            session_id = f"SES_{today_str.replace('-', '')}_DEFAULT"

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Retrieve session date from sessions table
            cursor.execute('SELECT date FROM sessions WHERE session_id = ?', (session_id,))
            s_row = cursor.fetchone()
            if s_row:
                sess_date = s_row['date']
            
            # Lookup student ID
            cursor.execute('SELECT student_id FROM students WHERE name = ?', (student_name,))
            st_row = cursor.fetchone()
            student_id = st_row['student_id'] if st_row else None
            
            # Check for existing attendance in this session
            cursor.execute('''
                SELECT id FROM attendance 
                WHERE student_name = ? AND session_id = ?
            ''', (student_name, session_id))
            
            existing = cursor.fetchone()
            if existing:
                # Update engagement score if already marked
                cursor.execute('''
                    UPDATE attendance 
                    SET engagement_score = ?
                    WHERE id = ?
                ''', (engagement_score, existing['id']))
                conn.commit()
                return False, "Attendance already marked in this session"
            
            # Insert new attendance
            cursor.execute('''
                INSERT INTO attendance (student_name, student_id, session_id, date, time, engagement_score, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (student_name, student_id, session_id, sess_date, current_time, engagement_score, status))
            conn.commit()
            
            logger.info(f"Marked attendance for {student_name} in session {session_id}")
            return True, "Attendance marked successfully"

    def is_attendance_marked(
        self, 
        student_name: str, 
        session_id: Optional[str] = None,
        check_date: Optional[date_type] = None
    ) -> bool:
        """Check if attendance is already marked for a student in a session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute('''
                    SELECT id FROM attendance 
                    WHERE student_name = ? AND session_id = ?
                ''', (student_name, session_id))
            else:
                check_date = check_date or date_type.today()
                cursor.execute('''
                    SELECT id FROM attendance 
                    WHERE student_name = ? AND date = ?
                ''', (student_name, check_date))
            return cursor.fetchone() is not None

    def get_attendance_by_session(self, session_id: str) -> List[AttendanceRecord]:
        """Get all attendance records for a specific session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT a.*, s.title as session_title, s.course
                FROM attendance a
                LEFT JOIN sessions s ON a.session_id = s.session_id
                WHERE a.session_id = ?
                ORDER BY a.time DESC, a.id DESC
            ''', (session_id,))
            return [
                AttendanceRecord(
                    id=row['id'],
                    student_name=row['student_name'],
                    student_id=row['student_id'],
                    session_id=row['session_id'],
                    session_title=row['session_title'],
                    course=row['course'],
                    date=row['date'],
                    time=row['time'],
                    engagement_score=row['engagement_score'],
                    status=row['status'],
                    created_at=row['created_at']
                )
                for row in cursor.fetchall()
            ]

    def get_attendance_by_date(
        self, 
        check_date: Optional[date_type] = None,
        session_id: Optional[str] = None
    ) -> List[AttendanceRecord]:
        """Get attendance records for a date or session."""
        if session_id:
            return self.get_attendance_by_session(session_id)
            
        check_date = check_date or date_type.today()
        date_str = check_date.isoformat() if isinstance(check_date, (date_type, datetime)) else str(check_date)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT a.*, s.title as session_title, s.course
                FROM attendance a
                LEFT JOIN sessions s ON a.session_id = s.session_id
                WHERE a.date = ?
                ORDER BY a.session_id, a.time DESC, a.id DESC
            ''', (date_str,))
            return [
                AttendanceRecord(
                    id=row['id'],
                    student_name=row['student_name'],
                    student_id=row['student_id'],
                    session_id=row['session_id'],
                    session_title=row['session_title'],
                    course=row['course'],
                    date=row['date'],
                    time=row['time'],
                    engagement_score=row['engagement_score'],
                    status=row['status'],
                    created_at=row['created_at']
                )
                for row in cursor.fetchall()
            ]

    def update_attendance_status(
        self,
        record_id: int,
        status: str,
        engagement_score: Optional[float] = None
    ) -> bool:
        """Manually correct student attendance status and optionally engagement score."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if engagement_score is not None:
                cursor.execute('''
                    UPDATE attendance 
                    SET status = ?, engagement_score = ?
                    WHERE id = ?
                ''', (status, engagement_score, record_id))
            else:
                cursor.execute('''
                    UPDATE attendance 
                    SET status = ?
                    WHERE id = ?
                ''', (status, record_id))
            conn.commit()
            return cursor.rowcount > 0

    def manual_mark_student(
        self,
        session_id: str,
        student_name: str,
        status: str = "Present",
        engagement_score: float = 100.0,
        time_str: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Manually add or correct a student's attendance in a session."""
        time_str = time_str or datetime.now().strftime("%H:%M:%S")
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            # Find session date
            cursor.execute('SELECT date FROM sessions WHERE session_id = ?', (session_id,))
            s_row = cursor.fetchone()
            sess_date = s_row['date'] if s_row else date_type.today()
            
            # Find student_id
            cursor.execute('SELECT student_id FROM students WHERE name = ?', (student_name,))
            st_row = cursor.fetchone()
            student_id = st_row['student_id'] if st_row else None
            
            # Check existing record in this session
            cursor.execute('SELECT id FROM attendance WHERE student_name = ? AND session_id = ?', (student_name, session_id))
            existing = cursor.fetchone()
            if existing:
                cursor.execute('''
                    UPDATE attendance 
                    SET status = ?, engagement_score = ?
                    WHERE id = ?
                ''', (status, engagement_score, existing['id']))
                conn.commit()
                return True, "Updated existing student attendance record"
            
            cursor.execute('''
                INSERT INTO attendance (student_name, student_id, session_id, date, time, engagement_score, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (student_name, student_id, session_id, sess_date, time_str, engagement_score, status))
            conn.commit()
            return True, f"Student {student_name} marked as {status}"

    def delete_attendance(self, record_id: int) -> bool:
        """Delete an attendance record."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM attendance WHERE id = ?', (record_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_engagement_score(
        self,
        student_name: str,
        engagement_score: float,
        session_id: Optional[str] = None,
        check_date: Optional[date_type] = None
    ) -> bool:
        """Update engagement score for an attendance record in a session."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute('''
                    UPDATE attendance 
                    SET engagement_score = ?
                    WHERE student_name = ? AND session_id = ?
                ''', (engagement_score, student_name, session_id))
            else:
                check_date = check_date or date_type.today()
                cursor.execute('''
                    UPDATE attendance 
                    SET engagement_score = ?
                    WHERE student_name = ? AND date = ?
                ''', (engagement_score, student_name, check_date))
            conn.commit()
            return cursor.rowcount > 0

    def get_average_engagement(
        self, 
        check_date: Optional[date_type] = None,
        session_id: Optional[str] = None
    ) -> float:
        """Get average engagement score for a session or date."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute('SELECT AVG(engagement_score) FROM attendance WHERE session_id = ?', (session_id,))
            else:
                check_date = check_date or date_type.today()
                cursor.execute('SELECT AVG(engagement_score) FROM attendance WHERE date = ?', (check_date,))
            result = cursor.fetchone()[0]
            return float(result) if result else 0.0

    def get_attendance_count(
        self,
        check_date: Optional[date_type] = None,
        session_id: Optional[str] = None
    ) -> int:
        """Get count of attendance records for a session or date."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute('SELECT COUNT(*) as cnt FROM attendance WHERE session_id = ?', (session_id,))
            else:
                check_date = check_date or date_type.today()
                date_str = check_date.isoformat() if isinstance(check_date, (date_type, datetime)) else str(check_date)
                cursor.execute('SELECT COUNT(*) as cnt FROM attendance WHERE date = ?', (date_str,))
            row = cursor.fetchone()
            return int(row['cnt']) if row and row['cnt'] is not None else 0


class EngagementRepository:
    """Repository for engagement log operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    def log_engagement(self, log: EngagementLog) -> int:
        """Log engagement data."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO engagement_logs 
                (student_name, engagement_score, status, ear_value, head_pose_yaw, head_pose_pitch)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (log.student_name, log.engagement_score, log.status,
                  log.ear_value, log.head_pose_yaw, log.head_pose_pitch))
            conn.commit()
            return cursor.lastrowid
    
    def get_student_engagement_history(
        self,
        student_name: str,
        hours: int = 1
    ) -> List[EngagementLog]:
        """Get engagement history for a student."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM engagement_logs 
                WHERE student_name = ? AND timestamp > ?
                ORDER BY timestamp ASC
            ''', (student_name, cutoff))
            
            return [
                EngagementLog(
                    id=row['id'],
                    student_name=row['student_name'],
                    timestamp=row['timestamp'],
                    engagement_score=row['engagement_score'],
                    status=row['status'],
                    ear_value=row['ear_value'],
                    head_pose_yaw=row['head_pose_yaw'],
                    head_pose_pitch=row['head_pose_pitch']
                )
                for row in cursor.fetchall()
            ]
    
    def get_average_engagement_by_student(self, hours: int = 1) -> Dict[str, float]:
        """Get average engagement per student over time period."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT student_name, AVG(engagement_score) as avg_score
                FROM engagement_logs 
                WHERE timestamp > ?
                GROUP BY student_name
            ''', (cutoff,))
            
            return {row['student_name']: row['avg_score'] for row in cursor.fetchall()}
    
    def cleanup_old_logs(self, days: int = 30) -> int:
        """Delete engagement logs older than specified days."""
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM engagement_logs WHERE timestamp < ?
            ''', (cutoff,))
            conn.commit()
            deleted = cursor.rowcount
            logger.info(f"Cleaned up {deleted} old engagement logs")
            return deleted


class DatabaseService:
    """
    High-level database service combining all repositories.
    
    Provides a unified interface for all database operations including
    sessions, attendance, students, and engagement logs.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_manager = DatabaseManager(db_path)
        self.students = StudentRepository(self.db_manager)
        self.sessions = SessionRepository(self.db_manager)
        self.attendance = AttendanceRepository(self.db_manager, self.sessions)
        self.engagement = EngagementRepository(self.db_manager)
        
        logger.info("DatabaseService initialized with Sessions support")
    
    def get_dashboard_stats(
        self, 
        check_date: Optional[date_type] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics for dashboard display, scoped to session or date."""
        check_date = check_date or date_type.today()
        total_students = self.students.count_students()
        
        # Get active session
        active_session = self.sessions.get_active_session()
        active_sess_dict = active_session.to_dict() if active_session else None
        
        target_session_id = session_id or (active_session.session_id if active_session else None)
        
        if target_session_id:
            attendance_records = self.attendance.get_attendance_by_session(target_session_id)
        else:
            attendance_records = self.attendance.get_attendance_by_date(check_date)
            
        present_count = len(attendance_records)
        avg_engagement = (
            sum(r.engagement_score for r in attendance_records) / present_count
        ) if present_count > 0 else 0.0
        
        student_stats = [
            {
                'id': r.id,
                'name': r.student_name,
                'time': r.time,
                'engagement_score': r.engagement_score,
                'status': r.status,
                'session_id': r.session_id,
                'session_title': r.session_title
            }
            for r in attendance_records
        ]
        
        return {
            'date': check_date.isoformat(),
            'total_students': total_students,
            'present_count': present_count,
            'absent_count': max(0, total_students - present_count),
            'attendance_percentage': (present_count / total_students * 100) if total_students > 0 else 0,
            'average_engagement': round(avg_engagement, 1),
            'student_stats': student_stats,
            'active_session': active_sess_dict
        }
    
    def export_attendance_csv(
        self,
        filepath: Path,
        session_id: Optional[str] = None,
        check_date: Optional[date_type] = None
    ) -> bool:
        """Export attendance records to CSV."""
        try:
            if session_id:
                records = self.attendance.get_attendance_by_session(session_id)
            else:
                records = self.attendance.get_attendance_by_date(check_date or date_type.today())
                
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Record ID', 'Student Name', 'Student ID', 'Session ID', 'Session Title', 'Course', 'Date', 'Time', 'Engagement Score (%)', 'Status'])
                for r in records:
                    writer.writerow([
                        r.id,
                        r.student_name,
                        r.student_id or '',
                        r.session_id or '',
                        r.session_title or '',
                        r.course or '',
                        r.date,
                        r.time,
                        round(r.engagement_score, 1),
                        r.status
                    ])
            return True
        except Exception as e:
            logger.error(f"Error exporting attendance CSV: {e}")
            return False


# Singleton service instance
_db_service_instance: Optional[DatabaseService] = None


def get_database_service() -> DatabaseService:
    """Get singleton DatabaseService instance."""
    global _db_service_instance
    if _db_service_instance is None:
        _db_service_instance = DatabaseService()
    return _db_service_instance
