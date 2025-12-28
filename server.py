
from flask import Flask, render_template, Response, jsonify, request
import cv2
import mediapipe as mp
import websocket
import time
import random
import threading
import queue
import json
import collections
import math
import pyttsx3
import sys
import os

app = Flask(__name__, template_folder="templates", static_folder="static")

# --------------------------
# CONFIG
# --------------------------
ESP_IP = "ws://10.85.62.203:81"   # set your ESP websocket address
CAMERA_INDEX = 1
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
CENTER_TOLERANCE = 70

# --------------------------
# GLOBAL STATE
# --------------------------
tracking_enabled = False
current_mode = "simulation"
mode_start = time.time()

# angle sets
ANGLE_SETS = [
    [180, 0, 90, 45, 70, 110],
    [0, 90, 45, 0, 180, 10],
    [90, 45, 180, 0, 50],
    [45, 180, 0, 90, 20, 160],
    [70, 180, 0, 30, 120, 45],
    [53, 160, 33, 10]
]

# servo runtime
s1_angle = 0
s1_dir = 1
last_s1_move = time.time()
last_seq_step = time.time()

# player tracking
player_last_pos = None
frames_no_player = 0
PLAYER_MISSING_THRESHOLD = 30

# analytics
reaction_times = []
hip_history = collections.deque(maxlen=240)

# SSE queue
event_q = queue.Queue(maxsize=1000)

# websocket to ESP
ws = None

# --------------------------
# Connect to ESP WebSocket
# --------------------------
def connect_ws():
    global ws
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(ESP_IP, timeout=5)
            print("Connected to ESP WebSocket:", ESP_IP)
            return
        except Exception as e:
            print("ESP WS connect failed:", e)
            time.sleep(1)

threading.Thread(target=connect_ws, daemon=True).start()

# --------------------------
# Mediapipe + Camera init
# --------------------------
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6)
camera = cv2.VideoCapture(CAMERA_INDEX)
camera.set(3, FRAME_WIDTH)
camera.set(4, FRAME_HEIGHT)
try:
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
except:
    pass

# --------------------------
# Voice (fresh engine per speak) - V2 mixed coaching+funny
# --------------------------
voice_enabled = True
last_voice_event = None
last_voice_time = 0
VOICE_GAP = 2.5

LEFT_LINES = [
    "Nice move to the left! Keep them guessing.",
    "Great left court coverage — smooth and clever.",
    "You shifted left — that was slick!",
    "Good balance on the left side, well timed!",
    "Left side taken — smart move, keep it up!",
    "You’re owning the left court today!",
    "Left side defense looking sharp!",
    "Fantastic leftward agility!",
]

RIGHT_LINES = [
    "Strong move to the right — very sharp!",
    "Right court defended perfectly, nice!",
    "Great reaction shifting right — impressive!",
    "You moved right, stay quick on your feet!",
    "Right side locked down nicely — let's go!"
    "You’re dominating the right court!",
    "Right side coverage is on point!",
    "Excellent rightward speed and control!",
]

CENTER_LINES = [
    "Back to center — perfect recovery, champion!",
    "Center position is strong — keep that stance!",
    "Great movement back to the middle — excellent!",
    "Balanced in center — that's how winners stand!",
    "Center regained — stay ready for the smash!",
    "You’re holding the center court like a pro!",
    "Center court control is impressive!",
    "Fantastic center positioning — well done!",

]

NOTFOUND_LINES = [
    "Hey, where did you go? Come into view!",
    "I lost you — step back into the frame please.",
    "Player missing — don't hide from training!",
    "Can't see you — reposition for the camera.",
    "Move into the camera frame so I can coach you!",
    "I'm here to help, but I can't see you!",
    "Don't be a ghost — show yourself to the camera!",
    "Reappear on camera — let's get back to training!",
]

def speak(text):
    if not voice_enabled:
        return
    def run_speech():
        try:
            en = pyttsx3.init()
            en.setProperty('rate', 180)
            # prefer female-like voices if available
            try:
                for v in en.getProperty('voices'):
                    name = getattr(v, 'name', '').lower()
                    if "female" in name or "zira" in name or "samantha" in name:
                        en.setProperty('voice', v.id)
                        break
            except:
                pass
            en.say(text)
            en.runAndWait()
            try:
                en.stop()
            except:
                pass
            del en
        except Exception as e:
            print("TTS error:", e, file=sys.stderr)
    threading.Thread(target=run_speech, daemon=True).start()

def handle_voice_event(event_name):
    global last_voice_event, last_voice_time
    now = time.time()
    if event_name == last_voice_event and now - last_voice_time < VOICE_GAP:
        return
    last_voice_event = event_name
    last_voice_time = now
    if event_name == "LEFT":
        speak(random.choice(LEFT_LINES))
    elif event_name == "RIGHT":
        speak(random.choice(RIGHT_LINES))
    elif event_name == "CENTER":
        speak(random.choice(CENTER_LINES))
    elif event_name == "NOTFOUND":
        speak(random.choice(NOTFOUND_LINES))

# --------------------------
# SSE events
# --------------------------
def push_event(event_type, data):
    try:
        payload = {"type": event_type, "data": data, "ts": time.time()}
        event_q.put_nowait(json.dumps(payload))
    except Exception:
        pass

@app.route("/events")
def events():
    def stream():
        while True:
            data = event_q.get()
            yield f"data: {data}\\n\\n"
    return Response(stream(), mimetype="text/event-stream")

# --------------------------
# Routes
# --------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start-system")
def start_system():
    global tracking_enabled, current_mode, mode_start
    global frames_no_player, player_last_pos
    mode = request.args.get("mode", "simulation").lower()
    current_mode = mode
    mode_start = time.time()
    frames_no_player = 0
    player_last_pos = None
    try:
        if ws:
            ws.send(f"MODE:{current_mode.upper()}")
    except:
        threading.Thread(target=connect_ws, daemon=True).start()
    push_event("MODE", current_mode.upper())
    speak(f"{current_mode} mode activated")
    tracking_enabled = True
    return jsonify({"status": "started", "mode": current_mode})

@app.route("/stop-system")
def stop_system():
    global tracking_enabled
    tracking_enabled = False
    push_event("MODE", "STOPPED")
    speak("System stopped")
    return jsonify({"status": "stopped"})

@app.route("/voice-toggle", methods=["POST"])
def voice_toggle():
    global voice_enabled
    voice_enabled = not voice_enabled
    push_event("VOICE", {"enabled": voice_enabled})
    return jsonify({"voice_enabled": voice_enabled})

# Custom endpoints for UI buttons
@app.route("/custom/s1")
def custom_s1():
    angle = int(request.args.get("angle", 90))
    try:
        if ws:
            ws.send(str(angle))
    except:
        threading.Thread(target=connect_ws, daemon=True).start()
    push_event("CUSTOM_S1", angle)
    if angle == 180:
        handle_voice_event("LEFT")
    elif angle == 0:
        handle_voice_event("RIGHT")
    else:
        handle_voice_event("CENTER")
    return jsonify({"ok": True, "s1": angle})

@app.route("/custom/s2")
def custom_s2():
    angle = int(request.args.get("angle", 90))
    try:
        if ws:
            ws.send(f"S2:{angle}")
    except:
        threading.Thread(target=connect_ws, daemon=True).start()
    push_event("CUSTOM_S2", angle)
    mapping = {160: "Drop shot activated.", 20: "Toss initiated.", 0: "Clear set.", 180: "Smash activated."}
    speak(mapping.get(angle, f"Shot set to {angle} degrees"))
    return jsonify({"ok": True, "s2": angle})

# --------------------------
# Generate frames (camera always-on)
# --------------------------
def generate_frames():
    global player_last_pos, frames_no_player
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
    while True:
        success, frame = camera.read()
        if not success:
            time.sleep(0.01)
            continue
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = pose.process(rgb)
        pos = player_last_pos or "UNKNOWN"
        detected = False
        if result.pose_landmarks:
            detected = True
            hip = result.pose_landmarks.landmark[mp_pose.PoseLandmark.RIGHT_HIP].x
            hip_x = int(hip * w)
            if hip_x < (w//2 - CENTER_TOLERANCE):
                pos = "LEFT"
            elif hip_x > (w//2 + CENTER_TOLERANCE):
                pos = "RIGHT"
            else:
                pos = "CENTER"
            if pos != player_last_pos:
                push_event("POS", pos)
                handle_voice_event(pos)
                player_last_pos = pos
            frames_no_player = 0
        else:
            frames_no_player += 1
            if frames_no_player >= PLAYER_MISSING_THRESHOLD:
                push_event("NO_PLAYER", "Player not detected")
                handle_voice_event("NOTFOUND")
                frames_no_player = 0
                player_last_pos = None
        if player_last_pos:
            cv2.putText(frame, f"Pos: {player_last_pos}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)
        ret, buf = cv2.imencode('.jpg', frame, encode_params)
        if not ret:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" +
            buf.tobytes() +
            b"\r\n"
        )


@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --------------------------
# Background servo & modes
# --------------------------
def background_servo_loop():
    global s1_angle, s1_dir, last_s1_move, last_seq_step
    while True:
        if not tracking_enabled:
            time.sleep(0.02)
            continue
        now = time.time()
        if current_mode == "beginner":
    # Servo 1 sweeping slowly (unchanged)
            if now - last_s1_move > 0.08:
                s1_angle += s1_dir * 3
                if s1_angle >= 180: s1_dir = -1
                if s1_angle <= 0: s1_dir = 1
                try:
                    if ws:
                        ws.send(str(int(s1_angle)))
                except:
                    threading.Thread(target=connect_ws, daemon=True).start()
                last_s1_move = now

            # Servo 2 random shot from ANGLE_SETS every 2.5s
            if now - last_seq_step > 2.5:
                try:
                    if ws:
                        random_angle = random.choice(random.choice(ANGLE_SETS))
                        ws.send(f"S2:{random_angle}")
                except:
                    threading.Thread(target=connect_ws, daemon=True).start()
                last_seq_step = now

        elif current_mode in ("intermediate", "pro"):
    # Servo 1 movement (UNCHANGED)
            if now - last_s1_move > (0.06 if current_mode == "intermediate" else 0.045):
                s1_angle += s1_dir * (4 if current_mode == "intermediate" else 5)
                if s1_angle >= 180: s1_dir = -1
                if s1_angle <= 0: s1_dir = 1
                try:
                    if ws:
                        ws.send(str(int(s1_angle)))
                except:
                    threading.Thread(target=connect_ws, daemon=True).start()
                last_s1_move = now

            # ---- Updated Delays ----
            delay = 2.0 if current_mode == "intermediate" else 1.5

            if now - last_seq_step > delay:

                if current_mode == "intermediate":
                    # ONE random shot every 2.0s
                    try:
                        if ws:
                            angle = random.choice(random.choice(ANGLE_SETS))
                            ws.send(f"S2:{angle}")
                    except:
                        threading.Thread(target=connect_ws, daemon=True).start()

                else:  # PRO MODE
                    # Full random sequence every 1.5s
                    seq = random.choice(ANGLE_SETS)
                    for val in seq:
                        try:
                            if ws:
                                ws.send(f"S2:{val}")
                        except:
                            threading.Thread(target=connect_ws, daemon=True).start()
                        time.sleep(0.15)

                last_seq_step = now

        elif current_mode in ("random","random_mode"):
            if now - last_seq_step > 2:
                seq1 = random.choice(ANGLE_SETS)
                seq2 = random.choice(ANGLE_SETS)
                v1 = random.choice(seq1)
                v2 = random.choice(seq2)
                try:
                    if ws:
                        ws.send(str(v1))
                        ws.send(f"S2:{v2}")
                except:
                    threading.Thread(target=connect_ws, daemon=True).start()
                last_seq_step = now
        elif current_mode == "simulation":

    # --- SERVO 1 CONTROL BASED ON PLAYER POSITION ---
                if player_last_pos == "RIGHT":
                    angle_s1 = random.randint(0, 90)

                elif player_last_pos == "LEFT":
                    angle_s1 = random.randint(90, 180)

                elif player_last_pos == "CENTER":
                    angle_s1 = random.randint(0, 180)

                else:
                    # Player not visible → do nothing
                    time.sleep(0.05)
                    continue

                # Send Servo 1 angle
                try:
                    if ws:
                        ws.send(str(angle_s1))
                except:
                    threading.Thread(target=connect_ws, daemon=True).start()

                # --- SERVO 2 CONTROL EVERY 2 SECONDS ---
                if time.time() - last_seq_step > 2:
                    try:
                        if ws:
                            random_angle_s2 = random.choice(random.choice(ANGLE_SETS))
                            ws.send(f"S2:{random_angle_s2}")
                    except:
                        threading.Thread(target=connect_ws, daemon=True).start()

                    last_seq_step = time.time()

                time.sleep(0.2)  # smooth update timing

        elif current_mode == "custom":
            pass
        time.sleep(0.01)

threading.Thread(target=background_servo_loop, daemon=True).start()

# --------------------------
# Run server
# --------------------------\

if __name__ == "__main__":
    print("Starting server at http://0.0.0.0:5000")
    push_event("MSG", "Server starting")
    speak("System ready")
    app.run(host="0.0.0.0", port=5000, debug=True)
