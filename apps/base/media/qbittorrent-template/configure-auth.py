#!/usr/bin/env python3
"""Set qBittorrent WebUI credentials before the service starts."""

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path


def main() -> None:
    config = Path(os.environ["QBITTORRENT_CONFIG"])
    username = os.environ["QBITTORRENT_USERNAME"]
    password = Path(os.environ["QBITTORRENT_PASSWORD_FILE"]).read_text().rstrip("\r\n")
    if not password or "\n" in username or "\r" in username:
        raise SystemExit("qBittorrent username/password is empty or invalid")

    config.parent.mkdir(parents=True, exist_ok=True)

    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, 100_000)
    encoded = "@ByteArray({}:{})".format(
        base64.b64encode(salt).decode(), base64.b64encode(derived).decode()
    )

    content = config.read_text() if config.exists() else ""
    if "[Preferences]" not in content:
        content = content.rstrip() + "\n\n[Preferences]\n"
    start = content.index("[Preferences]")
    next_section = re.search(r"(?m)^\[", content[start + len("[Preferences]") :])
    end = start + len("[Preferences]") + next_section.start() if next_section else len(content)
    section = content[start:end]
    for key, value in (("WebUI\\Username", username), ("WebUI\\Password_PBKDF2", encoded)):
        pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
        line = f"{key}={value}"
        # Config keys contain a literal backslash (for example, WebUI\\Username).
        # A callable keeps re.sub from parsing backslashes in the replacement text.
        if pattern.search(section):
            section = pattern.sub(lambda _match: line, section)
        else:
            section = section.rstrip("\n") + "\n" + line + "\n"
    updated = content[:start] + section + content[end:]
    temp = config.with_suffix(".conf.tmp")
    temp.write_text(updated)
    temp.chmod(0o600)
    temp.replace(config)
    os.chown(config, int(os.environ["PUID"]), int(os.environ["PGID"]))


if __name__ == "__main__":
    main()
