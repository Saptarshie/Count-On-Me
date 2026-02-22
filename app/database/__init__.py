"""
Database Module for Attendance and Engagement Storage.

This module provides SQLite database operations for:
- Student registration and management
- Attendance tracking with duplicate prevention
- Engagement score logging
- Analytics and reporting

Features:
- Automatic table creation
- Thread-safe operations
- Backup functionality
- CSV export support

Author: AI Engineer
Version: 1.0.0
"""

import sqlite3
import csv
import shutil
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


@dataclass
class AttendanceRecord:
    """Data class for attendance record."""
    
    id: Optional[int] = None
    student_name: str = ""
    student_id: Optional[str] = None
    date: Optional[date_type] = None
    time: Optional[str] = None
    engagement_score: float = 0.0
    status: str = "Present"
    created_at: Optional[datetime] = None


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
    and automatic schema management.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path or config.database.database_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        logger.info(f"DatabaseManager initialized with {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """
        Get a database connection (thread-safe).
        
        Yields:
            SQLite connection object
        """
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
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Students table
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
            
            # Attendance table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT NOT NULL,
                    student_id TEXT,
                    date DATE NOT NULL,
                    time TEXT NOT NULL,
                    engagement_score REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'Present',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_name, date)
                )
            ''')
            
            # Engagement logs table
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
            
            # Create indices for performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_attendance_date 
                ON attendance(date)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_attendance_student 
                ON attendance(student_name)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_engagement_timestamp 
                ON engagement_logs(timestamp)
            ''')
            
            conn.commit()
            logger.info("Database schema initialized")


class StudentRepository:
    """Repository for student CRUD operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize student repository.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager
    
    def add_student(self, student: Student) -> int:
        """
        Add a new student.
        
        Args:
            student: Student object
        
        Returns:
            Inserted row ID
        """
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
            cursor.execute(
                'SELECT * FROM students WHERE student_id = ?',
                (student_id,)
            )
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
            cursor.execute(
                'SELECT * FROM students WHERE name = ?',
                (name,)
            )
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
                cursor.execute('SELECT * FROM students WHERE is_active = 1')
            else:
                cursor.execute('SELECT * FROM students')
            
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
    
    def update_student(self, student: Student) -> bool:
        """Update student information."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE students 
                SET name = ?, email = ?, department = ?, is_active = ?
                WHERE student_id = ?
            ''', (student.name, student.email, student.department, 
                  student.is_active, student.student_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_student(self, student_id: str, soft_delete: bool = True) -> bool:
        """Delete or deactivate a student."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if soft_delete:
                cursor.execute(
                    'UPDATE students SET is_active = 0 WHERE student_id = ?',
                    (student_id,)
                )
            else:
                cursor.execute(
                    'DELETE FROM students WHERE student_id = ?',
                    (student_id,)
                )
            conn.commit()
            return cursor.rowcount > 0
    
    def count_students(self) -> int:
        """Get total number of active students."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM students WHERE is_active = 1')
            return cursor.fetchone()[0]


class AttendanceRepository:
    """Repository for attendance CRUD operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize attendance repository.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager
    
    def mark_attendance(
        self,
        student_name: str,
        engagement_score: float = 0.0,
        status: str = "Present"
    ) -> Tuple[bool, str]:
        """
        Mark attendance for a student.
        
        Args:
            student_name: Name of the student
            engagement_score: Current engagement score
            status: Attendance status
        
        Returns:
            Tuple of (success, message)
        """
        today = date_type.today()
        current_time = datetime.now().strftime("%H:%M:%S")
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check for existing attendance
            cursor.execute('''
                SELECT id FROM attendance 
                WHERE student_name = ? AND date = ?
            ''', (student_name, today))
            
            if cursor.fetchone():
                # Update engagement score if already marked
                cursor.execute('''
                    UPDATE attendance 
                    SET engagement_score = ?
                    WHERE student_name = ? AND date = ?
                ''', (engagement_score, student_name, today))
                conn.commit()
                return False, "Attendance already marked"
            
            # Insert new attendance
            cursor.execute('''
                INSERT INTO attendance (student_name, date, time, engagement_score, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (student_name, today, current_time, engagement_score, status))
            conn.commit()
            
            logger.info(f"Marked attendance for {student_name}")
            return True, "Attendance marked successfully"
    
    def is_attendance_marked(self, student_name: str, check_date: date_type = None) -> bool:
        """Check if attendance is already marked for today."""
        check_date = check_date or date_type.today()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM attendance 
                WHERE student_name = ? AND date = ?
            ''', (student_name, check_date))
            return cursor.fetchone() is not None
    
    def get_attendance_by_date(self, check_date: date_type = None) -> List[AttendanceRecord]:
        """Get all attendance records for a date."""
        check_date = check_date or date_type.today()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM attendance WHERE date = ?
                ORDER BY time DESC
            ''', (check_date,))
            
            return [
                AttendanceRecord(
                    id=row['id'],
                    student_name=row['student_name'],
                    student_id=row['student_id'],
                    date=row['date'],
                    time=row['time'],
                    engagement_score=row['engagement_score'],
                    status=row['status'],
                    created_at=row['created_at']
                )
                for row in cursor.fetchall()
            ]
    
    def get_attendance_by_student(
        self,
        student_name: str,
        start_date: date_type = None,
        end_date: date_type = None
    ) -> List[AttendanceRecord]:
        """Get attendance records for a student within date range."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            if start_date and end_date:
                cursor.execute('''
                    SELECT * FROM attendance 
                    WHERE student_name = ? AND date BETWEEN ? AND ?
                    ORDER BY date DESC
                ''', (student_name, start_date, end_date))
            else:
                cursor.execute('''
                    SELECT * FROM attendance 
                    WHERE student_name = ?
                    ORDER BY date DESC
                ''', (student_name,))
            
            return [
                AttendanceRecord(
                    id=row['id'],
                    student_name=row['student_name'],
                    student_id=row['student_id'],
                    date=row['date'],
                    time=row['time'],
                    engagement_score=row['engagement_score'],
                    status=row['status'],
                    created_at=row['created_at']
                )
                for row in cursor.fetchall()
            ]
    
    def get_attendance_count(self, check_date: date_type = None) -> int:
        """Get number of students present on a date."""
        check_date = check_date or date_type.today()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM attendance WHERE date = ?
            ''', (check_date,))
            return cursor.fetchone()[0]
    
    def get_attendance_percentage(
        self,
        total_students: int,
        check_date: date_type = None
    ) -> float:
        """Calculate attendance percentage."""
        if total_students == 0:
            return 0.0
        
        count = self.get_attendance_count(check_date)
        return (count / total_students) * 100
    
    def update_engagement_score(
        self,
        student_name: str,
        engagement_score: float,
        check_date: date_type = None
    ) -> bool:
        """Update engagement score for an attendance record."""
        check_date = check_date or date_type.today()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE attendance 
                SET engagement_score = ?
                WHERE student_name = ? AND date = ?
            ''', (engagement_score, student_name, check_date))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_average_engagement(self, check_date: date_type = None) -> float:
        """Get average engagement score for a date."""
        check_date = check_date or date_type.today()
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT AVG(engagement_score) FROM attendance WHERE date = ?
            ''', (check_date,))
            result = cursor.fetchone()[0]
            return result if result else 0.0
    
    def delete_attendance(self, record_id: int) -> bool:
        """Delete an attendance record."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM attendance WHERE id = ?', (record_id,))
            conn.commit()
            return cursor.rowcount > 0


class EngagementRepository:
    """Repository for engagement log operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize engagement repository.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager
    
    def log_engagement(self, log: EngagementLog) -> int:
        """
        Log engagement data.
        
        Args:
            log: EngagementLog object
        
        Returns:
            Inserted row ID
        """
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
                ORDER BY timestamp DESC
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
    
    Provides a unified interface for all database operations.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database service.
        
        Args:
            db_path: Path to database file
        """
        self.db_manager = DatabaseManager(db_path)
        self.students = StudentRepository(self.db_manager)
        self.attendance = AttendanceRepository(self.db_manager)
        self.engagement = EngagementRepository(self.db_manager)
        
        logger.info("DatabaseService initialized")
    
    def get_dashboard_stats(self, check_date: date_type = None) -> Dict[str, Any]:
        """
        Get statistics for dashboard display.
        
        Returns:
            Dictionary with dashboard statistics
        """
        check_date = check_date or date_type.today()
        total_students = self.students.count_students()
        
        attendance_records = self.attendance.get_attendance_by_date(check_date)
        present_count = len(attendance_records)
        
        avg_engagement = self.attendance.get_average_engagement(check_date)
        
        # Get per-student engagement
        student_stats = []
        for record in attendance_records:
            student_stats.append({
                'name': record.student_name,
                'time': record.time,
                'engagement_score': record.engagement_score,
                'status': record.status
            })
        
        return {
            'date': check_date.isoformat(),
            'total_students': total_students,
            'present_count': present_count,
            'absent_count': max(0, total_students - present_count),
            'attendance_percentage': (present_count / total_students * 100) if total_students > 0 else 0,
            'average_engagement': avg_engagement,
            'student_stats': student_stats
        }
    
    def export_attendance_csv(
        self,
        filepath: Path,
        start_date: date_type = None,
        end_date: date_type = None
    ) -> bool:
        """
        Export attendance records to CSV.
        
        Args:
            filepath: Output file path
            start_date: Start date filter
            end_date: End date filter
        
        Returns:
            True if successful
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                if start_date and end_date:
                    cursor.execute('''
                        SELECT * FROM attendance 
                        WHERE date BETWEEN ? AND ?
                        ORDER BY date DESC, time DESC
                    ''', (start_date, end_date))
                else:
                    cursor.execute('''
                        SELECT * FROM attendance ORDER BY date DESC, time DESC
                    ''')
                
                rows = cursor.fetchall()
                
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['ID', 'Student Name', 'Date', 'Time', 
                                   'Engagement Score', 'Status'])
                    
                    for row in rows:
                        writer.writerow([
                            row['id'],
                            row['student_name'],
                            row['date'],
                            row['time'],
                            row['engagement_score'],
                            row['status']
                        ])
                
                logger.info(f"Exported {len(rows)} records to {filepath}")
                return True
                
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            return False
    
    def backup_database(self, backup_path: Path = None) -> bool:
        """
        Create a backup of the database.
        
        Args:
            backup_path: Path for backup file
        
        Returns:
            True if successful
        """
        try:
            backup_path = backup_path or config.database.backup_path
            backup_path.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_path / f"attendance_backup_{timestamp}.db"
            
            shutil.copy2(self.db_manager.db_path, backup_file)
            logger.info(f"Database backed up to {backup_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error backing up database: {e}")
            return False


# Convenience functions
def get_database_service() -> DatabaseService:
    """Get a DatabaseService instance."""
    return DatabaseService()


def mark_attendance(student_name: str, engagement_score: float = 0.0) -> Tuple[bool, str]:
    """Quick function to mark attendance."""
    service = DatabaseService()
    return service.attendance.mark_attendance(student_name, engagement_score)


def get_today_attendance() -> List[AttendanceRecord]:
    """Get today's attendance records."""
    service = DatabaseService()
    return service.attendance.get_attendance_by_date()
