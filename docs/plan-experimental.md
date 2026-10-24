# BLUE-DAR — Plan experimental

Objetivo: reemplazar las hipótesis del informe técnico por mediciones propias **antes** de escribir el clasificador. Nada de lo que figura acá como "hipótesis" es un resultado. Los resultados se cargan en la tabla de §7 recién después de ejecutar los experimentos.

## 1. Principios

1. **Verdad de campo solo sobre dispositivos propios.** Los dispositivos ajenos que aparecen en una captura son ruido de fondo. No se los etiqueta, no se los investiga y no entran en las métricas de precisión/recall (sí en el conteo de "detecciones sin verdad de campo").
2. **Separación desarrollo / validación.** Las sesiones se asignan al azar (antes de mirarlas) a `dev` o `val`. Las reglas se escriben mirando solo `dev`, y las métricas de aceptación se calculan solo sobre `val`.
3. **Preregistro.** Antes de cada experimento se escriben en el manifiesto la hipótesis, la métrica y el criterio de "confirmada / refutada". No se cambia el criterio después de ver los datos.
4. **Repeticiones.** Mínimo 3 repeticiones por condición, en al menos 2 días distintos y con el orden de las condiciones aleatorizado. Un resultado visto una sola vez se reporta como "observado una vez", no como comportamiento.
5. **No generalizar desde una unidad.** "Los AirPods Pro hacen X" significa "esta unidad, con este firmware, hizo X". Se registran el firmware y el modelo.
6. **Reportar negativos.** Si un estado no produce anuncios, eso es un resultado válido y va a la tabla.

## 2. Inventario de prueba

[LOCAL] En esta PC ya figuran emparejados: unos AirPods Pro, un iPhone y varios dispositivos de audio de otras marcas (auriculares y parlantes). Antes de usarlos:

- Confirmar el tipo real (auricular / parlante) y modelo de cada uno, y asignarles un ID de laboratorio (`LAB-A01`, `LAB-S01`, …) en `lab/manifests/devices.yaml`.
- **Ojo:** estar emparejados con la PC que escanea puede cambiar su comportamiento (reconexión automática a la PC). Para cada experimento, documentar si la PC tiene Bluetooth emparejado con el dispositivo, y preferir desconectarlos desde Windows (o quitar el emparejamiento) cuando se quiera observar el comportamiento "como dispositivo ajeno".
- Dispositivos de control **no-audio** propios (iPhone, otra PC, reloj, mouse/teclado BT si hay): sirven para medir falsos positivos con verdad de campo.

## 3. Formato de almacenamiento

```
lab/
  manifests/
    devices.yaml                 # LAB-ID → tipo real, marca, modelo, firmware, notas
    2026-10-25_E2_r1.json        # manifiesto de sesión
  sessions/
    2026-10-25_E2_r1.jsonl       # observaciones crudas (gitignored)
```

**Manifiesto de sesión** (JSON):

```json
{
  "session_id": "2026-10-25_E2_r1",
  "experiment": "E2",
  "split": "dev",
  "hypotheses": ["H1", "H2"],
  "platform": {"os": "Windows 11 26200", "backend": "bleak x.y.z", "scanning_mode": "active",
               "adapter": "Realtek VID_0BDA PID_B85C, driver 1.10.1061.3019"},
  "environment": {"place": "habitación A", "notes": "Wi-Fi 2.4 GHz activo, 1 persona"},
  "devices_present": [{"lab_id": "LAB-A01", "paired_with_scanner": false, "address_hint": null}],
  "events": [
    {"t_offset_s": 0,   "lab_id": "LAB-A01", "state": "estuche_cerrado"},
    {"t_offset_s": 180, "lab_id": "LAB-A01", "state": "tapa_abierta"}
  ],
  "preregistered_criterion": "H2 se refuta si aparece ≥1 mensaje 0x07 de LAB-A01 con tapa cerrada en ≥2 de 3 repeticiones"
}
```

**Observación cruda: formato JSONL v1** (una línea por paquete BLE o por respuesta de inquiry Classic; lo escribe `bluedar run`):

```json
{"v":1,"t":"2026-10-24T17:15:36.703Z","tr":"le","addr":"2f1cf0e0a380","kind":"nrpa","rssi":-68,
 "pdu":"adv_nonconn_ind","be":"bleak-winrt","conn":false,"scan":false,"dir":false,
 "ad":[[1,"1a"],[255,"4c000719010e20..."],[9,null,14]],"has_name":true,"hint":"auricular:airpods"}
```

| Campo | Significado |
|---|---|
| `t` | Marca de tiempo del evento de WinRT (UTC) |
| `tr` | `le` o `bredr` |
| `addr` | Pseudónimo de sesión: HMAC con una clave que se descarta al terminar. Nunca es la dirección real |
| `kind` | `public`, `random_static`, `rpa`, `nrpa` o `unknown`. Se calcula antes de pseudonimizar |
| `pdu` | `adv_ind`, `adv_scan_ind`, `adv_nonconn_ind`, `scan_rsp`, `extended` o `inquiry` |
| `ad` | Estructuras AD **de ese paquete** (sin fusionar adv + scan_rsp) como `[tipo, hex]`. Las redactadas van como `[tipo, null, longitud]` |
| `hint` | Categoría del nombre local (el texto se descarta, salvo `--keep-names`) |
| `cod` | Class of Device (Classic) |
| `syn` | `true` si las estructuras AD se reconstruyeron desde Bleak (plataformas que no son Windows) |

Cada captura tiene al lado un `<sesión>.meta.json` con el adaptador, el modo de escaneo y las etiquetas LAB-ID asignadas desde la UI.

Para asociar una dirección con un `LAB-ID` durante el experimento se usa el modo laboratorio: el operador marca la entidad en la UI/CLI cuando la identifica (por ejemplo, porque aparece y desaparece al abrir y cerrar la tapa), y esa asignación queda en el manifiesto, nunca automáticamente.

## 4. Experimentos

Duración base por condición: 3 min (ajustar con E1 si los intervalos de anuncio son largos). Cada experimento abre con una **línea de base** de 3 min con todos los dispositivos propios de audio apagados.

### E1 — Capacidad de captura de la plataforma
- Condiciones: un dispositivo propio que anuncie de forma constante (por ejemplo, un auricular en modo emparejamiento) a 1 m. Escaneo activo vs. pasivo. Dispositivo emparejado vs. no emparejado con la PC.
- Medir: anuncios/s recibidos por dirección, huecos máximos entre paquetes, presencia de scan response, fuente del nombre.
- Decide: pregunta abierta 1 (¿Windows filtra?) y el valor de `T_ausencia`.

### E2 — AirPods por estado
- Estados (orden aleatorio): estuche cerrado · tapa abierta · fuera del estuche en la mesa · puestos sin audio · puestos reproduciendo desde el iPhone · iPhone con Bluetooth apagado (separados del dueño) · modo emparejamiento (botón del estuche).
- Medir: presencia y tasa de `0x004C/0x07` y `0x12`. Valor del campo modelo. Variación de los bytes de estado. Rotación de dirección (cuánto dura cada dirección).
- Hipótesis: H1–H4.

### E3 — Auriculares y parlantes de otras marcas
- Estados: apagado · encendido sin conectar · modo emparejamiento · conectado a un teléfono reproduciendo · conectado sin audio.
- Medir: si anuncian BLE en cada estado y qué campos traen (Appearance, Fast Pair, Swift Pair, manufacturer data, nombre). Con el backend Classic (fase 6), si responden a inquiry y con qué CoD.
- Hipótesis: H5–H6.

### E4 — RSSI vs. distancia, orientación y obstáculos
- Por cada dispositivo de audio: 0,5 / 1 / 2 / 4 / 8 m en línea de vista; 2 m con una pared; 2 m con una persona en el medio; 4 orientaciones a 1 m; auricular puesto vs. en la mesa a la misma distancia.
- Medir: distribución del RSSI (mediana, IQR, p5–p95) por condición, solapamiento entre distancias.
- Decide: umbrales de categorías y si alguna estimación de distancia es defendible. Hipótesis: H7.

### E5 — Falsos positivos y validación del clasificador
- Sesiones `val` con mezcla conocida de dispositivos propios (audio y no-audio) en distintos estados, ejecutadas **después** de congelar las reglas.
- Medir las métricas de §5.
- Hipótesis: H8.

## 5. Métricas

Por dispositivo propio, estado y ventana de evaluación (por ejemplo, 30 s):

- **Detección (A):** fracción de ventanas en que se recibió ≥1 anuncio del dispositivo.
- **Latencia de primera detección:** tiempo desde el cambio de estado hasta el primer anuncio.
- **Verdadero positivo:** dispositivo propio de audio etiquetado "posible auricular/parlante" con el tipo correcto.
- **Falso negativo:** dispositivo propio de audio presente y emitiendo, pero etiquetado "desconocido" o "insuficiente", o no detectado. Se separan "no emite" (límite físico) y "emite pero no se clasificó" (límite del algoritmo).
- **Falso positivo:** dispositivo propio **no-audio** etiquetado como audio, o audio con tipo equivocado (auricular↔parlante).
- **Precisión y recall por regla** (no solo globales), con intervalo de confianza de Wilson, porque las muestras serán chicas.
- **Detecciones sin verdad de campo:** conteo de entidades ajenas etiquetadas como audio. Se reporta como contexto y no entra en la precisión.

## 6. Cómo evitar conclusiones prematuras

- No cambiar reglas mirando sesiones `val`. Si hace falta, se crean nuevas sesiones `val` después del cambio.
- Ninguna hipótesis pasa a "confirmada" con menos de 3 repeticiones consistentes en 2 días.
- Si los resultados dependen de que el dispositivo esté emparejado con la PC, se reportan ambos casos por separado.
- Cualquier valor de tabla de modelos (`apple_models.yaml`, `fastpair_models.yaml`) lleva el `session_id` donde se observó, o una fuente publicada.

## 7. Hipótesis a verificar (estado inicial: todas pendientes)

| ID | Hipótesis | Origen | Estado |
|---|---|---|---|
| H1 | Los AirPods Pro emiten `0x004C/0x07` con tapa abierta | [RE] | pendiente |
| H2 | Con el estuche cerrado y cerca del iPhone del dueño, no emiten `0x07` | Comunidad / [RE] | pendiente |
| H3 | El campo modelo de `0x07` vale `0x0E20` para la unidad propia, coherente con el PnP `PID 0x200E` de Windows | [RE] + [LOCAL] | pendiente |
| H4 | Separados del iPhone (Bluetooth del teléfono apagado), al cabo de un tiempo emiten `0x12` Find My | [DOC] general | pendiente |
| H5 | Los auriculares/parlantes propios de otras marcas solo exponen campos de tipo (Appearance/CoD/Fast Pair Model ID) en modo emparejamiento | [DOC] Fast Pair/Swift Pair | pendiente |
| H6 | Al menos uno de los parlantes propios no emite nada por BLE cuando está conectado a un teléfono | Inferencia | pendiente |
| H7 | En línea de vista, las categorías fuerte/media/débil separan 0,5 m de 4 m para un mismo dispositivo con < 10 % de solapamiento | Inferencia | pendiente |
| H8 | Ningún dispositivo propio no-audio es clasificado como audio por las reglas congeladas | Diseño | pendiente |
| H9 | En el payload Find My de "separado" (`0x12`, longitud `0x19`), `status & 0x18 == 0x18` para AirPods propios y `0x10` para un AirTag | [RE] AirGuard | pendiente. [LOCAL] 2026-10-24: en 3 capturas solo hubo payloads cortos ("cerca del dueño", primer byte `0x00`), ninguno de separado |
