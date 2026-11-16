"""Inline SVG icons (stroke style, 24x24) for the templates: {{ icon("home") }}."""
from markupsafe import Markup

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "wallet": '<path d="M16 7V5H5a2 2 0 0 0 0 4"/><rect x="3" y="7" width="18" height="13" rx="2"/>'
              '<path d="M16 13.5h2"/>',
    "more": '<path d="M12 2.8 20 7.4v9.2l-8 4.6-8-4.6V7.4z"/><path d="M8.6 12h.01M12 12h.01M15.4 12h.01"/>',
    "chart": '<path d="M5 20V11M11 20V5M17 20v-6M3 20h18"/>',
    "loan": '<path d="M3 10 12 4l9 6M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/>'
              '<path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    "card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    "tag": '<path d="M3 3h8l10 10-8 8L3 11z"/><path d="M7.5 7.5h.01"/>',
    "settings": '<path d="M4 6h9M19 6h1M4 12h3M13 12h7M4 18h11M21 18h-1"/><circle cx="16" cy="6" r="2.5"/>'
                '<circle cx="10" cy="12" r="2.5"/><circle cx="17.5" cy="18" r="2.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "left": '<path d="m15 18-6-6 6-6"/>',
    "right": '<path d="m9 18 6-6-6-6"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "upload": '<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "edit": '<path d="M4 20h4L20 8l-4-4L4 16z"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>',
    "alert": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.01"/>',
    "up": '<path d="m3 17 6-6 4 4 8-8M14 7h7v7"/>',
    "down": '<path d="m3 7 6 6 4-4 8 8M14 17h7v-7"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    "hexagon": '<path d="M12 2.8 20 7.4v9.2l-8 4.6-8-4.6V7.4z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    "send":'<path d="M21 3 3 10.5l7 2.5 2.5 7z"/><path d="M21 3 10 13"/>',
}


def icon(name: str, size: int = 20) -> Markup:
    return Markup(
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
        f'focusable="false">{ICONS[name]}</svg>'
    )
