"""Class of Device (Classic) y Appearance (BLE): declaraciones estándar de tipo.

Valores de Bluetooth SIG Assigned Numbers. Los subtipos que no figuran acá se
muestran en hex; no se infiere nada de ellos.
"""

from __future__ import annotations

MAJOR_AUDIO_VIDEO = 0x04

# Minor class de Audio/Video → (nombre, tipo para el clasificador o None)
AV_MINOR: dict[int, tuple[str, str | None]] = {
    0x01: ("Wearable Headset", "auricular"),
    0x02: ("Hands-free", "auricular"),
    0x04: ("Microphone", None),
    0x05: ("Loudspeaker", "parlante"),
    0x06: ("Headphones", "auricular"),
    0x07: ("Portable Audio", None),
    0x08: ("Car audio", None),
    0x09: ("Set-top box", None),
    0x0A: ("HiFi Audio Device", "parlante"),
    0x0F: ("Video Display and Loudspeaker", None),
}

# Appearance: categoría = valor >> 6
APPEARANCE_CAT_AUDIO_SINK = 0x021
APPEARANCE_CAT_WEARABLE_AUDIO = 0x025
APPEARANCE_NAMES = {
    0x0840: "Audio Sink (genérico)",
    0x0841: "Standalone Speaker",
    0x0940: "Wearable Audio Device (genérico)",
    0x0941: "Earbud",
    0x0945: "Left Earbud",
}


def cod_major(cod: int) -> int:
    return (cod >> 8) & 0x1F


def cod_minor(cod: int) -> int:
    return (cod >> 2) & 0x3F


def describe_cod(cod: int) -> tuple[str, str | None]:
    """Devuelve (descripción, tipo) para un CoD. tipo None si no declara auricular/parlante."""
    major = cod_major(cod)
    if major != MAJOR_AUDIO_VIDEO:
        return f"CoD major 0x{major:02X} (no audio/video)", None
    minor = cod_minor(cod)
    name, kind = AV_MINOR.get(minor, (f"minor 0x{minor:02X}", None))
    return f"Audio/Video · {name}", kind


def describe_appearance(value: int) -> tuple[str, str | None]:
    category = value >> 6
    name = APPEARANCE_NAMES.get(value, f"0x{value:04X}")
    if category == APPEARANCE_CAT_WEARABLE_AUDIO:
        return f"Wearable Audio · {name}", "auricular"
    if category == APPEARANCE_CAT_AUDIO_SINK:
        return f"Audio Sink · {name}", "parlante"
    return f"Appearance {name} (categoría 0x{category:03X})", None
