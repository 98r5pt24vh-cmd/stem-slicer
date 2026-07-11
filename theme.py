COLORS = {
    "window": "#0b0c0e",
    "surface": "#15171a",
    "surface_raised": "#202328",
    "surface_pressed": "#101215",
    "border": "#393d44",
    "border_soft": "#292c31",
    "text": "#f2f3f5",
    "muted": "#92979f",
    "disabled": "#5e636a",
    "red": "#ff3b21",
    "red_hover": "#ff5039",
    "red_dark": "#a91c0c",
    "success": "#55d48a",
}


def application_stylesheet():
    return f"""
    * {{
        font-family: "SF Pro Display", "Segoe UI", Arial, sans-serif;
        color: {COLORS['text']};
        outline: none;
    }}
    QMainWindow, QWidget#StudioRoot {{
        background: {COLORS['window']};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QFrame#Panel {{
        background-color: {COLORS['surface']};
        border: 1px solid {COLORS['border']};
        border-radius: 7px;
    }}
    QFrame#Inset {{
        background-color: {COLORS['surface_pressed']};
        border: 1px solid {COLORS['border_soft']};
        border-radius: 6px;
    }}
    QLabel#Eyebrow {{
        color: {COLORS['red']};
        font-size: 10px;
        font-weight: 800;
    }}
    QLabel#SectionTitle {{
        font-size: 15px;
        font-weight: 800;
    }}
    QLabel#SectionDescription, QLabel#Muted {{
        color: {COLORS['muted']};
        font-size: 12px;
    }}
    QLabel#Mono, QLabel#PathValue, QLabel#PreviewValue, QLabel#Version {{
        font-family: "SF Mono", Menlo, Consolas, monospace;
    }}
    QLabel#PathValue {{
        color: #d9dce1;
        font-size: 11px;
    }}
    QLabel#PreviewValue {{
        color: #ffffff;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel#Version {{
        color: {COLORS['disabled']};
        font-size: 9px;
    }}
    QPushButton {{
        background: {COLORS['surface_raised']};
        border: 1px solid #4b4f57;
        border-bottom: 2px solid #08090b;
        border-radius: 5px;
        padding: 7px 14px 6px 14px;
        font-size: 11px;
        font-weight: 750;
    }}
    QPushButton:hover {{
        background: #292d33;
        border-color: #646a74;
    }}
    QPushButton:pressed {{
        background: {COLORS['surface_pressed']};
        border-bottom: 1px solid #08090b;
        padding-top: 8px;
        padding-bottom: 5px;
    }}
    QPushButton:disabled {{
        color: {COLORS['disabled']};
        background: #17191c;
        border-color: #2b2e33;
    }}
    QPushButton#PrimaryAction {{
        background: {COLORS['red']};
        color: white;
        border: 1px solid {COLORS['red_hover']};
        border-bottom: 3px solid {COLORS['red_dark']};
        border-radius: 6px;
        font-size: 13px;
        font-weight: 900;
        padding: 13px 22px 11px 22px;
    }}
    QPushButton#PrimaryAction:hover {{
        background: {COLORS['red_hover']};
    }}
    QPushButton#PrimaryAction:pressed {{
        background: #dc2a14;
        border-bottom: 1px solid {COLORS['red_dark']};
        padding-top: 14px;
        padding-bottom: 10px;
    }}
    QPushButton#PrimaryAction:disabled {{
        background: #34373c;
        color: #777c84;
        border-color: #41454b;
    }}
    QPushButton#Segment {{
        border-radius: 4px;
        padding: 7px 12px;
        background: #1b1e22;
        border: 1px solid #32363c;
        border-bottom: 2px solid #090a0c;
        color: {COLORS['muted']};
    }}
    QPushButton#Segment:checked {{
        background: #383c43;
        border-color: #666c76;
        color: white;
    }}
    QPushButton#Segment:disabled {{
        color: #4f535a;
        background: #141619;
        border-color: #24272b;
    }}
    QProgressBar {{
        background: #0d0f11;
        border: 1px solid #2c3035;
        border-radius: 4px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: {COLORS['red']};
        border-radius: 3px;
    }}
    QToolTip {{
        background: #24272c;
        color: white;
        border: 1px solid #4c5159;
        padding: 5px;
    }}
    """
