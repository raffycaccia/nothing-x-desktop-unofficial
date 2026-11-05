# Security

The app listens on `127.0.0.1:47816` only, never on a network interface, and talks to the earbuds over the
Bluetooth link the operating system already pairs. It does not phone home.

If you find a problem that affects users (for example a way for another local process to send commands to
the earbuds through the local server, or a crash triggered by a malformed Bluetooth packet), please open a
[private security advisory](../../security/advisories/new) rather than a public issue. Expect an answer
within a week.
