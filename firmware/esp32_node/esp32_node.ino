// BLUE-DAR · receptor ESP32
//
// ESTADO: escrito contra la API de NimBLE-Arduino 1.4.x y el core Arduino-ESP32,
// pero NO compilado ni probado en hardware. Ver firmware/README.md.
//
// Escanea anuncios BLE, pseudonimiza la dirección con la clave de sesión del hub
// (HMAC-SHA256, igual que bluedar/privacy/pseudonym.py), redacta nombres y envía
// lotes JSON a  POST {HUB}/api/nodes/{NODE_ID}/observations  cada 500 ms.
// La dirección real nunca sale de la placa. La hora la pone el hub al recibir.

#include <WiFi.h>
#include <HTTPClient.h>
#include <NimBLEDevice.h>
#include "mbedtls/md.h"

// ---------- configuración ----------
const char* WIFI_SSID = "TU_WIFI";
const char* WIFI_PASS = "TU_CLAVE";
const char* HUB = "http://192.168.0.10:8765";  // lo imprime `bluedar run --lan`
const char* NODE_ID = "esp32-a";               // debe existir en lab/room.yaml

// Ciclo de escaneo (unidades de 0,625 ms). 50 % de escucha; Windows usa ~15 %.
const uint16_t SCAN_INTERVAL = 100;
const uint16_t SCAN_WINDOW = 50;
const size_t MAX_BUFFER_BYTES = 24 * 1024;
const uint32_t SEND_EVERY_MS = 500;

// ---------- estado ----------
uint8_t sessionKey[32];
String token;
String buffer;          // registros JSON separados por coma
size_t buffered = 0;
uint32_t dropped = 0;
SemaphoreHandle_t bufferLock;

static String jsonField(const String& body, const char* name) {
  String key = String("\"") + name + "\":\"";
  int start = body.indexOf(key);
  if (start < 0) return "";
  start += key.length();
  int end = body.indexOf('"', start);
  return end < 0 ? "" : body.substring(start, end);
}

static bool registerWithHub() {
  HTTPClient http;
  http.begin(String(HUB) + "/api/nodes/register");
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(String("{\"node_id\":\"") + NODE_ID + "\"}");
  String body = http.getString();
  http.end();
  if (code != 200) {
    Serial.printf("Registro falló: HTTP %d %s\n", code, body.c_str());
    return false;
  }
  token = jsonField(body, "token");
  String keyHex = jsonField(body, "key");
  if (token.isEmpty() || keyHex.length() != 64) return false;
  for (int i = 0; i < 32; i++) {
    sessionKey[i] = (uint8_t)strtol(keyHex.substring(2 * i, 2 * i + 2).c_str(), nullptr, 16);
  }
  Serial.println("Registrado en el hub");
  return true;
}

// HMAC-SHA256(clave, "AA:BB:CC:DD:EE:FF")[:6] en hex: mismo pseudónimo que el hub.
static void pseudonym(const char* addrUpper, char out[13]) {
  uint8_t mac[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, sessionKey, sizeof(sessionKey));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)addrUpper, strlen(addrUpper));
  mbedtls_md_hmac_finish(&ctx, mac);
  mbedtls_md_free(&ctx);
  for (int i = 0; i < 6; i++) sprintf(out + 2 * i, "%02x", mac[i]);
  out[12] = '\0';
}

static const char* addressKind(uint8_t type, const char* addrUpper) {
  if (type == BLE_ADDR_PUBLIC) return "public";
  uint8_t top = (uint8_t)strtol(String(addrUpper).substring(0, 2).c_str(), nullptr, 16) >> 6;
  if (top == 0b11) return "random_static";
  if (top == 0b01) return "rpa";
  if (top == 0b00) return "nrpa";
  return "random";
}

static const char* pduName(uint8_t advType) {
  switch (advType) {
    case 0: return "adv_ind";
    case 1: case 4: return "adv_direct_ind";
    case 2: return "adv_scan_ind";
    case 3: return "adv_nonconn_ind";
    default: return "extended";
  }
}

// Estructuras AD como [[tipo,"hex"],...]; nombres como [tipo,null,longitud];
// en Swift Pair BR/EDR (CID 0x0006, beacon 0x03, escenario 0x01) se ponen en cero los 6 bytes de dirección.
static String adToJson(const uint8_t* p, size_t len, bool& hasName) {
  String out = "[";
  size_t i = 0;
  bool first = true;
  while (i < len) {
    uint8_t fieldLen = p[i];
    if (fieldLen == 0 || i + 1 + fieldLen > len) break;
    uint8_t type = p[i + 1];
    const uint8_t* data = p + i + 2;
    size_t dataLen = fieldLen - 1;
    if (!first) out += ",";
    first = false;
    if (type == 0x08 || type == 0x09) {
      hasName = true;
      out += "[" + String(type) + ",null," + String(dataLen) + "]";
    } else {
      bool swiftBredr = type == 0xFF && dataLen >= 11 && data[0] == 0x06 && data[1] == 0x00 && data[2] == 0x03 && data[3] == 0x01;
      out += "[" + String(type) + ",\"";
      char hx[3];
      for (size_t k = 0; k < dataLen; k++) {
        uint8_t b = (swiftBredr && k >= 5 && k < 11) ? 0 : data[k];
        sprintf(hx, "%02x", b);
        out += hx;
      }
      out += "\"]";
    }
    i += 1 + fieldLen;
  }
  return out + "]";
}

class ScanCallbacks : public NimBLEAdvertisedDeviceCallbacks {
  void onResult(NimBLEAdvertisedDevice* dev) override {
    if (token.isEmpty()) return;
    std::string addr = dev->getAddress().toString();
    for (auto& c : addr) c = toupper(c);
    char pseudo[13];
    pseudonym(addr.c_str(), pseudo);
    bool hasName = false;
    String ad = adToJson(dev->getPayload(), dev->getPayloadLength(), hasName);
    String rec = String("{\"tr\":\"le\",\"addr\":\"") + pseudo + "\",\"kind\":\"" +
                 addressKind(dev->getAddress().getType(), addr.c_str()) + "\",\"rssi\":" + String(dev->getRSSI()) +
                 ",\"pdu\":\"" + pduName(dev->getAdvType()) + "\",\"be\":\"esp32-nimble\",\"ad\":" + ad +
                 (hasName ? ",\"has_name\":true}" : "}");
    if (xSemaphoreTake(bufferLock, pdMS_TO_TICKS(5)) != pdTRUE) {
      dropped++;
      return;
    }
    if (buffer.length() + rec.length() > MAX_BUFFER_BYTES) {
      dropped++;
    } else {
      if (buffered) buffer += ",";
      buffer += rec;
      buffered++;
    }
    xSemaphoreGive(bufferLock);
  }
};

void setup() {
  Serial.begin(115200);
  bufferLock = xSemaphoreCreateMutex();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(250);
  Serial.printf("Wi-Fi OK: %s\n", WiFi.localIP().toString().c_str());
  while (!registerWithHub()) delay(3000);

  NimBLEDevice::init("");
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setAdvertisedDeviceCallbacks(new ScanCallbacks(), true);  // true = recibir duplicados
  scan->setActiveScan(true);
  scan->setInterval(SCAN_INTERVAL);
  scan->setWindow(SCAN_WINDOW);
  scan->setDuplicateFilter(false);
  scan->setMaxResults(0);  // no acumular resultados en memoria
  scan->start(0, nullptr, false);
}

void loop() {
  delay(SEND_EVERY_MS);
  String batch;
  size_t count = 0;
  if (xSemaphoreTake(bufferLock, pdMS_TO_TICKS(50)) == pdTRUE) {
    batch = buffer;
    count = buffered;
    buffer = "";
    buffered = 0;
    xSemaphoreGive(bufferLock);
  }
  if (!count) return;
  HTTPClient http;
  http.begin(String(HUB) + "/api/nodes/" + NODE_ID + "/observations");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " + token);
  int code = http.POST("{\"records\":[" + batch + "]}");
  http.end();
  if (code == 401) {
    token = "";
    registerWithHub();  // el hub se reinició: nueva sesión, nueva clave
  } else if (code != 200) {
    dropped += count;
    Serial.printf("Envío falló: HTTP %d (descartados: %u)\n", code, dropped);
  }
}
