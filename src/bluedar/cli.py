"""Línea de comandos de BLUE-DAR.

    bluedar adapter                      diagnóstico del adaptador
    bluedar run [--classic] [--no-ui]    escaneo en vivo (graba JSONL + UI web local)
    bluedar replay CAPTURA.jsonl         reproduce una captura en la UI
    bluedar stats CAPTURA.jsonl          tasas, huecos y RSSI por dirección (E1)
    bluedar export CAPTURA.jsonl         clasificación final de una captura a CSV/JSON
    bluedar node --hub URL --id NOMBRE   esta máquina como receptor adicional de un hub
    bluedar simulate --room room.yaml    precisión esperada de la ubicación (Monte Carlo)
    bluedar demo --room room.yaml        UI con receptores y dispositivos simulados
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .capture.adapter_info import adapter_info
from .capture.replay_backend import ReplayBackend
from .classify.rules_engine import load_default_ruleset
from .pipeline import Session
from .positioning.room import Room
from .privacy.pseudonym import Privacy
from .store.export import entities_to_csv, snapshot_to_json
from .store.jsonl_log import JsonlWriter, meta_path_for, write_meta

DEFAULT_OUT = Path("lab/sessions")
DEFAULT_PORT = 8765


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()  # antes de argparse: --help también imprime acentos
    parser = argparse.ArgumentParser(prog="bluedar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("adapter", help="diagnóstico del adaptador Bluetooth")

    run = sub.add_parser("run", help="escaneo en vivo")
    run.add_argument("--duration", type=float, help="segundos (por defecto: hasta Ctrl+C)")
    run.add_argument("--passive", action="store_true", help="escaneo pasivo (sin scan requests: no se ven scan responses ni nombres que vengan en ellas)")
    run.add_argument("--classic", action="store_true", help="también búsqueda Bluetooth Classic (solo equipos en modo emparejamiento)")
    run.add_argument("--keep-names", action="store_true", help="guardar nombres locales (solo sesiones de laboratorio con dispositivos propios)")
    run.add_argument("--no-record", action="store_true", help="no grabar la captura en disco")
    run.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"carpeta de capturas (por defecto {DEFAULT_OUT})")
    run.add_argument("--absence", type=float, default=30.0, help="segundos sin paquetes para marcar una entidad como ausente")
    run.add_argument("--no-ui", action="store_true", help="sin interfaz web: resumen periódico en consola")
    run.add_argument("--port", type=int, default=DEFAULT_PORT)
    run.add_argument("--room", type=Path, help="habitación y receptores (YAML) para ubicar dispositivos propios")
    run.add_argument("--lan", action="store_true", help="escuchar en la red local (necesario para receptores remotos)")

    node = sub.add_parser("node", help="usar esta máquina como receptor de un hub")
    node.add_argument("--hub", required=True, help="URL del hub, p. ej. http://192.168.0.10:8765")
    node.add_argument("--id", required=True, help="nombre del receptor; debe coincidir con room.yaml")
    node.add_argument("--passive", action="store_true")

    sim = sub.add_parser("simulate", help="precisión esperada de la ubicación con esta configuración")
    sim.add_argument("--room", type=Path, required=True)
    sim.add_argument("--trials", type=int, default=500)

    demo = sub.add_parser("demo", help="UI con receptores y dispositivos simulados (sin hardware)")
    demo.add_argument("--room", type=Path, required=True)
    demo.add_argument("--noise", type=float, default=5.0, help="σ del RSSI simulado en dB")
    demo.add_argument("--port", type=int, default=DEFAULT_PORT)

    rep = sub.add_parser("replay", help="reproduce una captura en la UI")
    rep.add_argument("file", type=Path)
    rep.add_argument("--speed", type=float, default=1.0, help="1 = tiempo real, 0 = sin esperas")
    rep.add_argument("--absence", type=float, default=30.0)
    rep.add_argument("--port", type=int, default=DEFAULT_PORT)

    st = sub.add_parser("stats", help="estadísticas de captura por dirección")
    st.add_argument("file", type=Path)
    st.add_argument("--top", type=int, default=30)
    st.add_argument("--json", action="store_true")

    ex = sub.add_parser("export", help="clasificación final de una captura")
    ex.add_argument("file", type=Path)
    ex.add_argument("--format", choices=("csv", "json"), default="csv")
    ex.add_argument("-o", "--output", type=Path, help="archivo de salida (por defecto stdout)")
    ex.add_argument("--absence", type=float, default=30.0)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _utf8_stdout()

    handlers = {
        "adapter": _cmd_adapter, "run": _cmd_run, "replay": _cmd_replay, "stats": _cmd_stats,
        "export": _cmd_export, "node": _cmd_node, "simulate": _cmd_simulate, "demo": _cmd_demo,
    }
    try:
        return handlers[args.cmd](args)
    except KeyboardInterrupt:
        return 130


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")


# --- adapter -----------------------------------------------------------------


def _cmd_adapter(_args: argparse.Namespace) -> int:
    info = asyncio.run(adapter_info())
    for key, value in info.items():
        print(f"{key:42} {value}")
    if info.get("is_extended_advertising_supported") is False:
        print("\nNota: sin anuncios extendidos no se ven LE Audio / Auracast. AirPods, Fast Pair y Swift Pair usan anuncios legacy.")
    return 0


# --- run ---------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    from .capture.bleak_backend import BleakBackend

    ruleset = load_default_ruleset()
    privacy = Privacy(keep_names=args.keep_names, name_hinter=ruleset.name_hint)
    session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    writer = None if args.no_record else JsonlWriter(args.out / f"{session_id}.jsonl")
    meta: dict[str, Any] = {
        "session_id": session_id,
        "started": datetime.now(UTC).isoformat(),
        "bluedar": __version__,
        "adapter": await adapter_info(),
        "scanning_mode": "passive" if args.passive else "active",
        "classic": args.classic,
        "keep_names": args.keep_names,
        "absence_s": args.absence,
        "privacy": "direcciones pseudonimizadas con clave de sesión descartada al terminar",
    }
    room = Room.load(args.room) if args.room else None
    if room is not None and "local" not in room.nodes:
        print("Aviso: room.yaml no define el receptor 'local' (esta PC); no aportará a la ubicación.", file=sys.stderr)
    session = Session(ruleset, privacy, writer, args.absence, meta=meta, room=room)
    backends: list[Any] = [BleakBackend("passive" if args.passive else "active")]
    if args.classic:
        if sys.platform != "win32":
            print("--classic solo está implementado para Windows.", file=sys.stderr)
            return 2
        from .capture.win_classic_backend import WinClassicBackend

        backends.append(WinClassicBackend())

    if writer:
        print(f"Grabando en {writer.path}")
        write_meta(meta_path_for(writer.path), meta)

    workers = [asyncio.create_task(session.consume(b), name=f"backend:{b.name}") for b in backends]
    workers.append(asyncio.create_task(session.ticker(), name="ticker"))
    main_tasks: list[asyncio.Task] = []
    server = None
    if args.no_ui:
        main_tasks.append(asyncio.create_task(_console_report(session), name="console"))
    else:
        host = "0.0.0.0" if args.lan else "127.0.0.1"
        server = _make_server(session, args.port, host)
        main_tasks.append(asyncio.create_task(server.serve(), name="server"))
        print(f"Interfaz: http://127.0.0.1:{args.port}  (Ctrl+C para terminar)")
        if args.lan:
            print(f"Escuchando en la red local. Receptores: bluedar node --hub http://{_lan_ip()}:{args.port} --id <nombre>")
            print("Aviso: la UI también queda accesible desde la red local (datos pseudonimizados).")
    if args.duration:
        main_tasks.append(asyncio.create_task(asyncio.sleep(args.duration), name="duration"))

    exit_code = 0
    try:
        done, _ = await asyncio.wait(workers + main_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.get_name().startswith("backend:") and task.exception():
                print(f"Error en {task.get_name()}: {task.exception()}", file=sys.stderr)
                exit_code = 1
    finally:
        if server is not None:
            server.should_exit = True
        for task in workers + main_tasks:
            if task.get_name() != "server":
                task.cancel()
        await asyncio.gather(*workers, *main_tasks, return_exceptions=True)
        session.tick()
        _finish(session, writer)
    return exit_code


def _make_server(session: Session, port: int, host: str = "127.0.0.1") -> Any:
    import uvicorn

    from .app.server import create_app

    config = uvicorn.Config(create_app(session), host=host, port=port, log_level="warning")
    return uvicorn.Server(config)


def _lan_ip() -> str:
    import socket

    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # UDP sin enviar nada: solo elige la interfaz de salida
        return s.getsockname()[0]
    return "<IP-de-esta-PC>"


async def _console_report(session: Session, every: float = 5.0) -> None:
    while True:
        await asyncio.sleep(every)
        snap = session.snapshot(include_reasons=False)
        labels = [e["label"] for e in snap["entities"] if e["present"]]
        print(
            f"{datetime.now():%H:%M:%S}  paquetes={snap['packets']:>7}  presentes={snap['entities_present']:>4}/{snap['entities_total']:<4}"
            f"  auriculares?={labels.count('auricular'):>3}  parlantes?={labels.count('parlante'):>3}"
            f"  descartados={snap['dropped']}" + ("  ⚠ posible BLE spam" if snap["spam_active"] else ""),
            flush=True,
        )


def _finish(session: Session, writer: JsonlWriter | None) -> None:
    snap = session.snapshot()
    session.meta.update({
        "ended": datetime.now(UTC).isoformat(),
        "packets": snap["packets"],
        "entities": snap["entities_total"],
        "dropped": snap["dropped"],
    })
    if writer is not None:
        writer.close()
        write_meta(meta_path_for(writer.path), session.meta)
        print(f"\nCaptura: {writer.path} ({writer.count} paquetes)")
    _print_candidates(snap["entities"])


def _print_candidates(entities: list[dict]) -> None:
    audio = [e for e in entities if e["label"] in ("auricular", "parlante")]
    print(f"Entidades: {len(entities)} · posibles audio: {len(audio)}")
    for e in sorted(audio, key=lambda e: -(e["rssi"] or -999)):
        print(
            f"  {e['id'][:6]}  {e['label_text']:<18} {e['basis'] or '':<10} conf={e['confidence'] or '-':<5}"
            f" {e['model'] or e['family'] or '':<40} rssi={e['rssi']}"
            + ("  ⚠" if e["warnings"] else "")
        )


# --- replay / export ---------------------------------------------------------


def _replay_session(path: Path, absence: float) -> Session:
    meta_file = meta_path_for(path)
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta["source"] = str(path)
    return Session(load_default_ruleset(), absence_s=absence, meta=meta, virtual_time=True)


def _cmd_replay(args: argparse.Namespace) -> int:
    async def go() -> None:
        session = _replay_session(args.file, args.absence)
        server = _make_server(session, args.port)
        consumer = asyncio.create_task(session.consume(ReplayBackend(args.file, args.speed)))
        ticker = asyncio.create_task(session.ticker())
        print(f"Interfaz: http://127.0.0.1:{args.port}  (Ctrl+C para terminar)")
        try:
            await server.serve()
        finally:
            consumer.cancel()
            ticker.cancel()
            await asyncio.gather(consumer, ticker, return_exceptions=True)

    asyncio.run(go())
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    async def go() -> Session:
        session = _replay_session(args.file, args.absence)
        await session.consume(ReplayBackend(args.file, speed=0))
        session.tick()
        return session

    session = asyncio.run(go())
    snap = session.snapshot()
    text = entities_to_csv(snap["entities"]) if args.format == "csv" else snapshot_to_json(snap, session.meta)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Exportado: {args.output}")
    else:
        sys.stdout.write(text)
    return 0


# --- receptores y ubicación ----------------------------------------------------


def _cmd_node(args: argparse.Namespace) -> int:
    from .remote_node import RemoteNode

    asyncio.run(RemoteNode(args.hub, args.id, "passive" if args.passive else "active").run())
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    from .positioning.simulate import run as simulate

    room = Room.load(args.room)
    print(f"Habitación {room.width} × {room.height} m · receptores: {', '.join(room.nodes)}")
    print("Resultados de un MODELO (sombreado gaussiano independiente): cota optimista, no una medición.\n")
    print(f"{'σ RSSI':>7} {'n real':>7} {'resueltos':>10} {'error p50':>10} {'error p90':>10} {'radio inf.':>11} {'cobertura':>10}  {'centro p50/p90':>15}")
    assumed_n = sum(n.n for n in room.nodes.values()) / max(1, len(room.nodes))
    for sigma in (2.0, 4.0, 6.0, 8.0):
        for n_true in (None, assumed_n + 0.7):
            r = simulate(room, sigma, n_true, args.trials)
            label = "= mod." if n_true is None else f"{n_true:.1f}"
            print(
                f"{sigma:>5.0f}dB {label:>7} {r.solved:>5}/{r.trials:<4} {r.median_m:>9.2f}m {r.p90_m:>9.2f}m"
                f" {r.mean_reported_radius_m:>10.2f}m {r.coverage:>9.0%}  {r.center_median_m:>6.2f}/{r.center_p90_m:.2f}m"
            )
    print("\nn real ≠ modelo: simula un exponente de pérdida mal calibrado (paredes, cuerpos).")
    print("cobertura: % de casos con error ≤ radio informado. Muy por encima de ~63% = radio conservador; por debajo = la app subestima su error.")
    print("centro: error de decir siempre 'el centro de la habitación'. Si la estimación no le gana, no aporta.")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from .capture.sim_backend import SIM_DEVICES, SimBackend

    async def go() -> None:
        room = Room.load(args.room)
        room.path = None  # en la demo, calibrar no modifica el archivo
        meta = {"session_id": "demo", "source": "simulador", "labels": {k: v[0] for k, v in SIM_DEVICES.items()}}
        session = Session(load_default_ruleset(), meta=meta, room=room)
        server = _make_server(session, args.port)
        consumer = asyncio.create_task(session.consume(SimBackend(room, sigma_db=args.noise)))
        ticker = asyncio.create_task(session.ticker())
        print(f"Demo (datos simulados): http://127.0.0.1:{args.port}  (Ctrl+C para terminar)")
        try:
            await server.serve()
        finally:
            consumer.cancel()
            ticker.cancel()
            await asyncio.gather(consumer, ticker, return_exceptions=True)

    asyncio.run(go())
    return 0


# --- stats -------------------------------------------------------------------


def _cmd_stats(args: argparse.Namespace) -> int:
    from .analysis.stats import compute

    summary, rows = compute(args.file)
    if args.json:
        print(json.dumps({"summary": summary, "addresses": rows}, indent=2, ensure_ascii=False))
        return 0
    for key, value in summary.items():
        print(f"{key:16} {value}")
    print()
    header = f"{'addr':12} {'tipo':13} {'tr':5} {'paq':>6} {'Hz':>6} {'gap50':>6} {'gapmax':>7} {'rssi':>5}  pdus / fabricantes / apple / nombre"
    print(header)
    print("-" * len(header))
    for r in rows[: args.top]:
        extras = " ".join(filter(None, [
            ",".join(f"{k}:{v}" for k, v in r["pdus"].items()),
            ",".join(r["companies"]),
            ",".join(r["apple"]),
            ("nombre en " + ",".join(r["name_in"])) if r["name_in"] else "",
        ]))
        print(
            f"{r['addr']:12} {r['kind']:13} {r['tr']:5} {r['packets']:>6} {r['rate_hz'] if r['rate_hz'] is not None else '-':>6}"
            f" {r['gap_p50_s'] if r['gap_p50_s'] is not None else '-':>6} {r['gap_max_s'] if r['gap_max_s'] is not None else '-':>7}"
            f" {r['rssi_med'] if r['rssi_med'] is not None else '-':>5}  {extras}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
