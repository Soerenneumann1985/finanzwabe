"""The start program for the .exe: log file, free port, finding Finanzwabe on a port."""
import socket
import sys

import launcher


def test_log_goes_into_the_data_folder_and_replaces_missing_console(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)  # like a program without console
    monkeypatch.setattr(sys, "stderr", None)
    log_path = launcher.start_logging(tmp_path / "neu")
    print("Hallo Log")
    sys.stdout.flush()
    assert log_path == tmp_path / "neu" / launcher.LOG_NAME
    assert "Hallo Log" in log_path.read_text(encoding="utf-8")
    sys.stdout.close()


def test_big_log_is_rotated(tmp_path, monkeypatch):
    (tmp_path / launcher.LOG_NAME).write_bytes(b"x" * (launcher.LOG_MAX_BYTES + 1))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    launcher.start_logging(tmp_path)
    sys.stdout.close()
    assert (tmp_path / (launcher.LOG_NAME + ".alt")).is_file()
    assert (tmp_path / launcher.LOG_NAME).stat().st_size < launcher.LOG_MAX_BYTES


def test_port_in_use_sees_a_listening_socket():
    with socket.socket() as server:
        server.bind((launcher.HOST, 0))
        server.listen()
        port = server.getsockname()[1]
        assert launcher.port_in_use(port)
    assert not launcher.port_in_use(port)


def test_find_port_takes_a_free_port_and_skips_foreign_programs(monkeypatch):
    monkeypatch.setattr(launcher, "port_in_use", lambda port: port == launcher.FIRST_PORT)
    monkeypatch.setattr(launcher, "is_finanzwabe", lambda port: False)  # something else on 8000
    assert launcher.find_port() == (launcher.FIRST_PORT + 1, False)


def test_find_port_recognises_a_running_finanzwabe(monkeypatch):
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher, "is_finanzwabe", lambda port: port == launcher.FIRST_PORT)
    assert launcher.find_port() == (launcher.FIRST_PORT, True)


def test_nothing_free_gives_none(monkeypatch):
    monkeypatch.setattr(launcher, "port_in_use", lambda port: True)
    monkeypatch.setattr(launcher, "is_finanzwabe", lambda port: False)
    assert launcher.find_port() == (None, False)


def test_resource_dir_is_the_project_folder_when_not_packed():
    assert (launcher.resource_dir() / "templates").is_dir()
    assert (launcher.resource_dir() / "static").is_dir()
