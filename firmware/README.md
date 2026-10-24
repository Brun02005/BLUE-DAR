# Receptor ESP32 para BLUE-DAR

> **Estado: sin compilar ni probar.** Está escrito contra NimBLE-Arduino 1.4.x y el core Arduino-ESP32. La versión 2.x de NimBLE cambió la API de callbacks y `getPayload()`. El protocolo con el hub sí está probado, usando `bluedar node` como receptor.

## Antes de comprar

Corré `bluedar simulate --room lab/room.yaml` con tu habitación real. Si con el ruido que mediste en E4 la estimación no le gana claramente a "decir siempre el centro", sumar receptores no va a aportar.

Para probar sin comprar nada podés usar otra PC o notebook con Bluetooth como receptor:

```powershell
.venv\Scripts\bluedar node --hub http://<IP-del-hub>:8765 --id notebook
```

## Qué hace

- Escanea BLE con un ciclo de escucha de ~50 % (Windows usa ~15 %).
- Pseudonimiza cada dirección con la clave de sesión del hub (HMAC-SHA256), así el mismo dispositivo tiene el mismo pseudónimo en todos los receptores. **La dirección real nunca sale de la placa.**
- Redacta los nombres locales y la dirección BR/EDR de Swift Pair.
- Envía lotes cada 500 ms. La hora la pone el hub al recibir, así no hace falta NTP.

## Uso

1. Instalá en Arduino IDE el core **esp32** (Espressif) y la biblioteca **NimBLE-Arduino 1.4.x**.
2. Editá en `esp32_node.ino` las constantes `WIFI_SSID`, `WIFI_PASS`, `HUB` y `NODE_ID`.
3. Agregá el receptor a `lab/room.yaml` con su posición medida en metros.
4. En la PC hub ejecutá `bluedar run --room lab/room.yaml --lan` y permití el puerto 8765 en el firewall de Windows.
5. Flasheá la placa y mirá el monitor serie (115200): tiene que decir "Registrado en el hub".
6. Calibrá cada receptor desde la UI: con un dispositivo propio con LAB-ID a 1 m medido del receptor, apretá **Calibrar**.

## Limitaciones conocidas

- NimBLE 1.4 junta el anuncio y la scan response en un solo payload, así que el campo `pdu` refleja el tipo del anuncio.
- El ESP32 comparte la radio entre Wi-Fi y BLE: el ciclo de escucha real será menor al configurado.
- El HTTP va sin TLS dentro de la red local. Los datos viajan pseudonimizados, pero la clave de sesión también viaja en claro al registrarse.
