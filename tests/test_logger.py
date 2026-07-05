import json

from src.logger import create_logger


def test_default_threshold_suppresses_debug(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    create_logger("heediq-worker-transcription").debug("verbose detail")
    assert capsys.readouterr().out == ""


def test_default_threshold_emits_info(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    create_logger("heediq-worker-transcription").info("lifecycle event")
    line = json.loads(capsys.readouterr().out.strip())
    assert line["level"] == "info"
    assert line["message"] == "lifecycle event"


def test_log_level_debug_env_var_enables_debug(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    create_logger("heediq-worker-transcription").debug("verbose detail")
    line = json.loads(capsys.readouterr().out.strip())
    assert line["level"] == "debug"


def test_log_level_warn_suppresses_info(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warn")
    logger = create_logger("heediq-worker-transcription")
    logger.info("lifecycle event")
    logger.warn("careful")
    out, err = capsys.readouterr()
    assert out == ""
    assert json.loads(err.strip())["level"] == "warn"


def test_invalid_log_level_falls_back_to_info(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    create_logger("heediq-worker-transcription").info("lifecycle event")
    line = json.loads(capsys.readouterr().out.strip())
    assert line["level"] == "info"
