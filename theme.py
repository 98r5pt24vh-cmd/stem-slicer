COLORS = {"red": "#ff2b1c", "text": "#eef0f2", "muted": "#92979f"}


def application_stylesheet():
    return """
    * { font-family: "SF Pro Display", "Helvetica Neue", sans-serif; color: #eef0f2; outline: none; }
    QMainWindow, QWidget#StudioRoot { background: #090b0d; }
    QDialog[role="managerDialog"] { background: #101417; }
    QFrame[role="panel"] { background: #14181b; border: 1px solid #333a40; border-radius: 7px; }
    QFrame[role="header"] { background: transparent; border: none; }
    QFrame[role="result"] { background: #101417; border: 1px solid #30373d; border-radius: 6px; }
    QFrame[role="modeChip"] { background: #171d21; border: 1px solid #303940; border-radius: 4px; }
    QFrame[role="sourcePanel"] { background: #181d21; border: 1px solid #343c43; border-radius: 6px; }
    QFrame[role="resultPanel"] { background: #0d1215; border: 1px solid #2b3339; border-radius: 6px; }
    QFrame[role="disabledPanel"] { background: #111518; border: 1px solid #293036; border-radius: 7px; }
    QFrame[role="disabledInner"] { background: #0e1215; border: 1px solid #252b30; border-radius: 6px; }
    QFrame[role="activePanel"] { background: #14181b; border: 1px solid #333a40; border-radius: 7px; }
    QFrame[role="activeInner"] { background: #101417; border: 1px solid #30373d; border-radius: 6px; }
    QFrame[role="separator"] { background: #252c31; border: none; }
    QFrame[role="subtleSeparator"] { background: rgba(122, 132, 141, 0.16); border: none; }
    QLabel[role="pageTitle"] { font-size: 17px; font-weight: 800; letter-spacing: 1px; }
    QLabel[role="boxTitle"] { color: #f3f4f5; font-size: 14px; font-weight: 700; letter-spacing: 1px; }
    QLabel[role="redSmall"] { color: #ff2b1c; font-size: 11px; font-weight: 800; }
    QLabel[role="redBrand"] { color: #ff2b1c; font-size: 16px; font-weight: 900; }
    QLabel[role="muted"] { color: #999ea5; font-size: 11px; }
    QLabel[role="tabSubtitle"] { color: #a5abb1; font-size: 12px; }
    QLabel[role="mutedSmall"] { color: #8b9198; font-size: 10px; }
    QLabel[role="monoDim"], QLabel[role="mono"] { color: #858b92; font-family: "SF Mono", Menlo; font-size: 10px; }
    QLabel[role="tabTitle"] { color: #d2d6da; font-size: 16px; font-weight: 800; letter-spacing: 1px; }
    QLabel[role="tabTitle"][active="true"] { color: #ff2b1c; }
    QFrame[role="tabLine"] { background: transparent; border: none; }
    QFrame[role="tabLine"][active="true"] { background: #ff2b1c; }
    QFrame[role="dropZone"] { background: #11161a; border: none; border-radius: 7px; }
    QLabel[role="dropTitle"] { font-size: 13px; font-weight: 600; }
    QLabel[role="dropSubtitle"] { color: #a9afb5; font-size: 13px; font-weight: 500; }
    QLabel[role="info"] { color: #a4a9af; font-size: 10px; }
    QFrame[role="resultLine"] { background: transparent; border: none; }
    QLabel[role="scannedFile"] { color: #e2e5e7; font-size: 14px; font-weight: 650; }
    QLabel[role="analyzedTime"] { color: #858d94; font-size: 10px; font-weight: 500; }
    QLabel[role="keyValue"] { font-size: 23px; font-weight: 500; }
    QLabel[role="keyModeName"] { color: #9da5ac; font-size: 10px; font-weight: 500; }
    QLabel[role="degreeValue"] { color: #d5d9dc; font-size: 12px; font-weight: 750; }
    QLabel[role="resultTitle"] { color: #ff2b1c; font-size: 12px; font-weight: 850; }
    QLabel[role="modeFull"] { color: #f0f1f2; font-size: 10px; font-weight: 700; }
    QLabel[role="modeDegree"] { color: #d5d9dc; font-size: 10px; font-weight: 750; }
    QLabel[role="modeNote"] { color: #9da5ac; font-size: 10px; font-weight: 500; }
    QLabel[role="degreeReference"], QLabel[role="controlLabel"] { color: #929aa1; font-size: 9px; font-weight: 750; }
    QLabel[role="success"], QLabel[role="status"] { color: #b9bec4; font-size: 11px; }
    QLabel[role="storage"] { color: #aeb4ba; font-size: 14px; font-weight: 500; }
    QLabel[role="status"] { color: #b9bec4; }
    QLabel[role="mutedCaps"] { color: #9aa0a7; font-size: 11px; letter-spacing: 1px; }
    QLabel[role="disabledTitle"] { color: #96261f; font-size: 16px; font-weight: 800; letter-spacing: 1px; }
    QLabel[role="activeTitle"] { color: #ff2b1c; font-size: 16px; font-weight: 800; letter-spacing: 1px; }
    QLabel[role="disabledText"] { color: #50565c; font-size: 10px; }
    QLabel[role="disabledTiny"] { color: #454b51; font-size: 9px; }
    QLabel[role="disabledField"] { color: #4a5056; background: #111518; border: 1px solid #242a2f; border-radius: 4px; padding: 6px; font-family: "SF Mono"; }
    QLabel[role="activeField"] { color: #b7bdc3; background: #0d1114; border: 1px solid #2c3339; border-radius: 4px; padding: 6px; font-family: "SF Mono"; }
    QLabel[role="chipText"], QLabel[role="buttonText"] { color: #b7bdc3; font-size: 10px; font-weight: 700; }
    QLabel[role="cardWave"] { color: #747c83; font-family: Menlo; font-size: 10px; }
    QLabel[role="cardMeta"] { color: #9aa1a8; font-family: "SF Mono", Menlo; font-size: 9px; }
    QLabel[role="layerName"] { color: #b9bec3; font-size: 11px; font-weight: 700; min-width: 75px; }
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1a1f23, stop:0.52 #161b1f, stop:1 #12171a);
        border: 1px solid #424a52;
        border-radius: 5px;
        padding: 7px 16px;
        font-size: 10px;
        font-weight: 750;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22282e, stop:0.50 #1b2126, stop:1 #171c20);
        border-color: #59636d;
    }
    QPushButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #111518, stop:1 #1a2025);
        border-color: #3d454d;
    }
    QPushButton[role="icon"] { font-size: 18px; padding: 3px 8px; }
    QPushButton[role="selected"] {
        color: #ffffff;
        border-color: #e64032;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c92b20, stop:0.52 #b82117, stop:1 #9f190f);
    }
    QPushButton[role="primary"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d72f23, stop:0.52 #c32318, stop:1 #a91a10);
        border-color: #e34538;
        color: white;
    }
    QPushButton[role="primary"] { font-size: 16px; font-weight: 800; }
    QPushButton[role="disabled"] { color: #454b51; background: #13171a; border-color: #262c31; }
    QPushButton[role="chip"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282e35, stop:1 #1d2329);
        border-color: #4a525b;
        padding: 0;
    }
    QPushButton[role="chip"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #30373e, stop:1 #242a31);
        border-color: #606a74;
    }
    QPushButton[role="layerPlay"] { padding: 0; border-radius: 12px; color: #57d84e; font-size: 11px; }
    QPushButton[role="layerPlay"][state="playing"] { color: #e1a83a; }
    QPushButton[role="layerPlay"][state="paused"] { color: #57d84e; }
    QPushButton[role="compact"], QPushButton[role="compactSelected"] { padding: 0; border-radius: 4px; font-size: 8px; font-weight: 800; }
    QPushButton[role="compactSelected"] { color: white; border-color: #d63a2e; background: #a92017; }
    QFrame[role="switch"] { background: #15191d; border: 1px solid #414951; border-radius: 14px; }
    QFrame[role="switch"][active="true"] { background: #391513; border-color: #ff2b1c; }
    QLabel[role="switchDot"] { color: #818990; font-size: 22px; }
    QLabel[role="switchText"] { color: #656b72; font-size: 12px; font-weight: 700; }
    QLabel[role="switchDot"][active="true"], QLabel[role="switchText"][active="true"] { color: #ff2b1c; }
    QProgressBar { background: #0c0f11; border: 1px solid #333a40; border-radius: 4px; height: 9px; color: transparent; }
    QProgressBar::chunk { background: #ff2b1c; }
    QScrollArea[role="layers"], QScrollArea[role="layers"] > QWidget > QWidget { background: #0e1215; border: 1px solid #30373d; border-radius: 6px; }
    QScrollArea[role="layers"] > QWidget > QWidget { border: none; }
    QFrame[role="layerCard"] { background: #12171a; border: 1px solid #323a41; border-radius: 6px; }
    QFrame[role="managerRow"] { background: #151a1e; border: 1px solid #343c43; border-radius: 6px; }
    QLabel[role="managerName"] { color: #eef0f2; font-size: 12px; font-weight: 750; }
    QScrollArea[role="managerList"], QScrollArea[role="managerList"] > QWidget > QWidget { background: #0d1114; border: 1px solid #2f373d; border-radius: 6px; }
    QPushButton[role="danger"] { color: #ff796e; border-color: #71342f; background: #251513; }
    QPushButton[role="danger"]:hover { color: white; border-color: #d64337; background: #8f2119; }
    QScrollBar:vertical { background: #0d1012; width: 8px; margin: 5px 1px; }
    QScrollBar::handle:vertical { background: #454c53; border-radius: 4px; min-height: 28px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """
