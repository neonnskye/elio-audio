#include <Arduino.h>
#include <WiFiManager.h>

#define ledPin 2

WiFiManager wifiManager;
WiFiUDP wifiUDP;

void setup()
{
  Serial.begin(115200);
  delay(1000);

  pinMode(ledPin, OUTPUT);

  // wifiManager.resetSettings(); // for debugging
  wifiManager.autoConnect("Amrith's NodeMCU-32S", "pacman@123");
}

void loop()
{
  digitalWrite(ledPin, HIGH);
  delay(1000);
  digitalWrite(ledPin, LOW);
  delay(1000);
}