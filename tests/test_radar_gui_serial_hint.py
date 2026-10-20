"""Permission hint for a driver open_failed on a serial port (no hardware)."""


def test_permission_hint(tmp_path, monkeypatch):
    from radar_gui import driver
    port = tmp_path / "ttyACM9"
    port.write_text("")
    line = f"error: cannot open the CLI port {port}"
    monkeypatch.setattr(driver.os, "access", lambda p, m: False)
    hint = driver.serial_permission_hint(["noise", line])
    assert hint and str(port) in hint and f"gid {port.stat().st_gid}" in hint and "SERIAL_GID" in hint
    monkeypatch.setattr(driver.os, "access", lambda p, m: True)
    assert driver.serial_permission_hint([line]) is None                       # accessible: no hint
    assert driver.serial_permission_hint([f"cannot open the CLI port {tmp_path}/nope"]) is None  # absent port
    assert driver.serial_permission_hint(["unrelated"]) is None
