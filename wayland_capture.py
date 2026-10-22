"""wayland_capture.py - Look At This on Wayland, through the desktop portal.

Policy honesty first: *automatic* captures on Wayland stay impossible by
design. The desktop is not enumerable, so the blocklist cannot be honoured,
so `screen_capture.redaction_guarantee` refuses and fails closed. No module
changes that -- a background capture the user did not ask for is not the pet's
business on Wayland, full stop.

What this module covers is the one case that is both useful and safe: the
user explicitly asked for it ("Look At This"). The xdg-desktop-portal Screenshot
API is used with `interactive=True`, which hands the confirm/deny decision to
the user in a compositor dialog (you cannot silently screenshot through this
call on any sane portal implementation -- and we never ask it to try). The
compositor takes the shot, we get a URI to the PNG, and the normal pipeline
takes over: OCR content filter, then encode and send. The image is subject to
exactly the same discard rules as any other capture.

Plumbing note: this uses PyQt5's QtDBus (no new dependencies), and connections
live on the session bus. The response is asynchronous -- it arrives in the Qt
event loop once the user answers the dialog -- so `request()` returns
immediately and the result comes back through the callback.
"""

import os

QT_DBUS_OK = False
try:
    from PyQt5.QtCore import QObject, QTimer, pyqtSignal
    from PyQt5.QtDBus import (QDBus, QDBusConnection, QDBusInterface,
                              QDBusMessage, QDBusVariant)
    from PyQt5.QtGui import QImage

    QT_DBUS_OK = True
except ImportError:
    QT_DBUS_OK = False

SERVICE = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_TYPE_OF = "org.freedesktop.portal.Request"

DEFAULT_TIMEOUT_MS = 20000     # the dialog is the user's time, not ours


def wayland_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")
                or os.environ.get("WAYLAND_SOCKET"))


def available() -> tuple:
    """(ok, reason) -- whether a portal screenshot attempt makes sense."""
    if not QT_DBUS_OK:
        return False, "no QtDBus in this PyQt5"
    if not wayland_session():
        return False, "not a Wayland session"
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False, "no session bus"
    try:
        if not bus.interface().isServiceRegistered(SERVICE):
            return False, "the desktop portal is not running"
    except Exception:
        return False, "cannot reach the desktop portal"
    return True, ""


def _variant_map(options):
    """Wrap a dict's values the way the portal spec requires (a{sv})."""
    return {key: QDBusVariant(value) for key, value in options.items()}


def _token():
    return "pet_%d_%d" % (os.getpid(), os.getpid() * 7)


def _path_from_reply(reply):
    """The request object path a Screenshot call hands back."""
    try:
        arg = reply.arguments()[0]
        return str(arg)
    except Exception:
        return None


def image_from_uri(uri) -> tuple:
    """Load the portal's result URI into a QImage.

    Returns (image, reason). The URI is a file under /tmp (or the portal's
    app dir) that the compositor wrote; it is deleted after reading.
    """
    if not uri:
        return None, "the portal returned no image"
    path = str(uri)
    if path.startswith("file://"):
        path = path[len("file://"):]
    image = QImage(path)
    if image.isNull():
        return None, "the portal's image could not be read"
    try:
        os.unlink(path)                      # the pixels were for this one look
    except OSError:
        pass
    return image.normalize(), ""


class PortalScreenshot(QObject):
    """One interactive portal screenshot request, result via callback."""

    def __init__(self, on_result, timeout_ms=DEFAULT_TIMEOUT_MS):
        super().__init__()
        self._on_result = on_result
        self._done = False
        self.bus = None
        self.iface = None
        self.watch_paths = []
        if QT_DBUS_OK:
            self.bus = QDBusConnection.sessionBus()
            self.iface = QDBusInterface(SERVICE, PATH, SCREENSHOT_IFACE,
                                        self.bus)
        self._timer = None

    # ---- the one public call ------------------------------------------
    def request(self, timeout_ms=DEFAULT_TIMEOUT_MS):
        """Start the async request. Returns (ok, reason)."""
        if self._done:
            return False, "already answered"
        ok, why = available()
        if not ok:
            self._done = True
            return False, why
        options = {
            "handle_token": _token(),
            "interactive": True,     # always: the user confirms the shot
        }
        expected = self._expected_request_path()
        if self._connect_response(expected):
            self.watch_paths.append(expected)
        try:
            reply = self.iface.callWithArgumentList(
                QDBus.AutoDetect, "Screenshot",
                ["", _variant_map(options)])
        except Exception as problem:
            self._done = True
            return False, "the portal call failed (%s)" % problem
        if reply is not None and reply.type() == QDBusMessage.ErrorMessage:
            self._done = True
            return False, "the portal refused: %s" % reply.errorMessage()
        path = _path_from_reply(reply)
        if path and path not in self.watch_paths and \
                self._connect_response(path):
            self.watch_paths.append(path)
        if not self.watch_paths:
            self._done = True
            return False, "the portal request was not accepted"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.start(timeout_ms)
        return True, ""

    def _expected_request_path(self):
        """The request path convention: <sender-without-colon>/<token>.

        The portal reuses the caller's unique name in the request path, so
        connecting this BEFORE the call (the spec's ordering requirement)
        leaves no race where the Response is missed.
        """
        name = self.bus.unique_name() or ""
        if name.startswith(":"):
            name = name[1:]
        return "/org/freedesktop/portal/desktop/request/%s/%s" % (
            name.replace(".", "_"), _token())

    def _connect_response(self, path):
        """Subscribe to Response (uint32 code, a{sv} results) on `path`."""
        try:
            return bool(self.bus.connect(
                SERVICE, path, REQUEST_TYPE_OF, "Response",
                self._on_response))
        except Exception:
            return False

    # ---- responses ------------------------------------------------------
    def _on_response(self, code, results):
        """Shared tail for both response sources."""
        if self._done:
            return
        if self._timer is not None:
            self._timer.stop()
        if int(code) != 0:
            self._finish(None, "the screenshot request was cancelled")
            return
        image, why = image_from_uri(results.get("uri", "") if results else "")
        self._finish(image, why)

    def _finish(self, image, reason):
        if self._done:
            return
        self._done = True                       # exactly one answer, ever
        for path in self.watch_paths:
            try:
                self.bus.disconnect(SERVICE, path, REQUEST_TYPE_OF,
                                    "Response", self._on_response)
            except Exception:
                pass
        try:
            self._on_result(image, reason)
        except Exception:
            pass

    def _on_timeout(self):
        self._finish(None, "no answer from the portal (the dialog timed out)")
