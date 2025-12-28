#include <ESP8266WiFi.h>
#include <WebSocketsServer.h>
#include <Servo.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

const char* ssid = "Dass_Picsoul";
const char* password = "0987654321";

WebSocketsServer webSocket(81);

Servo servo1;   
Servo servo2;   

String currentMode = "IDLE";
String playerPos = "CENTER";
int angle1 = 90;
int angle2 = 90;

// ------------------------ NORMAL DASHBOARD (unchanged) ------------------------
void updateMainScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);

  display.setCursor(0, 0);
  display.printf("Mode: %s", currentMode.c_str());

  display.setCursor(0, 15);
  display.printf("Player: %s", playerPos.c_str());

  display.setCursor(0, 30);
  display.printf("Direction: %d", angle1);

  display.setCursor(0, 45);
  display.printf("Angle: %d", angle2);

  display.display();
}

// ------------------------ BOOT SEQUENCE ------------------------
void showBootSequence() {

  // Wait until WiFi connects
  while (WiFi.status() != WL_CONNECTED) {
    display.clearDisplay();
    display.setCursor(0, 10);
    display.setTextSize(1);
    display.setTextColor(WHITE);
    display.println("WiFi Connecting...");
    display.display();
    delay(500);
  }

  // WiFi connected screen
  display.clearDisplay();
  display.setCursor(0, 10);
  display.println("WiFi Connected!");
  display.display();
  delay(2000);

  // Show IP for 5 seconds
  display.clearDisplay();
  display.setCursor(0, 10);
  display.printf("IP: %s", WiFi.localIP().toString().c_str());
  display.display();
  delay(5000);

  // Load main UI (same as your old one)
  updateMainScreen();
}

// ------------------------ WEBSOCKET HANDLING ------------------------
void onWebSocketEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t len) {

  if (type == WStype_TEXT) {
    String msg = String((char*)payload);

    // Servo 2
    if (msg.startsWith("S2:")) {
      angle2 = msg.substring(3).toInt();
      servo2.write(angle2);
      updateMainScreen();
      return;
    }

    // Player Position
    if (msg.startsWith("POS:")) {
      playerPos = msg.substring(4);
      updateMainScreen();
      return;
    }

    // Mode Update
    if (msg.startsWith("MODE:")) {
      currentMode = msg.substring(5);
      currentMode.toUpperCase();
      updateMainScreen();
      return;
    }

    // Servo 1 (numbers only)
    bool isNumber = true;
    for (int i = 0; i < msg.length(); i++) {
      if (!isdigit(msg[i])) isNumber = false;
    }

    if (isNumber) {
      angle1 = msg.toInt();
      servo1.write(angle1);
      updateMainScreen();
      return;
    }
  }
}

// ------------------------ SETUP ------------------------
void setup() {
  Serial.begin(115200);

  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);

  servo1.attach(2);   // D4
  servo2.attach(14);  // D5

  servo1.write(90);
  servo2.write(90);

  WiFi.begin(ssid, password);

  // Show boot sequence (this waits until WiFi connects)
  showBootSequence();

  webSocket.begin();
  webSocket.onEvent(onWebSocketEvent);
}

// ------------------------ LOOP ------------------------
void loop() {
  webSocket.loop();
}
