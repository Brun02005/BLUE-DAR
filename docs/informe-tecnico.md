# BLUE-DAR — Informe técnico de viabilidad y diseño

Detector de auriculares y parlantes Bluetooth cercanos.
Fecha: 2026-10-24 · Estado: investigación previa a la implementación (no hay código de producto).

Convención usada en todo el documento:

- **[DOC]**: afirmación respaldada por documentación oficial (Bluetooth SIG, Apple, Google, Microsoft, Android, BlueZ).
- **[RE]**: respaldada por ingeniería inversa publicada (papers académicos, repositorios de investigación). No es una especificación oficial y puede cambiar con actualizaciones de firmware.
- **[LOCAL]**: dato medido en esta PC durante la investigación.
- **[VERIFICAR]**: hipótesis plausible que todavía hay que comprobar en el laboratorio (ver `plan-experimental.md`). No usarla como hecho.

---

## 0. Resumen ejecutivo

1. **Lo que se puede observar sin conectarse ni emparejarse** son los anuncios BLE (advertising) y, solo cuando el equipo está en modo emparejamiento ("discoverable"), las respuestas a una búsqueda Classic (inquiry). Todo lo demás (audio, enlaces Classic ya establecidos) no es observable con hardware convencional y además queda fuera del alcance ético del proyecto.
2. **AirPods / Beats**: emiten un mensaje Apple Continuity de tipo `0x07` ("Proximity Pairing") dentro de los datos de fabricante de Apple (`0x004C`). Ese mensaje lleva en claro un **modelo declarado** de 2 bytes (por ejemplo `0x0E20` = AirPods Pro) [RE]. Es la mejor evidencia disponible, pero **no es inequívoca**: el formato no es oficial y cualquier dispositivo puede emitir ese mismo paquete (existen herramientas públicas de "BLE spam" que lo falsifican). Además, solo se emite en ciertos estados [VERIFICAR qué estados].
3. **Auriculares y parlantes de otras marcas**: la detección depende del fabricante. Hay campos estándar que **declaran** el tipo (Appearance BLE, Class of Device Classic, Swift Pair con CoD, servicios LE Audio), pero en general aparecen sobre todo en modo emparejamiento. Fuera de ese modo, muchos equipos no anuncian nada o anuncian datos opacos. Un parlante solo Classic, conectado a un teléfono, es **invisible** para este proyecto.
4. **RSSI** solo sirve para categorías relativas ("fuerte / media / débil") de un mismo dispositivo y adaptador. No sirve para clasificar y no equivale a metros sin calibración.
5. **Plataforma recomendada para el MVP: Windows + Python + Bleak**, que es la máquina actual. Hay que validarla primero con una fase 0 de captura. **Linux + BlueZ** queda como plataforma de investigación si Windows resulta insuficiente. **Android** queda para una fase posterior.
6. **No hace falta comprar hardware para empezar.** El adaptador actual cubre anuncios BLE legacy y búsqueda Classic. Lo único que probablemente no cubre son los anuncios extendidos (LE Audio/Auracast) [LOCAL]. Recién si los experimentos muestran que eso importa se evalúa un nRF52840 con nRF Sniffer.

---

## 1. Informe de viabilidad: cómo se anuncian estos dispositivos

### 1.1 Bluetooth Classic vs BLE para descubrir dispositivos de audio

| Aspecto | Bluetooth Classic (BR/EDR) | Bluetooth Low Energy (BLE) |
|---|---|---|
| Uso en audio | Transporte del audio tradicional (A2DP, HFP, AVRCP) | Descubrimiento rápido, apps compañeras, batería, Find My, Fast Pair. LE Audio usa BLE también para el audio |
| Cómo se descubre | *Inquiry*: el escáner pregunta y solo responden los equipos en *inquiry scan* (modo descubrible) [DOC] | Escucha pasiva/activa de anuncios en los canales 37/38/39 (legacy) o canales secundarios (extendidos) [DOC] |
| Qué se obtiene sin conectar | Dirección BD_ADDR, **Class of Device** (CoD), RSSI, y si hay EIR: nombre y UUIDs de perfiles (A2DP Sink `0x110B`, HFP `0x111E`, etc.) [DOC] | Dirección (normalmente aleatoria), tipo de PDU (conectable/escaneable), RSSI, y estructuras AD: nombre, UUIDs, *service data*, *manufacturer data*, Appearance, TX Power [DOC] |
| ¿Visible estando conectado a un teléfono? | Normalmente **no**: un equipo conectado no suele estar en modo descubrible [VERIFICAR por modelo] | **A veces**: muchos dispositivos siguen anunciando por BLE mientras transmiten audio por Classic (los AirPods emiten Proximity Pairing en algunos estados) [VERIFICAR] |
| Privacidad de la dirección | BD_ADDR fija (pública) | Suele usar direcciones privadas resolubles (RPA) que rotan [DOC] |

**Conclusión:** para "detectar auriculares cercanos en uso" la vía realista es BLE. La búsqueda Classic aporta evidencia fuerte (CoD) pero solo de equipos en modo emparejamiento.

### 1.2 Campos observables en un anuncio BLE sin conectarse

Estructuras AD (Assigned Numbers, Bluetooth SIG) relevantes [DOC]:

| AD type | Campo | Valor para el detector |
|---|---|---|
| `0x01` | Flags | Indica LE-only vs. dual-mode (BR/EDR soportado). Pista débil |
| `0x02`–`0x07` | Listas de UUID de servicio | Fuerte si aparecen UUIDs de audio (LE Audio). La mayoría de los auriculares no lista UUIDs útiles |
| `0x08` / `0x09` | Nombre local (corto/completo) | Pista heurística. Suele ir en la *scan response*, por lo que requiere escaneo activo. Es texto libre que define el fabricante o el usuario |
| `0x0A` | TX Power Level | Mejora la estimación de pérdida de trayecto. Pocos dispositivos lo incluyen |
| `0x0D` | Class of Device | Raro en anuncios BLE. Si está, es evidencia fuerte de tipo |
| `0x16` | Service Data (UUID16) | Ej.: Fast Pair `0xFE2C` |
| `0x19` | Appearance | **Declaración estándar de tipo** (ver 1.6) |
| `0xFF` | Manufacturer Specific Data | Company ID de 2 bytes + datos propietarios (Apple Continuity, Swift Pair, Samsung, etc.) |

Metadatos de la recepción (no son contenido del anuncio): RSSI, marca de tiempo, tipo de dirección (pública/aleatoria), si es conectable o escaneable, si es legacy o extendido. Qué metadatos expone cada SO varía (ver §3).

**Identificadores de fabricante:** el Company ID solo dice quién registró el formato del bloque, no qué tipo de producto es. `0x004C` (Apple) aparece en iPhones, Macs, relojes, AirTags y AirPods. `0x0006` (Microsoft) aparece en PCs, mouses y teclados. Solo un Company ID nunca alcanza para decir "auricular".

### 1.3 Ecosistema Apple

Todos los mensajes van en `0xFF` con Company ID `0x004C`, como una secuencia TLV de mensajes "Continuity" (tipo, longitud, valor) [RE: Martin et al. 2019; Celosia & Cunche 2020; repositorio furiousMAC/continuity].

**Mensaje `0x07` Proximity Pairing** (AirPods, AirPods Pro/Max, Beats), según el repositorio furiousMAC [RE]:

| Byte(s) | Campo | Nota |
|---|---|---|
| 1 | Tipo = `0x07` | |
| 1 | Longitud | |
| 1 | Prefijo (`0x01` observado) | |
| 2 | **Modelo del dispositivo** | Único valor documentado ahí: `0x0E20` = AirPods Pro |
| 1 | Estado (posición en oreja/estuche) | ej. `0x55` = "ambos en el estuche" |
| 1 | Batería izq./der. (nibbles, ×10 %) | Se observaron valores > 100 % |
| 1 | Carga + batería del estuche | Disposición de bits no documentada con precisión |
| 1 | Contador de apertura de tapa | Significado incierto |
| 1 | Color | ej. `0x00` = blanco. Cambia en Beats |
| 1 | Indefinido (`0x00`) | |
| 16 | **Payload cifrado** | No se intenta descifrar (fuera de alcance) |

Implicancias para el diseño:

- El **modelo declarado** es lo más cercano a una identificación de modelo que existe sin conectarse. La tabla modelo→nombre se construye **solo** con fuentes citadas o con capturas propias. [LOCAL] Los AirPods Pro emparejados con esta PC se registran en Windows con PnP `VID 0x004C / PID 0x200E`. Eso coincide con `0x0E20` leído en el otro orden de bytes. Es una coincidencia consistente, pero hay que confirmarla capturando el anuncio [VERIFICAR].
- **No es inequívoco.** Desde 2023 circulan herramientas (firmware de Flipper Zero, scripts para ESP32 tipo "AppleJuice") que emiten Proximity Pairing falsos para provocar ventanas emergentes en iPhones. El paquete no está autenticado ni para nosotros ni para nadie sin las claves del dueño. El detector debe decir "anuncio con formato de AirPods Pro", no "AirPods Pro".
- **Cuándo se emite:** la literatura y la comunidad lo asocian a la tapa abierta y a los auriculares fuera del estuche o en uso. No encontramos una fuente oficial con los estados exactos [VERIFICAR, experimentos E2/E3].

**Mensaje `0x12` Offline Finding (Find My)** [DOC: Apple Platform Security; RE: Heinrich et al. 2021]:

- Lo emite un dispositivo separado de su dueño o sin conexión. Transmite una clave pública derivada que **rota aproximadamente cada 15 minutos** [DOC].
- Lo emiten iPhones, AirTags, AirPods con Find My y accesorios de terceros compatibles. **No permite saber el tipo de dispositivo.** Clasificación correcta: "dispositivo Find My, tipo no determinable".
- No se intenta vincular claves entre rotaciones. Sería exactamente el tipo de rastreo que el proyecto excluye.

**Otros mensajes Continuity** (Nearby Info `0x10`, Handoff `0x0C`, AirDrop `0x05`, Nearby Action `0x0F`, etc.) los emiten iPhones, iPads, Macs y relojes [RE]. Sirven para **descartar** audio, no para confirmarlo. Un `0x004C` sin `0x07` no es evidencia de auricular.

### 1.4 Google Fast Pair (Android y muchos auriculares de terceros) [DOC]

- Service Data con UUID `0xFE2C`.
- **En modo emparejamiento:** incluye un **Model ID de 24 bits** y la dirección BLE no rota durante ese modo. Se anuncia a ≤100 ms.
- **Fuera de ese modo:** incluye solo "Account Data", es decir un filtro Bloom de claves de cuenta con *salt*. **No hay Model ID.** El *salt* se regenera al rotar la dirección para impedir el rastreo. Se anuncia a ≤250 ms.
- Inferencia de diseño: `0xFE2C` presente significa "dispositivo compatible con Fast Pair". La gran mayoría son de audio, pero hay excepciones. Solo con Model ID **y** una tabla de modelos verificada se puede hablar de modelo. El registro de Model IDs de Google no es una base pública descargable, así que la tabla se arma con dispositivos propios.

### 1.5 Microsoft Swift Pair [DOC]

- `0xFF` con Company ID `0x0006`, *beacon* Swift Pair y subescenario: `0x00` = solo LE, `0x01` = BR/EDR descubierto vía LE, `0x02` = LE + BR/EDR con Secure Connections.
- **Solo en modo emparejamiento**, y se retira ≥30 s antes de salir de ese modo.
- Los payloads de modo dual **incluyen el Class of Device de 3 bytes**, y los LE-only pueden usar Appearance. Por eso un anuncio Swift Pair con CoD Audio/Video → Headphones es **evidencia declarada de tipo**.
- Es útil para auriculares Microsoft, Logitech, Jabra y otros, pero solo durante el emparejamiento.

### 1.6 Declaraciones estándar de tipo (las más confiables)

**Appearance BLE (AD `0x19`)** [DOC Assigned Numbers. Valores confirmados vía tablas derivadas; revisar el PDF oficial antes de codificarlos]:

- Categoría *Audio Sink* `0x0840`–: `0x0841` parlante independiente, otros: soundbar, etc.
- Categoría *Wearable Audio Device* `0x0940`–: `0x0940` genérico, `0x0941` earbud, `0x0945` earbud izquierdo, además de headset y headphones.

**Class of Device (Classic, o dentro de Swift Pair)** [DOC Assigned Numbers, Baseband]: Major class `0x04` = Audio/Video, con minors como *Wearable Headset*, *Hands-free*, *Loudspeaker*, *Headphones*, *Portable Audio*, *Car audio*, *HiFi Audio*. Los valores exactos de los minors se toman de la tabla oficial al implementar.

**LE Audio / Auracast**: UUIDs de servicio PACS `0x1850`, ASCS `0x184E`, BASS `0x184F`, Broadcast Audio Announcement `0x1852`, Public Broadcast Announcement `0x1856` [DOC; verificar contra Assigned Numbers]. Los broadcasts Auracast usan **anuncios extendidos + periódicos**, que el adaptador de esta PC probablemente no recibe (§4).

Ninguna declaración está autenticada: un dispositivo puede declarar cualquier cosa. Pero son **declaraciones verificables contra la especificación**, que es la evidencia más alta posible sin conectarse.

### 1.7 Identificadores que cambian, faltan o son ambiguos

| Identificador | Comportamiento | Consecuencia |
|---|---|---|
| Dirección BLE | Muchas veces es una RPA que rota. El valor típico del temporizador es de 15 min; Find My rota ~15 min [DOC] | Un mismo dispositivo aparece como varios. El conteo de "dispositivos" sobreestima |
| Nombre local | A menudo ausente. Apple no pone nombre en sus anuncios Continuity. Puede estar solo en la scan response | Sin escaneo activo no se ve. Es texto libre y no es confiable |
| Nombre vía caché del SO | Windows/BlueZ pueden asociar el nombre de un dispositivo **ya emparejado** | Hay que registrar la **fuente del nombre** (anuncio vs. caché). Si no, se confunde con un dato observado |
| Fast Pair salt / Account filter | Cambia con la rotación de dirección [DOC] | No sirve como identificador estable (es intencional) |
| Contadores Apple / batería | Cambian. Investigaciones los usaron para rastrear [RE] | **No se usan para vincular** direcciones |
| Company ID | Estable, pero compartido por todo el catálogo del fabricante | Pista débil de tipo |

### 1.8 Limitaciones por estado del dispositivo

| Estado | AirPods (esperado) | Auriculares/parlantes de otras marcas | Fuente |
|---|---|---|---|
| Apagado / sin batería | Nada | Nada | Trivial |
| En estuche cerrado, cerca del dueño | Probablemente sin `0x07` | Varía | [VERIFICAR E2] |
| En estuche cerrado, lejos del dueño | Posible `0x12` Find My (tipo indeterminable) | Varía (algunos con Find My Device de Google) | [DOC general / VERIFICAR] |
| Tapa abierta | `0x07` frecuente | n/a | [RE / VERIFICAR E2] |
| En uso, conectados a un teléfono | Posible `0x07` intermitente | Muchos siguen anunciando BLE con datos opacos. Los solo-Classic, nada | [VERIFICAR E3] |
| Modo emparejamiento | `0x07` + Classic descubrible | Fast Pair con Model ID, Swift Pair, Classic con CoD: **mejor caso** | [DOC] |
| Radio inactiva / ahorro de energía | Intervalos largos, posible ausencia | Ídem | [VERIFICAR] |

---

## 2. Qué significa "detectar" (objetivos A–E)

| Objetivo | Viable | Datos necesarios | Confianza alcanzable |
|---|---|---|---|
| **A.** Hay una transmisión BT cercana | Sí, para BLE siempre que haya anuncios. Classic solo si es descubrible | Cualquier anuncio + RSSI + hora | Alta (el paquete existe). No dice qué es |
| **B.** Un anuncio que **podría** ser de audio | Sí, cuando hay campos con semántica de audio | Appearance, CoD, UUIDs LE Audio, Fast Pair, Apple `0x07`, nombre | Media: depende del campo (ver §5) |
| **C.** Clasificación probabilística de tipo/familia | Parcial | Reglas con evidencia + validación experimental | Ordinal (alta/media/baja) hasta medir precisión por regla. Recién entonces, porcentajes calibrados |
| **D.** Marca/modelo con evidencia suficiente | Solo en casos específicos: Apple `0x07` con modelo tabulado, Fast Pair Model ID tabulado, nombre de fabricante + coherencia | Tabla de modelos con fuente o captura propia | "Modelo **declarado** por el anuncio". Nunca "confirmado", porque no hay autenticación |
| **E.** Proximidad relativa por RSSI | Sí, como categoría relativa y tendencia (acercándose/alejándose) | Serie temporal de RSSI suavizada. TX Power si está | Baja en valor absoluto, aceptable en tendencias del mismo dispositivo. Ver §6 |

Reglas inviolables:

- RSSI **nunca** es una entrada de la clasificación (B–D).
- Un Company ID o un dato desconocido **nunca** produce "posible auricular" por sí solo.
- Si no hay campos con semántica de audio, el resultado es "dispositivo desconocido" o "clasificación insuficiente". No se adivina.

---

## 3. Plataformas: comparación (entregable 2)

| Capacidad | Windows + Python (Bleak/WinRT) | Linux + Python (BlueZ, Bleak o HCI crudo) | Android (API nativas) |
|---|---|---|---|
| Anuncios BLE legacy con manufacturer/service data | Sí (`BluetoothLEAdvertisementWatcher`) [DOC] | Sí | Sí (`BluetoothLeScanner`, `ScanRecord`) [DOC] |
| Escaneo activo (scan response, nombres) | Sí, por defecto en Bleak. Bleak combina las SCAN_RSP que Windows entrega por separado [DOC] | Sí | Sí |
| Escaneo pasivo | Sí (`scanning_mode="passive"`) | Sí. En Bleak requiere *advertisement monitor* de BlueZ con patrones | No configurable directamente |
| Cada paquete vs. deduplicado | El watcher entrega eventos por anuncio. La pérdida/filtrado real del driver queda [VERIFICAR E1] | D-Bus deduplica por defecto. `DuplicateData=true` lo desactiva [DOC]. HCI crudo (`btmon`/socket HCI, root) ve todo | Por callback. El SO/OEM puede agrupar resultados |
| Anuncios extendidos (BT5) | API desde Windows 10 2004 (`AllowExtendedAdvertisements`). Bleak lo activa [código fuente]. **Esta PC reporta `IsExtendedAdvertisingSupported = False`** [LOCAL] | Sí, si controlador + kernel lo soportan | Sí (API 26+, `setLegacy(false)`) si el chip lo soporta |
| Búsqueda Classic (CoD, nombre) | Sí vía WinRT `DeviceWatcher` (dispositivos no emparejados) + `BluetoothDevice.ClassOfDevice`. Control fino del inquiry: no [VERIFICAR alcance] | Sí: `SetDiscoveryFilter(Transport="bredr")` [DOC], HCI inquiry con RSSI | Sí: `startDiscovery()` con `BluetoothClass` y RSSI |
| Tipo de dirección / dirección | Dirección + tipo | Dirección + tipo | Dirección (puede estar enmascarada en ciertos modos) |
| Restricciones del SO | Hilo MTA para WinRT: conflicto con GUIs que inicializan STA (`allow_sta`/`uninitialize_sta` en Bleak) [DOC] | Permisos (root/`CAP_NET_RAW` para HCI). Caché de dispositivos de BlueZ | Permisos `BLUETOOTH_SCAN` (12+). **Con `neverForLocation` se filtran algunos beacons** [DOC]. Límite de ~5 `startScan` cada 30 s [fuente secundaria]. Escaneos sin filtro se detienen con pantalla apagada [AOSP] |
| Variabilidad de hardware | Según driver (Realtek, Intel, MediaTek, Qualcomm) | Según controlador. Mejor diagnóstico (`btmon`) | Muy alta entre OEM |
| Costo para empezar | **Cero: es la máquina actual** | Requiere una máquina Linux (PC con live USB o Raspberry Pi). WSL2 no expone Bluetooth por defecto | Requiere desarrollo en Kotlin y un teléfono Android |
| Rol recomendado | **MVP** | **Plataforma de investigación** de referencia si Windows filtra o pierde datos | **Fase posterior** (portabilidad) |

Bleak es una biblioteca multiplataforma (WinRT / BlueZ D-Bus / CoreBluetooth). Su ventaja es un mismo código de escaneo BLE en Windows y Linux. Su límite es que **no hace búsqueda Classic** y no expone el canal, el PHY ni el tipo de PDU de forma uniforme. Por eso la arquitectura separa los *backends* (§5).

---

## 4. Hardware mínimo requerido

**Mínimo para el MVP: el adaptador actual.** [LOCAL] Realtek Wireless Bluetooth Adapter (USB `VID_0BDA&PID_B85C`, driver 1.10.1061.3019), Windows 11 build 26200. WinRT reporta: LE sí, Classic sí, rol central sí, *advertisement offload* sí, **anuncios extendidos no**, longitud máxima de anuncio 31 bytes.

Qué cubre: anuncios BLE legacy (Apple Continuity, Fast Pair, Swift Pair, Appearance) y búsqueda Classic. Esto alcanza para todos los mecanismos de §1.3–1.6 **excepto** LE Audio/Auracast.

Mediciones preliminares con la herramienta ya implementada [LOCAL, 2026-10-24, capturas de 40–75 s en un ambiente con poco tráfico]:

- El controlador soporta PHY 2M y Coded (o sea, es Bluetooth 5), pero Windows igual informa que no hay anuncios extendidos.
- **Ciclo de escaneo de Windows:** `scan_interval` 189 y `scan_window` 29 (unidades de 0,625 ms), es decir 18 ms de escucha cada 118 ms, **≈15 % del tiempo**. Asignar `BluetoothLEAdvertisementScanParameters.low_latency()` devuelve los mismos valores: en este build y driver no hay forma de subirlo.
- **Consecuencia:** se recibe aproximadamente 1 de cada 6–7 anuncios. Se midieron 3–5 paquetes/s en total y ≤1,3 Hz por dirección; un iPhone con Nearby Info llegó a ~0,8 Hz. Para dispositivos que anuncian poco o en ráfagas cortas, la latencia de detección y los falsos negativos van a ser mayores que con un escáner dedicado. Esto ya responde en parte la pregunta 1 de §11.
- **Classic:** el `DeviceWatcher` de WinRT devolvió Class of Device y RSSI de equipos descubribles. Windows solo envía actualizaciones cuando cambia algo (por ejemplo, el RSSI), así que un equipo Classic quieto puede pasar a "ausente" aunque siga ahí. Su ausencia hay que leerla con más cautela que la de BLE.

Hardware adicional, **solo si un experimento demuestra que hace falta**:

| Hardware | Qué aporta | Qué **no** resuelve | Disparador para considerarlo |
|---|---|---|---|
| nRF52840 USB dongle + nRF Sniffer for Bluetooth LE + Wireshark | PDUs crudos de todos los tipos, canal 37/38/39, marcas de tiempo precisas, anuncios extendidos, independencia de filtros del SO | No resuelve RPAs (necesita IRK = emparejamiento). No descifra payloads. No ve Classic. No identifica dueños | E1 muestra pérdida de anuncios por el SO > umbral, o se necesita estudiar LE Audio |
| Segundo adaptador USB BT 5.x usado en Linux | Anuncios extendidos vía BlueZ, HCI crudo, comparación entre adaptadores | Lo mismo que arriba | Si se decide la plataforma Linux o se necesita extendido sin sniffer |
| Ubertooth One u otros sniffers Classic | Observación parcial de tráfico BR/EDR | **Excluido**: escuchar enlaces Classic ajenos excede la observación de anuncios y choca con §7 | No aplica |

---

## 5. Arquitectura recomendada

### 5.1 Vista general

```
 ┌──────────────── backends (adaptadores de captura) ────────────────┐
 │ BleakBackend (BLE, Win/Linux) │ WinClassicBackend (WinRT inquiry)  │
 │ BlueZHciBackend (futuro)      │ PcapImportBackend (nRF Sniffer)    │
 └───────────────┬────────────────────────────────────────────────────┘
                 │ RawObservation (normalizada, con metadatos de origen)
                 ▼
        ┌─────────────────┐   pseudonimización de dirección (HMAC con
        │ Ingesta/privacy │── clave de sesión en memoria) + allowlist
        └────────┬────────┘   de dispositivos propios (modo laboratorio)
                 ▼
   ┌───────────────────────────┐        ┌───────────────────────┐
   │ Decoders (puros, testeables)│──────▶│ Store: JSONL crudo +   │
   │ AD parser, Apple Continuity │        │ meta.json de sesión    │
   │ Fast Pair, Swift Pair,      │        └───────────────────────┘
   │ Appearance, CoD             │
   └────────┬───────────────────┘
            ▼
   ┌───────────────────────────┐   reglas como DATOS (YAML) con fuente,
   │ Classifier (reglas + evid.)│── nivel de evidencia y modos de FP
   └────────┬───────────────────┘
            ▼
   ┌───────────────────────────┐   entidades por sesión, aparición,
   │ Tracker de presencia      │── desaparición (timeout), deduplicación
   └────────┬───────────────────┘
            ▼
   ┌───────────────────────────┐
   │ Proximity (RSSI suavizado) │
   └────────┬───────────────────┘
            ▼
   ┌───────────────────────────┐
   │ API local + UI web         │  FastAPI + WebSocket en 127.0.0.1:
   │ tabla + gráfico RSSI       │  tabla filtrable/ordenable, gráfico,
   │ exportación CSV/JSON       │  detalle con "razones" de cada clase
   └───────────────────────────┘
```

### 5.2 Decisiones y justificación

- **Backends intercambiables** detrás de una interfaz `async` que emite `RawObservation`. Bleak no cubre Classic ni datos crudos. Así se puede agregar BlueZ/HCI o importar capturas del nRF Sniffer sin tocar el núcleo, y se pueden reproducir capturas guardadas (*replay*) para tests.
- **Decoders puros** (bytes → estructura) con tests a partir de *fixtures* reales capturados. Es donde más errores aparecerán.
- **Reglas de clasificación como datos** (YAML versionado). Cada regla cita su fuente y su nivel de evidencia. Se pueden auditar, medir por separado y portar a Android sin reescribir la lógica.
- **Un solo event loop asyncio** con Bleak + servidor web local. Evita el conflicto STA/MTA de COM que aparece al combinar Bleak con GUIs de escritorio en Windows [DOC Bleak]. Además la UI queda desacoplada del escaneo. Alternativa evaluada: PySide6 + qasync + pyqtgraph, más nativa pero con el problema de apartamentos COM. Otra: Textual (TUI), sin un buen gráfico en tiempo real.
- **Almacenamiento:** JSONL de observaciones crudas (append-only, fácil de reprocesar) + un `meta.json` por sesión (adaptador, modo de escaneo, etiquetas LAB-ID). La exportación CSV/JSON sale de ahí, reproduciendo la captura con las reglas vigentes. SQLite se descartó por ahora: no hay consultas que lo justifiquen. Si el análisis multi-sesión lo pide, se agrega como índice derivado de los JSONL.
- **Gestión de direcciones aleatorias:** la entidad básica es *(dirección pseudonimizada, sesión)*. Se deduplica por dirección dentro de la sesión. Una dirección que deja de verse por `T_ausencia` (inicialmente 30 s, a calibrar con los intervalos de anuncio medidos) se marca "dejó de aparecer". **No se vinculan direcciones rotadas** de dispositivos ajenos. La UI muestra el conteo como "direcciones observadas" e indica que puede sobreestimar. Para dispositivos propios en modo laboratorio, la verdad de campo se registra manualmente (§7 y plan experimental).

### 5.3 Estructura de módulos y carpetas (entregable 6, implementada)

```
BLUE-DAR/
├── README.md
├── pyproject.toml
├── docs/
│   ├── informe-tecnico.md          ← este documento
│   └── plan-experimental.md        ← incluye el formato de captura JSONL v1
├── src/bluedar/
│   ├── cli.py                      ← adapter · run · replay · stats · export
│   ├── pipeline.py                 ← Session: ingesta → privacidad → JSONL → decode → reglas → presencia
│   ├── capture/
│   │   ├── base.py                 ← Observation, AdStructure, interfaz Backend
│   │   ├── bleak_backend.py        ← BLE; en Windows lee cada paquete crudo de WinRT
│   │   ├── win_classic_backend.py  ← inquiry Classic vía DeviceWatcher (CoD + RSSI)
│   │   ├── replay_backend.py       ← reproduce un JSONL grabado
│   │   └── adapter_info.py         ← diagnóstico del adaptador
│   ├── privacy/pseudonym.py        ← HMAC de sesión, redacción de nombres y dirección Swift Pair
│   ├── decode/                     ← AD genérico, Apple Continuity, Fast Pair, Swift Pair, CoD/Appearance
│   ├── classify/
│   │   ├── rules_engine.py         ← carga YAML + detectores
│   │   └── evidence.py             ← acumulación por entidad, etiqueta, confianza, razones
│   ├── rules/                      ← DATOS: classification.yaml, apple_models.yaml, fastpair_models.yaml, company_ids.yaml
│   ├── track/presence.py           ← entidades, aparición/ausencia, historial RSSI
│   ├── proximity/rssi.py           ← mediana + EMA, categorías con histéresis, tendencia
│   ├── store/                      ← jsonl_log.py, export.py (CSV/JSON)
│   ├── analysis/stats.py           ← tasas, huecos y RSSI por dirección (E1)
│   └── app/                        ← server.py (FastAPI + WebSocket) y static/ (tabla + gráfico)
├── lab/
│   ├── sessions/                   ← capturas JSONL + meta.json (gitignored)
│   └── manifests/                  ← manifiestos de experimento y devices.yaml
└── tests/                          ← paquetes sintéticos según los formatos documentados
```

Las reglas viven dentro del paquete para que se instalen con él. Siguen siendo datos versionados y editables.

---

## 6. Algoritmo de clasificación y sus limitaciones (entregable 5)

### 6.1 Modelo de evidencia

Cada observación agregada (una dirección dentro de una sesión) acumula **evidencias**. Cada evidencia tiene:

- `rule_id`, `claim` (p. ej. `type=earbuds`, `vendor_format=apple_proximity_pairing`, `model_declared=0x0E20`).
- `level`, de mayor a menor:
  1. **DECLARADO-ESTÁNDAR**: un campo definido por el Bluetooth SIG declara el tipo (Appearance audio, CoD Audio/Video, UUIDs LE Audio de unicast/broadcast). Verificable contra la especificación. No autenticado.
  2. **DECLARADO-FABRICANTE-DOC**: formato de fabricante con documentación oficial (Swift Pair con CoD, Fast Pair Model ID con tabla propia verificada).
  3. **DECLARADO-FABRICANTE-RE**: formato documentado por ingeniería inversa (Apple `0x07`).
  4. **HEURÍSTICO**: nombre local con patrones ("Buds", "Headphones", "Speaker", marcas de audio), Company ID de fabricante de audio sin otro dato, `0xFE2C` sin Model ID.
- `source` (referencia a §10), `known_false_positives` (texto), `observed_count` (en cuántos paquetes apareció).

Además, cada regla puede tener el atributo **VALIDADA-EN-LAB**, con precisión y recall medidos (plan experimental) y la fecha y la versión de la medición. Recién con esto se puede mostrar un porcentaje.

### 6.2 Decisión de etiqueta

```
si hay evidencia de tipo "auricular" o "parlante":
    si hay evidencias de tipos audio contradictorias (auricular vs parlante)
       o evidencia de tipo NO audio (p. ej. Apple Nearby Info de un iPhone) en la misma dirección:
        → "clasificación insuficiente" (mostrar el conflicto)
    sino → "posible auricular" / "posible parlante"
          confianza = f(mejor nivel, consistencia en ≥ N paquetes, VALIDADA-EN-LAB)
sino si hay campos decodificables pero ninguno indica audio
       (o indican otra familia: Find My, Continuity de teléfono, beacon):
    → "dispositivo desconocido" (con familia si la hay: "dispositivo Find My", "dispositivo Apple no-audio")
sino (solo dirección + RSSI, < N paquetes, payload vacío u opaco):
    → "clasificación insuficiente"
```

Confianza **ordinal** inicial (a reemplazar por valores medidos):

| Mejor evidencia | Consistente en ≥3 paquetes | Confianza |
|---|---|---|
| DECLARADO-ESTÁNDAR o FABRICANTE-DOC | sí | alta |
| DECLARADO-FABRICANTE-RE | sí | media (alta solo si la regla está VALIDADA-EN-LAB) |
| Cualquier declarado | no | baja |
| HEURÍSTICO solo | — | baja |

Etiquetado en la UI: "**Declarado**: el anuncio contiene Appearance = Earbud (0x0941)" vs. "**Hipótesis**: el nombre contiene 'Buds'". Ninguna etiqueta dice "confirmado" ni "identificado". Esos términos se reservan para la verdad de campo de los dispositivos propios en el laboratorio.

### 6.3 Reglas iniciales (borrador para `rules/classification.yaml`)

| ID | Condición | Afirmación | Nivel | Falsos positivos conocidos |
|---|---|---|---|---|
| R-APP-07 | `0xFF`, CID `0x004C`, mensaje TLV tipo `0x07` con longitud esperada | Formato Proximity Pairing → posible auricular Apple/Beats. Modelo declarado si figura en `apple_models.yaml` | FABRICANTE-RE | Spoofing (BLE spam). Cambios de formato por firmware |
| R-APP-12 | CID `0x004C`, tipo `0x12` | Dispositivo Find My (tipo indeterminable) | FABRICANTE-RE + DOC | — (no afirma audio) |
| R-APP-NONAUDIO | CID `0x004C` con `0x10`/`0x0C`/`0x05`/`0x0F` | Dispositivo Apple no-audio (teléfono, Mac, etc.) | FABRICANTE-RE | Un mismo anuncio puede traer varios TLV. Revisar |
| R-FP-MODEL | Service data `0xFE2C` con 3 bytes de Model ID | Fast Pair en modo emparejamiento. Modelo si figura en la tabla verificada | FABRICANTE-DOC | Fast Pair no es exclusivo de audio |
| R-FP-ACCT | `0xFE2C` con Account Data | Dispositivo Fast Pair (tipo no declarado) | HEURÍSTICO (para audio) | Idem |
| R-SWP-COD | CID `0x0006`, beacon Swift Pair, CoD major Audio/Video | Tipo según minor del CoD | FABRICANTE-DOC | — |
| R-APPEAR | AD `0x19` en rango Wearable Audio / Audio Sink | Auricular / parlante según subcategoría | ESTÁNDAR | — |
| R-LEA | UUIDs PACS/ASCS/Broadcast Audio | Dispositivo LE Audio (sink/broadcast) | ESTÁNDAR | Un TV o transmisor Auracast también anuncia broadcast |
| R-COD | (Classic) CoD major Audio/Video | Tipo según minor | ESTÁNDAR | — |
| R-NAME | Nombre local que coincide con patrones | Pista de tipo/marca | HEURÍSTICO | Nombres editados por el usuario o genéricos |

Señales de posible spoofing (no cambian la clase, agregan una advertencia visible): muchas direcciones distintas emitiendo `0x07` con modelos variados en pocos segundos. Ráfagas de `0x07` con intervalos anómalos [umbrales a definir con E1/E3].

### 6.4 Limitaciones

- Nada está autenticado. Toda clase es "declarada" o "hipotética".
- Falsos negativos estructurales: dispositivos solo Classic y conectados; dispositivos que no anuncian BLE fuera del emparejamiento; anuncios extendidos en esta PC.
- Las tablas de modelos estarán incompletas por diseño (solo lo verificado).
- El conteo de dispositivos sobreestima por las direcciones rotativas.
- La precisión medida en un ambiente y con un adaptador no se transfiere automáticamente a otros.

---

## 7. Proximidad por RSSI

**Por qué no metros:** el modelo log-distancia `RSSI(d) = RSSI(1 m) − 10·n·log10(d)` tiene dos incógnitas que dependen del entorno y del dispositivo: `RSSI(1 m)`, que depende de la potencia TX del emisor, su antena y el offset de RSSI del adaptador receptor, y `n`, que va aproximadamente de 2 en espacio libre a 3–4 en interiores. Con errores de ±5–10 dB comunes en interiores, la distancia inferida puede variar un factor de 2–3 o más [a medir en E4].

Factores que alteran el RSSI sin cambiar la distancia:

- **Cuerpo humano**: el agua absorbe 2,4 GHz. Un auricular puesto o un parlante detrás de una persona pierde mucha señal.
- **Paredes y muebles**: atenuación y reflexiones.
- **Orientación** de antenas (emisor y receptor).
- **Multitrayecto/fading**: variaciones rápidas de varios dB entre paquetes consecutivos.
- **Canal de anuncio**: 37/38/39 son frecuencias distintas con RSSI distinto. Windows no informa el canal.
- **Interferencia Wi-Fi** en 2,4 GHz y coexistencia en el mismo chip combo.
- **Cambios de potencia TX del emisor** según su estado (modo emparejamiento, ahorro de energía).
- **Diferencias entre adaptadores** receptores: el mismo emisor da valores distintos en otro equipo.

Diseño:

1. Filtro por entidad: mediana móvil (ventana ~5 s) + EMA. Se muestran el valor suavizado y la dispersión (p. ej. rango intercuartílico) para que se vea la incertidumbre.
2. Categorías relativas con **histéresis** (para que no oscilen): «fuerte», «media», «débil». Umbrales iniciales **provisionales** de −60 / −75 dBm, a recalibrar con E4 para este adaptador. La UI aclara: "categoría de señal, no distancia".
3. Si el anuncio trae TX Power (`0x0A`), se muestra también la pérdida de trayecto `TX − RSSI`, que compara mejor entre dispositivos.
4. Tendencia: pendiente del RSSI suavizado en los últimos N segundos → "acercándose / estable / alejándose", solo si supera la dispersión.
5. **Mapa de señal (radar).** El radio es el RSSI suavizado. El ángulo es el cuadrante de la clasificación, más una posición estable derivada del pseudónimo. Con un solo receptor no hay información de dirección, así que el mapa no puede mostrar posiciones. Un mapa con posiciones reales requiere ≥3 receptores en ubicaciones conocidas (trilateración, precisión de nivel habitación en interiores) o *direction finding* BT 5.1 (AoA, con arreglo de antenas). Por §8, solo se consideraría para dispositivos propios con LAB-ID.
6. Modo calibración opcional, solo para dispositivos propios: medir a 0,5/1/2/4 m en un entorno dado y ajustar un intervalo de distancia **con margen de error explícito**, válido solo para ese par dispositivo-adaptador y ese entorno.

---

## 7b. Ubicación con varios receptores (implementada, 2026-10-24)

**Alcance:** solo entidades con LAB-ID (dispositivos propios). El resto no se posiciona, ni siquiera internamente (§8).

**Arquitectura:**
- La PC donde corre `bluedar run --room … --lan` es el hub y el receptor `local`.
- Otros receptores se registran en el hub: otra PC con `bluedar node`, o un ESP32 con `firmware/esp32_node`, sin probar. Cada uno recibe la clave de sesión y pseudonimiza en origen, así un mismo dispositivo tiene el mismo pseudónimo en todos los receptores y la dirección real no viaja. [LOCAL] Verificado con dos procesos receptores en esta PC: 6 entidades, no 12.
- La hora de cada paquete remoto la pone el hub al recibirlo. Así se evitan desfasajes de reloj, a cambio de un error de ≤0,5 s (el intervalo de envío).
- Cada receptor tiene su propio filtro de RSSI por entidad. Un receptor aporta un rango solo si escuchó a la entidad en los últimos 10 s.

**Algoritmo:**
- Modelo log-distancia por receptor (`ref_dbm` a 1 m y exponente `n`), con σ del RSSI = max(4 dB, IQR/1,35). σ_d = d·ln10/(10n)·σ_RSSI, así que el error en metros crece con la distancia.
- Mínimos cuadrados no lineales ponderados (Gauss-Newton amortiguado), limitados a la habitación. Radio informado = √traza((JᵀWJ)⁻¹)·√max(1, χ²/gl).
- Con <3 receptores o receptores alineados no se devuelve posición.
- La calibración de un punto fija `ref_dbm` con un dispositivo propio a distancia medida. `n` sigue siendo un supuesto.

**Precisión esperada (`bluedar simulate`, MODELO, no medición):** habitación de 5×4 m con 3 receptores, sombreado gaussiano independiente y 500 posiciones al azar.

| σ RSSI | error p50 | error p90 | "decir el centro" p50 / p90 |
|---|---|---|---|
| 2 dB | 0,49 m | 1,09 m | 1,84 / 2,60 m |
| 4 dB | 0,90 m | 1,88 m | 1,84 / 2,60 m |
| 6 dB | 1,26 m | 2,81 m | 1,84 / 2,60 m |
| 8 dB | 1,49 m | 3,35 m | 1,84 / 2,60 m |

Interpretación:
- Con el ruido típico de interiores (6–8 dB) la mediana mejora poco sobre la línea de base trivial, y el **p90 es peor** que decir siempre el centro.
- El modelo es optimista: en la realidad el sombreado está correlacionado entre receptores y no es gaussiano.
- El radio informado resultó conservador: cubre el error real en el 83–96 % de los casos.
- **Antes de sumar receptores** hay que medir el σ real de esta habitación (experimento E4) y repetir la simulación con ese valor.

## 8. Privacidad y límites (requisitos de diseño)

- **Solo observación pasiva de anuncios y respuestas de búsqueda públicas.** Sin conexiones GATT a dispositivos ajenos, sin emparejamiento, sin intentos de descifrar payloads, sin sniffing de enlaces, sin evasión de autenticación.
- **Pseudonimización por defecto:** las direcciones se reemplazan por `HMAC(clave_de_sesión, dirección)` truncado. La clave vive en memoria y se descarta al cerrar la sesión, así que entre sesiones no se puede correlacionar a nadie. Las exportaciones usan los pseudónimos.
- **Excepción controlada (modo laboratorio):** el usuario registra explícitamente sus **dispositivos propios** (allowlist). Solo para ellos se guarda un identificador estable en el manifiesto del experimento.
- **Sin vinculación entre rotaciones** de dirección, ni uso de contadores, batería o claves Find My para seguir dispositivos ajenos. La investigación publicada muestra que es posible, y por eso se evita explícitamente.
- **Minimización:** los nombres locales de dispositivos ajenos pueden contener nombres de personas (p. ej. "AirPods de …"). Por defecto se guarda solo la categoría del patrón detectado, no el texto. Hay una opción explícita para guardarlo en sesiones de laboratorio.
- **Retención:** las sesiones crudas se borran automáticamente después de N días (configurable) salvo que se marquen como experimento.
- **Sin funciones de "seguir este dispositivo"** para entidades que no estén en la allowlist.

---

## 9. MVP por fases y criterios de aceptación (entregable 8)

> **Nota (2026-10-24):** se decidió implementar todo en una sola iteración en lugar de por fases. La tabla queda como **lista de verificación**: los criterios técnicos de F0, F1, F4(b) y F5 se cumplen con la implementación y los tests. Los que dependen de experimentos (F2(b), F3(b–c), F4(a, c)) siguen pendientes, y las reglas siguen marcadas como *no validadas en laboratorio*.

| Fase | Contenido | Criterios de aceptación |
|---|---|---|
| **F0 — Sonda de captura** | `bluedar scan --raw` con Bleak en Windows. Vuelca JSONL con todos los campos AD crudos (hex), RSSI, hora y tipo de dirección. Script de diagnóstico del adaptador (lo hecho en §4, automatizado) | (a) 10 min de captura sin caídas. (b) Aparece al menos un anuncio Apple `0x004C` de un dispositivo propio. (c) Se mide la tasa de paquetes/s por dirección y queda registrada. (d) Se documenta si Windows entrega anuncios de dispositivos ya emparejados y de dónde sale el nombre |
| **F1 — Datos y privacidad** | `RawObservation`, pseudonimización, JSONL + SQLite, *replay*, exportación CSV/JSON, tracker de presencia | (a) *Replay* de una captura de F0 reproduce exactamente el mismo resultado. (b) Ningún archivo exportado contiene direcciones reales fuera de la allowlist (test automatizado). (c) Aparición/desaparición con `T_ausencia` configurable, con tests |
| **F2 — Decoders + experimentos E1–E3** | Parsers AD, Apple Continuity, Fast Pair, Swift Pair, Appearance. Ejecutar E1–E3 del plan experimental | (a) Tests unitarios con fixtures **reales** de dispositivos propios. (b) Tabla de hipótesis H1–H8 actualizada con resultados medidos (confirmada / refutada / no concluyente) |
| **F3 — Clasificador** | Motor de reglas YAML, evidencias, confianza ordinal, advertencias de spoofing | (a) Toda clasificación muestra su regla, nivel y fuente. (b) En el set de **validación** (sesiones no usadas para escribir reglas): precisión de "posible auricular" ≥ 0,9 sobre dispositivos con verdad de campo, y 0 dispositivos propios no-audio etiquetados como audio. (c) Recall reportado por estado (puede ser bajo; se reporta, no se maquilla) |
| **F4 — Proximidad** | Filtro RSSI, categorías con histéresis, tendencia, calibración opcional | (a) Ejecutado E4. (b) Categorías estables (≤1 cambio/min en reposo). (c) Umbrales justificados con datos medidos |
| **F5 — UI** | Servidor local, tabla en tiempo real (filtro/orden por RSSI, clase, confianza), gráfico RSSI vs. tiempo, panel de "razones", exportación | (a) Latencia de actualización < 1 s. (b) Las clases "declarado" e "hipótesis" son visualmente distintas. (c) Ninguna fila muestra un modelo sin la palabra "declarado" y su fuente |
| **F6 (opcional)** | Classic en Windows (WinRT DeviceWatcher + CoD). Backend Linux/HCI. Evaluación de nRF Sniffer si E1 lo justifica. Android | Cada uno con su propio experimento de capacidad antes de integrarlo |

---

## 10. Documentación técnica utilizada (entregable 9)

Consultada durante esta investigación:

- Bluetooth SIG — *Assigned Numbers* (AD types, Appearance, Class of Device, Company IDs, UUIDs): https://www.bluetooth.com/specifications/assigned-numbers/ . Los valores de Appearance `0x0941` y `0x0841` se confirmaron vía https://docs.embassy.dev/trouble-host/ (tablas generadas desde Assigned Numbers). **Pendiente:** cotejar con el PDF oficial antes de codificar.
- Bluetooth Core Specification (GAP: descubrimiento, privacidad/RPA, advertising legacy y extendido).
- Google — Fast Pair, Provider advertising: https://developers.google.com/nearby/fast-pair/specifications/service/provider
- Microsoft — Swift Pair: https://learn.microsoft.com/en-us/windows-hardware/design/component-guidelines/bluetooth-swift-pair
- Microsoft — `BluetoothLEAdvertisementWatcher.AllowExtendedAdvertisements`: https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.advertisement.bluetoothleadvertisementwatcher.allowextendedadvertisements
- Apple — *Platform Security Guide*, Find My: https://support.apple.com/guide/security/find-my-security-sec6cbc80fd0/web
- Android — Bluetooth permissions: https://developer.android.com/develop/connectivity/bluetooth/bt-permissions
- AOSP — `BluetoothLeScanner` (comportamiento con pantalla apagada): https://code.yawk.at/android/android-9.0.0_r35/android/bluetooth/le/BluetoothLeScanner.java
- Punch Through — errores de escaneo BLE en Android (throttling, fuente secundaria): https://punchthrough.com/android-ble-scan-errors/
- BlueZ — `org.bluez.Adapter` (`SetDiscoveryFilter`, `DuplicateData`, `Transport`): https://github.com/bluez/bluez/blob/master/doc/org.bluez.Adapter.rst
- Bleak — backend Windows: https://bleak.readthedocs.io/en/latest/backends/windows.html ; código del scanner WinRT (activa `allow_extended_advertisements`): https://github.com/hbldh/bleak/blob/develop/bleak/backends/winrt/scanner.py
- furiousMAC — Apple Continuity, Proximity Pairing: https://github.com/furiousMAC/continuity/blob/master/messages/proximity_pairing.md
- Celosia, G. & Cunche, M. (2020). *Discontinued Privacy: Personal Data Leaks in Apple Bluetooth-Low-Energy Continuity Protocols*. PoPETs 2020(1): https://crysp.petsymposium.org/popets/2020/popets-2020-0003.php
- Martin, J. et al. (2019). *Handoff All Your Privacy – A Review of Apple's Bluetooth Low Energy Continuity Protocol*. PoPETs 2019(4).
- Heinrich, A. et al. (2021). *Who Can Find My Devices? Security and Privacy of Apple's Crowd-Sourced Bluetooth Location Tracking System*. PoPETs 2021(3).

Referencias de memoria técnica todavía **no re-verificadas** en esta sesión (verificar antes de usar en código): los valores de minor class de CoD para audio, los UUIDs exactos de LE Audio, la lista completa de tipos Continuity y el comportamiento de `startDiscovery()` en Android.

---

## 11. Preguntas pendientes que pueden cambiar la arquitectura (entregable 10)

1. **¿Windows entrega todos los anuncios o filtra y agrupa?** Si E1 muestra pérdidas grandes frente a la tasa esperada, la plataforma de investigación pasa a Linux/HCI o se usa un sniffer.
2. **¿Los anuncios extendidos importan para los dispositivos objetivo?** Esta PC no los soporta [LOCAL]. Si los auriculares propios usan LE Audio, hace falta otro adaptador.
3. **¿Qué emiten realmente los AirPods propios en cada estado?** Si en uso emiten `0x07` muy pocas veces, el objetivo "detectar AirPods en uso" tendrá recall bajo por naturaleza, y la UI debe comunicarlo.
4. **¿Los parlantes y auriculares de otras marcas que tenés anuncian algo por BLE fuera del modo emparejamiento?** Si no, el producto será básicamente un detector de "dispositivos de audio en modo emparejamiento + ecosistema Apple".
5. **¿Hace falta Classic?** Si la mayoría de los parlantes solo se ven en modo emparejamiento vía Classic, el backend WinRT Classic sube de prioridad.
6. **¿Uso fijo o móvil?** Si la herramienta debe usarse caminando, Android pasa a ser la plataforma principal, y las reglas YAML compartidas se vuelven críticas.
7. **¿Interfaz de escritorio nativa o web local?** La recomendación es web local por el problema STA/MTA. Si se exige una app nativa, hay que resolver el threading (proceso de escaneo separado).
8. **¿Se necesitan dispositivos de prueba adicionales** (otras marcas, Fast Pair) para que la clasificación tenga validez fuera de tu propio inventario?
9. **Retención y exportación:** ¿quién usará los CSV/JSON? Define si basta la pseudonimización por sesión o si hay que agregar datos (solo conteos).
