from flask import Flask, request, jsonify, Response, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import sqlite3
from datetime import datetime
import os
import cv2
import numpy as np
import base64
import logging
import json
from threading import Lock
from dataclasses import dataclass
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")
thread = None
thread_lock = Lock()

# Database setup
DB_PATH = '/home/roboict/cou_bus/bus_tracking.db'

@dataclass
class OccupancyData:
    count: int
    confidence: float
    method: str
    timestamp: str

class BusTrackingSystem:
    def __init__(self):
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        
        # Initialize background subtractor for motion detection
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=16, detectShadows=True
        )
        
        self.last_frame = None
        self.occupancy_history = []
        
    def detect_occupancy(self, frame_data: bytes) -> OccupancyData:
        """
        Enhanced occupancy detection using multiple methods
        """
        try:
            # Decode image
            nparr = np.frombuffer(frame_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Failed to decode image")

            # Resize for faster processing
            height, width = img.shape[:2]
            scale = min(400 / width, 400 / height)
            img_resized = cv2.resize(img, None, fx=scale, fy=scale)
            
            # 1. HOG Person Detection
            boxes_hog, weights = self.hog.detectMultiScale(
                img_resized,
                winStride=(8, 8),
                padding=(4, 4),
                scale=1.05
            )
            person_count = len(boxes_hog)

            # 2. Face Detection
            gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            face_count = len(faces)
            
            # 3. Motion Detection
            motion_count = 0
            if self.last_frame is not None:
                # Apply background subtraction
                fg_mask = self.bg_subtractor.apply(img_resized)
                
                # Count significant motion regions
                contours, _ = cv2.findContours(
                    fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                min_area = 500 * scale * scale
                motion_regions = [c for c in contours if cv2.contourArea(c) > min_area]
                motion_count = len(motion_regions)
            
            self.last_frame = img_resized
            
            # Weighted combination of detection methods
            final_count = max(
                int(0.4 * person_count + 0.4 * face_count + 0.2 * motion_count),
                max(person_count, face_count)
            )
            
            # Calculate confidence based on agreement between methods
            max_diff = max(abs(person_count - face_count),
                         abs(person_count - motion_count),
                         abs(face_count - motion_count))
            confidence = 1.0 - (max_diff / (final_count + 1) if final_count > 0 else 0)
            
            # Store in history for smoothing
            self.occupancy_history.append(final_count)
            if len(self.occupancy_history) > 5:
                self.occupancy_history.pop(0)
            
            # Smooth the count
            smoothed_count = int(sum(self.occupancy_history) / len(self.occupancy_history))
            
            return OccupancyData(
                count=smoothed_count,
                confidence=confidence,
                method="combined",
                timestamp=datetime.now().isoformat()
            )

        except Exception as e:
            logger.error(f"Error in occupancy detection: {str(e)}")
            return OccupancyData(
                count=0,
                confidence=0.0,
                method="error",
                timestamp=datetime.now().isoformat()
            )

def init_db():
    """Initialize database with enhanced schema"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # GPS data table with additional fields
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gps_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    latitude REAL,
                    longitude REAL,
                    altitude REAL,
                    speed REAL,
                    satellites INTEGER,
                    hdop REAL,
                    timestamp TEXT,
                    battery_level REAL
                )
            ''')
            
            # Enhanced video frames table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame BLOB,
                    occupancy_count INTEGER,
                    confidence REAL,
                    detection_method TEXT,
                    frame_quality REAL,
                    timestamp TEXT
                )
            ''')
            
            # New table for system statistics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bus_id TEXT,
                    uptime INTEGER,
                    wifi_strength INTEGER,
                    cpu_usage REAL,
                    memory_usage REAL,
                    timestamp TEXT
                )
            ''')
            
            conn.commit()
            logger.info("Database initialization complete!")
            
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise

# Initialize tracking system
bus_tracker = BusTrackingSystem()

@app.route('/api/gps', methods=['POST', 'GET'])
def handle_gps():
    """Enhanced GPS data handler with validation and error handling"""
    if request.method == 'POST':
        try:
            data = request.json
            required_fields = ['lat', 'lng', 'alt', 'speed', 'satellites']
            if not all(field in data for field in required_fields):
                raise ValueError("Missing required GPS fields")

            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO gps_data (
                        latitude, longitude, altitude, speed, 
                        satellites, hdop, timestamp, battery_level
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['lat'],
                    data['lng'],
                    data['alt'],
                    data['speed'],
                    data['satellites'],
                    data.get('hdop', 0.0),
                    datetime.now().isoformat(),
                    data.get('battery', 100.0)
                ))
                conn.commit()

            # Emit update via WebSocket
            socketio.emit('gps_update', data)
            return jsonify({"status": "success"}), 200

        except Exception as e:
            logger.error(f"Error handling GPS POST: {str(e)}")
            return jsonify({"error": str(e)}), 500

    else:  # GET request
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT latitude, longitude, altitude, speed, 
                           satellites, hdop, timestamp, battery_level
                    FROM gps_data
                    ORDER BY id DESC
                    LIMIT 1
                ''')
                result = cursor.fetchone()

                if result:
                    return jsonify({
                        "lat": result[0],
                        "lng": result[1],
                        "alt": result[2],
                        "speed": result[3],
                        "satellites": result[4],
                        "hdop": result[5],
                        "timestamp": result[6],
                        "battery": result[7]
                    }), 200
                else:
                    return jsonify({"error": "No GPS data available"}), 404

        except Exception as e:
            logger.error(f"Error handling GPS GET: {str(e)}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/stream', methods=['POST', 'GET'])
def handle_stream():
    """Enhanced video stream handler with improved error handling and validation"""
    if request.method == 'POST':
        try:
            frame_data = request.data
            if not frame_data:
                raise ValueError("No frame data received")

            # Detect occupancy
            occupancy_data = bus_tracker.detect_occupancy(frame_data)

            # Store in database
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO video_frames (
                        frame, occupancy_count, confidence,
                        detection_method, frame_quality, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    frame_data,
                    occupancy_data.count,
                    occupancy_data.confidence,
                    occupancy_data.method,
                    1.0,  # placeholder for frame quality
                    occupancy_data.timestamp
                ))
                conn.commit()

            # Emit update via WebSocket
            socketio.emit('occupancy_update', {
                'count': occupancy_data.count,
                'confidence': occupancy_data.confidence,
                'timestamp': occupancy_data.timestamp
            })

            return jsonify({
                "status": "success",
                "occupancy": occupancy_data.count,
                "confidence": occupancy_data.confidence
            }), 200

        except Exception as e:
            logger.error(f"Error handling stream POST: {str(e)}")
            return jsonify({"error": str(e)}), 500

    else:  # GET request
        try:
            # Check if metadata is requested
            if request.args.get('metadata') == 'true':
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT occupancy_count, confidence, timestamp
                        FROM video_frames
                        ORDER BY id DESC
                        LIMIT 1
                    ''')
                    result = cursor.fetchone()
                    
                    if not result:
                        return jsonify({"error": "No data available"}), 404
                        
                    return jsonify({
                        "occupancy": result[0],
                        "confidence": result[1],
                        "timestamp": result[2]
                    }), 200
            
            # Return raw image data
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT frame
                    FROM video_frames
                    ORDER BY id DESC
                    LIMIT 1
                ''')
                result = cursor.fetchone()

                if not result:
                    return jsonify({"error": "No frame available"}), 404

                return Response(
                    result[0],
                    mimetype='image/jpeg',
                    headers={
                        'Cache-Control': 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0',
                        'Pragma': 'no-cache',
                    }
                )

        except Exception as e:
            logger.error(f"Error handling stream GET: {str(e)}")
            return jsonify({"error": str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """Enhanced system statistics endpoint"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get latest stats
            cursor.execute('''
                SELECT COUNT(*) FROM gps_data
            ''')
            total_gps_records = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT 
                    AVG(occupancy_count) as avg_occupancy,
                    MAX(occupancy_count) as max_occupancy,
                    AVG(confidence) as avg_confidence
                FROM video_frames
                WHERE timestamp >= datetime('now', '-1 hour')
            ''')
            occupancy_stats = cursor.fetchone()
            
            return jsonify({
                "total_gps_records": total_gps_records,
                "hourly_stats": {
                    "average_occupancy": round(occupancy_stats[0] or 0, 2),
                    "max_occupancy": int(occupancy_stats[1] or 0),
                    "detection_confidence": round(occupancy_stats[2] or 0, 2)
                }
            }), 200
            
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return jsonify({"error": str(e)}), 500

def background_task():
    """Background task for system monitoring"""
    while True:
        try:
            # Monitor system resources
            socketio.sleep(60)  # Check every minute
            
            # Implement system monitoring logic here
            # CPU, memory usage, etc.
            
        except Exception as e:
            logger.error(f"Background task error: {str(e)}")
            socketio.sleep(5)

@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    global thread
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(background_task)
    emit('connect', {'data': 'Connected'})

if __name__ == '__main__':
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()