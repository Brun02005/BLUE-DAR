# BLUE-DAR

Detector de auriculares y parlantes Bluetooth cercanos basado **solo en anuncios públicos** (BLE advertising y búsqueda Classic), con clasificación por evidencia y sin identificar personas.

Ninguna clasificación es una identificación: la app muestra qué **declara** cada anuncio (por ejemplo, "formato Proximity Pairing de AirPods Pro"), con qué regla, fuente y nivel de evidencia. Las reglas están marcadas como *no validadas en laboratorio* hasta que se ejecute el [plan experimental](docs/plan-experimental.md).

## Instalación (Windows, Python ≥ 3.11)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Uso

```powershell
.venv\Scripts\bluedar adapter                 # qué puede capturar este adaptador
.venv\Scripts\bluedar run                     # escaneo BLE + UI en http://127.0.0.1:8765
.venv\Scripts\bluedar run --classic           # + búsqueda Classic (equipos en modo emparejamiento)
.venv\Scripts\bluedar run --no-ui --duration 300
.venv\Scripts\bluedar stats  lab\sessions\<sesión>.jsonl   # tasas/huecos/RSSI por dirección (E1)
.venv\Scripts\bluedar replay lab\sessions\<sesión>.jsonl   # volver a ver una captura en la UI
.venv\Scripts\bluedar export lab\sessions\<sesión>.jsonl --format csv -o exports\sesion.csv
.venv\Scripts\python -m pytest
```

Cada `run` graba `lab/sessions/<fecha_hora>.jsonl` (un paquete por línea, direcciones pseudonimizadas y nombres descartados) y un `.meta.json`. Usá `--keep-names` solo en sesiones de laboratorio con dispositivos propios.

## Ubicación en un plano (solo dispositivos propios)

Con un solo receptor no hay posición, solo intensidad. Para ubicar dispositivos en un plano hacen falta ≥3 receptores en lugares conocidos, y **solo se ubican entidades con LAB-ID**.

```powershell
copy lab\room.example.yaml lab\room.yaml        # medí y anotá la posición de cada receptor
.venv\Scripts\bluedar simulate --room lab\room.yaml   # precisión esperada ANTES de comprar nada
.venv\Scripts\bluedar demo --room lab\room.yaml       # ver el plano con datos simulados

# real: hub en esta PC + receptores remotos
.venv\Scripts\bluedar run --room lab\room.yaml --lan
.venv\Scripts\bluedar node --hub http://<IP-del-hub>:8765 --id notebook   # en otra PC
```

Los receptores pueden ser otras PCs (`bluedar node`) o placas ESP32 (`firmware/`, sin probar). Para calibrar, asigná un LAB-ID a un dispositivo propio, ponelo a 1 m medido de cada receptor y apretá **Calibrar** en el panel de detalle.

### Búsqueda con un solo receptor (mapa de calor)

Si tenés **una sola** notebook, no hay posición en un plano (eso necesita 3 receptores), pero sí podés hacer una búsqueda tipo "más caliente / más frío": seleccioná en la tabla el dispositivo a buscar, caminá con la notebook y en el panel **Búsqueda: mapa de calor** hacé clic en el plano donde estás parado en cada paso. El mapa pinta más oscura la zona donde la señal es más fuerte; el círculo marca el punto más fuerte que marcaste. Es más fuerte = más cerca, no metros.

Límites: necesita que el dispositivo siga emitiendo (estuche con batería); si es un Find My que rota su firma (~15 min), al rotar hay que volver a seleccionarlo y empezar de nuevo; y marca una señal, no confirma de quién es.

## Interfaz

- Un **mapa de señal** en tiempo real con tu PC en el centro. La distancia al centro es la intensidad de señal, no metros. El ángulo solo agrupa por clasificación (un cuadrante por tipo) y **no indica dirección**. Cada punto lleva una barra radial con la dispersión del RSSI.
- Un **plano** (si se pasa `--room`) con los receptores y la posición estimada de los dispositivos propios, con un círculo de incertidumbre y los rangos por receptor del dispositivo seleccionado.
- Una tabla en tiempo real con clasificación, base (*declarado* / *hipótesis*), confianza, familia o modelo declarado, categoría de señal, **distancia aproximada** (como intervalo, nunca un número solo), tendencia y paquetes. Se puede filtrar y ordenar.
- **Distancia en metros**: se muestra como un intervalo (ej. "≈ 2–16 m") porque el RSSI → metros depende del dispositivo y de las paredes. Sin calibrar, el intervalo es ancho; calibrando el dispositivo a 1 m se angosta. A través de paredes (casas vecinas) el número es muy incierto y se marca como tal: ahí manda la atenuación, no la distancia.
- Un gráfico de RSSI suavizado. Por defecto muestra las 3 señales más fuertes; se pueden marcar hasta 5 filas.
- Un panel de detalle con las reglas que dispararon, su fuente y sus falsos positivos conocidos, más un campo para asignar un LAB-ID a dispositivos propios.
- Alertas de posible BLE spam y de las limitaciones del adaptador. Exportación CSV/JSON.

## Documentación

- [Informe técnico de viabilidad y diseño](docs/informe-tecnico.md)
- [Plan experimental y formato de captura](docs/plan-experimental.md)
- Reglas y tablas de modelos: [`src/bluedar/rules/`](src/bluedar/rules/)
