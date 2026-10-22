"""Tests for wayland_capture.py.

No real D-Bus here: the tests install fake bus/interface classes and drive
the portal flow by hand. The properties that actually matter:

1. The request is always made with interactive=True. A silent portal call
   would be a policy regression, not a bug.
2. Exactly one result reaches the callback, whatever happens: cancel, image,
   timeout, or second response after the first. `_done` latches.
3. The returned URI becomes an image and the file is erased afterwards; the
   portal's pixels are for the one look, not for /tmp to keep.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import wayland_capture as wc  # noqa: E402


class FakeDBus:
    """Enough interface()/connect()/disconnect() reality for the portal flow."""

    def __init__(self, registered=True, connected=True):
        self._registered = registered
        self._connected_ok = connected
        self.connections = []
        self.disconnections = []

    def isConnected(self):
        return self._connected_ok

    def interface(self):
        return self

    def isServiceRegistered(self, name):
        return self._registered

    def unique_name(self):
        return ":1.42.aB"

    def connect(self, service, path, iface, name, receiver):
        self.connections.append((path, name, receiver))
        return self._connected_ok

    def disconnect(self, service, path, iface, name, receiver):
        self.disconnections.append((path, name, receiver))
        return True


class FakeReply:
    def __init__(self, args, is_error=False):
        self._args = args
        self._is_error = is_error

    def arguments(self):
        return list(self._args)

    def type(self):
        return (wc.QDBusMessage.ErrorMessage if self._is_error
                else wc.QDBusMessage.ReplyMessage)

    def errorMessage(self):
        return "portal said no"


class FakeInterface:
    last = None

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.reply = FakeReply(["/org/freedesktop/portal/desktop/request/"
                                "ok/handled"])
        FakeInterface.last = self

    def callWithArgumentList(self, call_type, method, arguments):
        self.calls.append((call_type, method, arguments))
        return self.reply


class FakeTimer:
    last = None

    class Signal:
        def __init__(self):
            self.listeners = []

        def connect(self, callback):
            self.listeners.append(callback)

        def emit(self, *args):
            for listener in list(self.listeners):
                listener(*args)

    def __init__(self, parent=None):
        self.timeout = FakeTimer.Signal()
        self.started = None
        FakeTimer.last = self

    def setSingleShot(self, single):
        pass

    def start(self, ms):
        self.started = ms

    def stop(self):
        pass

    def fire(self):
        self.timeout.emit()


class FakeImage:
    def __init__(self, path):
        FakeImage.loaded.append(path)
        self._path = path
        self._null = FakeImage.null_next

    loaded = []
    null_next = False

    def isNull(self):
        return self._null

    def normalize(self):
        FakeImage.normalized = True
        return self


class PortalHarness(unittest.TestCase):
    """Patch the D-Bus surface the module binds to, then drive it by hand."""

    def setUp(self):
        FakeTimer.last = None
        FakeImage.loaded = []
        FakeImage.null_next = False
        self.bus = FakeDBus()
        self.results = []
        self._patches = [
            patch.object(wc, "QDBusConnection",
                         type("C", (), {"sessionBus": staticmethod(
                             lambda: self.bus)})),
            patch.object(wc, "QDBusInterface", FakeInterface),
            patch.object(wc, "QTimer", FakeTimer),
            patch.object(wc, "wayland_session", lambda: True),
        ]
        for item in self._patches:
            item.start()
            self.addCleanup(item.stop)
        self.portal = wc.PortalScreenshot(self._record)
        self.addCleanup(self._teardown_bus)

    def _record(self, image, reason):
        self.results.append((image, reason))

    def _teardown_bus(self):
        # latched unsubscribe hygiene: once a result was delivered, every
        # watched path must have been dropped. A still-pending request
        # (dialog open) may leave its watch in place.
        if not self.results:
            return
        for path, _, _ in self.bus.connections:
            disco = [d for d in self.bus.disconnections if d[0] == path]
            self.assertTrue(disco, "watch on %s was never removed" % path)

    def test_request_is_interactive_and_subscribes_first(self):
        ok, why = self.portal.request()
        self.assertTrue(ok, why)
        method_calls = FakeInterface.last.calls
        self.assertEqual(method_calls[0][1], "Screenshot")
        options = method_calls[0][2][1]
        interactive = options["interactive"]
        self.assertEqual(
            (interactive.variant() if hasattr(interactive, "variant")
             else interactive), True)      # the user is the gate
        # the subscription happens on the expected request-path convention
        self.assertTrue(self.bus.connections)
        path, name, receiver = self.bus.connections[0]
        self.assertEqual(name, "Response")
        self.assertIn(path, self.portal.watch_paths)

    def test_expected_path_uses_bus_unique_name(self):
        ok, why = self.portal.request()
        self.assertTrue(ok, why)
        expected = ("/org/freedesktop/portal/desktop/request/1_42_aB/%s"
                    % wc._token())
        self.assertIn(expected, [c[0] for c in self.bus.connections])

    def test_response_with_image(self):
        ok, why = self.portal.request()
        self.assertTrue(ok, why)
        handle = "/tmp/opencode/pet_portal_test.png"
        with open(handle, "wb") as fh:
            fh.write(b"pixels")
        self.addCleanup(lambda: (
            os.path.exists(handle) and os.unlink(handle)))
        with patch.object(wc, "QImage", FakeImage):
            self.portal._on_response(0, {"uri": "file://" + handle})
        image, reason = self.results[-1]
        self.assertIsInstance(image, FakeImage)
        self.assertEqual(reason, "")
        self.assertFalse(os.path.exists(handle))   # erased after the look

    def test_cancelled_response(self):
        self.portal.request()
        self.portal._on_response(1, {})
        image, reason = self.results[-1]
        self.assertIsNone(image)
        self.assertIn("cancelled", reason)

    def test_timeout_fronts_up(self):
        ok, why = self.portal.request()
        self.assertTrue(ok, why)
        FakeTimer.last.fire()          # the dialog sat there unloved
        image, reason = self.results[-1]
        self.assertIsNone(image)
        self.assertIn("timed out", reason)

    def test_only_one_result_ever_arrives(self):
        self.portal.request()
        self.portal._on_response(0, {"uri": ""})
        self.portal._on_timeout()
        self.portal._on_response(0, {"uri": ""})
        self.assertEqual(len(self.results), 1)

    def test_second_request_after_done_refuses(self):
        self.portal.request()
        self.portal._on_timeout()
        ok, why = self.portal.request()
        self.assertFalse(ok)


class TestAvailability(unittest.TestCase):
    def _with_env(self, **env):
        saved = {}
        for key, value in env.items():
            saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        def restore():
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(restore)

    def test_not_wayland(self):
        self._with_env(WAYLAND_DISPLAY=None, WAYLAND_SOCKET=None)
        ok, why = wc.available()
        self.assertFalse(ok)
        self.assertIn("Wayland", why)

    def test_no_qtdbus(self):
        self._with_env(WAYLAND_DISPLAY="wayland-0")
        with patch.object(wc, "QT_DBUS_OK", False):
            ok, why = wc.available()
        self.assertFalse(ok)
        self.assertIn("QtDBus", why)

    def test_portal_service_missing(self):
        self._with_env(WAYLAND_DISPLAY="wayland-0")
        bus = FakeDBus(registered=False)
        self.assertTrue(bus.isConnected())
        with patch.object(wc, "QDBusConnection",
                          type("C", (), {"sessionBus": staticmethod(
                              lambda: bus)})):
            ok, why = wc.available()
        self.assertFalse(ok)
        self.assertIn("not running", why)


class TestUriToImage(unittest.TestCase):
    def test_file_prefix_is_stripped(self):
        handle = "/tmp/opencode/pet_uri_test.png"
        with open(handle, "wb") as fh:
            fh.write(b"junk")
        self.addCleanup(lambda: (
            os.path.exists(handle) and os.unlink(handle)))
        with patch.object(wc, "QImage", FakeImage):
            image, why = wc.image_from_uri("file://" + handle)
        self.assertEqual(FakeImage.loaded[-1], handle)
        self.assertFalse(os.path.exists(handle))

    def test_empty_uri_reason(self):
        image, why = wc.image_from_uri("")
        self.assertIsNone(image)

    def test_unreadable_image_reasons_clearly(self):
        FakeImage.null_next = True
        self.addCleanup(setattr, FakeImage, "null_next", False)
        with patch.object(wc, "QImage", FakeImage):
            image, why = wc.image_from_uri("file:///tmp/opencode/never.png")
        self.assertIsNone(image)
        self.assertIn("could not be read", why)


if __name__ == "__main__":
    unittest.main()
