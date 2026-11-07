"""Windows: notification-area icon (battery digits as a dot matrix) and a borderless popup above it.

The popup is a Chromium window in --app mode: its own title bar styles are stripped, DWM non-client
rendering is disabled and a rounded window region clips the title bar away. Launched with
--disable-direct-composition so the region applies. No dependencies beyond ctypes.
"""
import ctypes as C
import ctypes.wintypes as W
import os
import subprocess
import threading
import time

from . import APP_NAME

u32, shell32, dwm, gdi = C.windll.user32, C.windll.shell32, C.windll.dwmapi, C.windll.gdi32
LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
u32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.GetWindowLongPtrW.restype = C.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
u32.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]  # HWND_TOPMOST=-1 must be pointer-wide
u32.CreateIconFromResourceEx.restype = W.HICON
u32.CreateIconFromResourceEx.argtypes = [C.c_char_p, W.DWORD, W.BOOL, W.DWORD, C.c_int, C.c_int, W.UINT]
u32.LoadImageW.restype = W.HANDLE
# Every handle-returning call needs a pointer-wide restype: the ctypes default (c_int) truncates 64-bit
# handles, which works only while Windows happens to hand out low addresses and crashes otherwise.
k32 = C.windll.kernel32
k32.GetModuleHandleW.restype = W.HMODULE
k32.GetModuleHandleW.argtypes = [W.LPCWSTR]
u32.RegisterClassW.restype = W.ATOM
u32.CreateWindowExW.restype = W.HWND
u32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
u32.CreatePopupMenu.restype = W.HMENU
u32.AppendMenuW.argtypes = [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR]
u32.TrackPopupMenu.argtypes = [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, W.LPVOID]
u32.DestroyMenu.argtypes = [W.HMENU]
u32.DestroyIcon.argtypes = [W.HICON]
u32.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
u32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
u32.IsWindow.argtypes = u32.IsWindowVisible.argtypes = [W.HWND]
u32.ShowWindow.argtypes = [W.HWND, C.c_int]
u32.SetForegroundWindow.argtypes = [W.HWND]
u32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u32.GetWindowLongPtrW.argtypes = [W.HWND, C.c_int]
u32.GetDpiForWindow.argtypes = [W.HWND]
u32.GetWindowRect.argtypes = u32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
u32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, W.LPVOID, W.DWORD]
gdi.CreateRoundRectRgn.restype = W.HRGN
u32.SetWindowRgn.argtypes = [W.HWND, W.HRGN, W.BOOL]
WM_TRAY, WM_LBUTTONUP, WM_RBUTTONUP = 0x8001, 0x0202, 0x0205
HERE = os.path.dirname(os.path.abspath(__file__))
AUMID = "NothingX.Desktop.Unofficial"


def register_identity():
    """Give our notifications the app's name and icon instead of "Python": an AppUserModelID for the process,
    registered under HKCU so the toast shows DisplayName/IconUri. Best effort, never fatal."""
    try:
        C.windll.shell32.SetCurrentProcessExplicitAppUserModelID(C.c_wchar_p(AUMID))
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\AppUserModelId\{AUMID}") as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_EXPAND_SZ, os.path.join(HERE, "icon.png"))
    except OSError:
        pass


class WNDCLASSW(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("uFlags", W.UINT),
                ("uCallbackMessage", W.UINT), ("hIcon", W.HICON), ("szTip", W.WCHAR * 128), ("dwState", W.DWORD),
                ("dwStateMask", W.DWORD), ("szInfo", W.WCHAR * 256), ("uVersion", W.UINT),
                ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD), ("guidItem", C.c_byte * 16),
                ("hBalloonIcon", W.HICON)]


class NOTIFYICONIDENTIFIER(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("guidItem", C.c_byte * 16)]


FONT = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
        "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
        "8": "111101111101111", "9": "111101111001111", "-": "000000111000000"}


def icon_bits(text, red=False, size=32):
    """32-bit icon resource (BITMAPINFOHEADER + BGRA + AND mask) drawing text as a 3x5 dot matrix."""
    cols = len(text) * 4 - 1
    pitch = min(size // cols, 6)
    dot = max(2, pitch - 1)
    x0, y0 = (size - cols * pitch + 1) // 2, (size - 5 * pitch + 1) // 2
    px = bytearray(size * size * 4)
    color = (0x21, 0x19, 0xD7, 255) if red else (255, 255, 255, 255)
    for ci, ch in enumerate(text):
        for r in range(5):
            for c in range(3):
                if FONT.get(ch, FONT["-"])[r * 3 + c] == "1":
                    for dy in range(dot):
                        for dx in range(dot):
                            x, y = x0 + (ci * 4 + c) * pitch + dx, y0 + r * pitch + dy
                            if 0 <= x < size and 0 <= y < size:
                                i = ((size - 1 - y) * size + x) * 4  # bottom-up rows
                                px[i:i + 4] = bytes(color)
    header = (40).to_bytes(4, "little") + size.to_bytes(4, "little") + (size * 2).to_bytes(4, "little") \
        + (1).to_bytes(2, "little") + (32).to_bytes(2, "little") + bytes(24)
    return bytes(header) + bytes(px) + bytes(size * size // 8)


class Tray:
    POPUP = True  # the window is a flyout: hides when it loses focus

    def __init__(self, buds, settings, browser_cmd, size):
        self.buds, self.settings, self.browser_cmd, self.size = buds, settings, browser_cmd, size
        self.proc = None
        self.launching = threading.Lock()  # warm-up and a click can race to spawn the browser
        self.hwnd_popup = None
        self.hidden_at = 0
        self.cap = 31     # Chromium title bar height in CSS px, until measured
        self.bar = None   # measured title bar height in device px
        register_identity()
        self.app_icon = u32.LoadImageW(None, os.path.join(HERE, "icon.ico"), 1, 64, 64, 0x10)  # for notifications
        self._proc = WNDPROC(self.wndproc)  # keep a reference or ctypes frees the callback
        wc = WNDCLASSW(lpfnWndProc=self._proc, lpszClassName="NothingXTray",
                       hInstance=k32.GetModuleHandleW(None))
        u32.RegisterClassW(C.byref(wc))
        self.hwnd = u32.CreateWindowExW(0, "NothingXTray", "NothingXTray", 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
        self.nid = NOTIFYICONDATAW(cbSize=C.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                                   uFlags=1 | 2 | 4, uCallbackMessage=WM_TRAY)
        self.set_icon(None, APP_NAME)
        shell32.Shell_NotifyIconW(0, C.byref(self.nid))  # NIM_ADD
        threading.Thread(target=self.watch, daemon=True, name="tray-watch").start()

    def set_icon(self, text, tip, red=False):
        old = self.nid.hIcon
        if text is None:
            self.nid.hIcon = u32.LoadImageW(None, os.path.join(HERE, "icon.ico"), 1, 32, 32, 0x10)  # IMAGE_ICON, LOADFROMFILE
        else:
            bits = icon_bits(text, red)
            self.nid.hIcon = u32.CreateIconFromResourceEx(bits, len(bits), True, 0x00030000, 32, 32, 0)
        self.nid.szTip = tip[:127]
        if old:
            shell32.Shell_NotifyIconW(1, C.byref(self.nid))  # NIM_MODIFY
            u32.DestroyIcon(old)

    def watch(self):
        """Mirror battery into the tray icon and tooltip."""
        from .app import LowBattery
        ver, low_alert = -1, LowBattery()
        while True:
            with self.buds.cv:
                self.buds.cv.wait_for(lambda: self.buds.ver != ver, timeout=5)
                ver, st = self.buds.ver, dict(self.buds.state)
            bat = st.get("battery") or {}
            name = (st.get("model") or {}).get("name", APP_NAME)
            if not st.get("connected"):
                self.set_icon(None, f"{name}: not connected")
                continue
            if crossed := low_alert.check(bat, self.settings.get("low_battery")):
                self.notify(*LowBattery.message(name, crossed, self.settings.get("lang")))
            parts = [f"{k.upper() if k != 'case' else 'Case'} {b['lvl']}%{' +' if b['chg'] else ''}" for k, b in bat.items()]
            low = min([b["lvl"] for k, b in bat.items() if k in ("L", "R")], default=None)
            text = str(min(low, 99)) if low is not None and self.settings.get("tray_battery") else None
            self.set_icon(text, f"{name}\n" + "  ".join(parts), red=low is not None and low <= self.settings.get("low_battery"))

    def notify(self, title, text):
        """Windows notification from the tray icon (shown as a toast on Windows 10/11)."""
        self.nid.uFlags |= 0x10           # NIF_INFO
        self.nid.szInfoTitle, self.nid.szInfo = title[:63], text[:255]
        self.nid.hBalloonIcon = self.app_icon
        self.nid.dwInfoFlags = 0x04 | 0x20  # NIIF_USER (our icon) | NIIF_LARGE_ICON
        shell32.Shell_NotifyIconW(1, C.byref(self.nid))  # NIM_MODIFY
        self.nid.uFlags &= ~0x10          # later icon updates must not repeat the notification

    def wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_TRAY:
            if lp == WM_LBUTTONUP:
                self.toggle()
            elif lp == WM_RBUTTONUP:
                self.menu()
            return 0
        return u32.DefWindowProcW(hwnd, msg, wp, lp)

    def menu(self):
        m = u32.CreatePopupMenu()
        u32.AppendMenuW(m, 0, 1, "Open")
        u32.AppendMenuW(m, 0, 2, "Quit")
        pt = W.POINT()
        u32.GetCursorPos(C.byref(pt))
        u32.SetForegroundWindow(self.hwnd)
        cmd = u32.TrackPopupMenu(m, 0x0100 | 0x0080 | 0x0020, pt.x, pt.y, 0, self.hwnd, None)  # RETURNCMD|NONOTIFY|BOTTOMALIGN
        u32.DestroyMenu(m)
        if cmd == 1:
            self.show()
        elif cmd == 2:
            self.quit()

    # -- popup window

    def find_popup(self):
        if self.hwnd_popup and u32.IsWindow(self.hwnd_popup):
            return self.hwnd_popup
        found = []

        @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def cb(h, _):
            buf = C.create_unicode_buffer(64)
            u32.GetWindowTextW(h, buf, 64)
            if buf.value == APP_NAME and u32.IsWindowVisible(h):  # Chromium also has a hidden helper with the same title
                found.append(h)
            return True
        u32.EnumWindows(cb, 0)
        if not found:
            return None
        h = self.hwnd_popup = found[0]
        u32.ShowWindow(h, 0)
        return h

    @staticmethod
    def strip(h):
        """Make the browser window a bare popup. Re-done on every show: Chromium restores its styles on its own."""
        style = u32.GetWindowLongPtrW(h, -16) & ~(0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000)
        u32.SetWindowLongPtrW(h, -16, style)  # no caption, sizing border, min/max
        ex = (u32.GetWindowLongPtrW(h, -20) | 0x80) & ~0x40000  # TOOLWINDOW, not APPWINDOW: no taskbar button
        u32.SetWindowLongPtrW(h, -20, ex)
        dwm.DwmSetWindowAttribute(h, 2, C.byref(C.c_int(1)), 4)  # NCRENDERING_POLICY=DISABLED: region applies

    def launch(self):
        with self.launching:
            if h := self.find_popup():
                return h
            if not (self.proc and self.proc.poll() is None):  # not already starting
                cmd = self.browser_cmd(self.size, hidden=True)
                if not cmd:
                    u32.MessageBoxW(None, "No Chromium-based browser found (Edge, Chrome, Chromium or Brave).", APP_NAME, 0x10)
                    return None
                self.proc = subprocess.Popen(cmd)
            for _ in range(100):
                time.sleep(0.1)
                if h := self.find_popup():
                    return h
            return None

    def place(self, h):
        """Put the page (w x h CSS px) above the tray icon; push the browser title bar up and clip it off."""
        dpr = u32.GetDpiForWindow(h) / 96 or 1
        w, gap = round(self.size[0] * dpr), round(12 * dpr)
        work = W.RECT()
        u32.SystemParametersInfoW(0x30, 0, C.byref(work), 0)  # SPI_GETWORKAREA
        hgt = min(round(self.size[1] * dpr), work.bottom - work.top - 2 * gap)
        top = self.bar if self.bar is not None else round(self.cap * dpr)
        icon = W.RECT()
        nii = NOTIFYICONIDENTIFIER(cbSize=C.sizeof(NOTIFYICONIDENTIFIER), hWnd=self.hwnd, uID=1)
        if shell32.Shell_NotifyIconGetRect(C.byref(nii), C.byref(icon)) == 0 and icon.right > 0:
            x = (icon.left + icon.right) // 2 - w // 2  # centered on our tray icon
        else:
            x = work.right - w - gap
        x = max(work.left + gap, min(x, work.right - w - gap))
        y = work.top + gap if 0 < icon.bottom <= work.top else work.bottom - hgt - gap
        # Chromium keeps a few px of frame around its client area: place once, measure the insets, place again.
        ox = oy = dx = dy = 0
        for _ in range(2):
            u32.SetWindowPos(h, -1, x - ox, y - top - oy, w + dx, hgt + top + dy, 0x0010 | 0x0020)  # TOPMOST, NOACTIVATE|FRAMECHANGED
            r, c, o = W.RECT(), W.RECT(), W.POINT()
            u32.GetWindowRect(h, C.byref(r))
            u32.GetClientRect(h, C.byref(c))
            u32.ClientToScreen(h, C.byref(o))
            new = (o.x - r.left, o.y - r.top, r.right - r.left - c.right, r.bottom - r.top - c.bottom)
            if new == (ox, oy, dx, dy):
                break
            ox, oy, dx, dy = new
        rad = round(22 * dpr)
        box = (ox + 1, oy + top, ox + w, oy + top + hgt)  # 1 px in: Chromium app windows draw a light border inside the client area

        def clip():
            u32.SetWindowRgn(h, gdi.CreateRoundRectRgn(*box, rad, rad), True)
        clip()
        threading.Timer(0.25, clip).start()  # Chromium resets the region after it handles the resize

    def set_cap(self, cap, inner=0):
        """The page reports its viewport height: title bar = client area height - viewport height, exact in
        device pixels. cap (outerHeight - innerHeight) is the fallback before any window exists."""
        h = self.find_popup()
        if h and inner:
            c = W.RECT()
            u32.GetClientRect(h, C.byref(c))
            bar = c.bottom - round(inner * (u32.GetDpiForWindow(h) / 96 or 1))
            if 0 <= bar < 120 and bar != self.bar:
                self.bar = bar
                if u32.IsWindowVisible(h):
                    self.place(h)
        elif 0 < cap < 80:
            self.cap = cap

    def show(self):
        h = self.find_popup() or self.launch()
        if h:
            self.strip(h)
            self.place(h)
            u32.ShowWindow(h, 5)  # SW_SHOW
            u32.SetForegroundWindow(h)

    def hide(self):
        if h := self.find_popup():
            u32.ShowWindow(h, 0)
            self.hidden_at = time.time()

    def toggle(self):
        h = self.find_popup()
        if h and u32.IsWindowVisible(h):
            self.hide()
        elif time.time() - self.hidden_at > 0.4:  # the click itself blurred and hid it: don't reopen
            self.show()

    def quit(self):
        shell32.Shell_NotifyIconW(2, C.byref(self.nid))  # NIM_DELETE
        if h := self.find_popup():
            u32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
        os._exit(0)

    def loop(self):
        threading.Thread(target=self.launch, daemon=True).start()  # warm up the hidden window
        msg = W.MSG()
        while u32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(C.byref(msg))
            u32.DispatchMessageW(C.byref(msg))
