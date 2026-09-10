"""Check package independence in fresh interpreters, without test import side effects."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [
        ("cgv_push_bot.alerts.service", ("discord", "cgv_push_bot.discord_ui")),
        ("cgv_push_bot.alerts.delivery", ("discord", "cgv_push_bot.discord_ui")),
        (
            "cgv_push_bot.cgv",
            ("discord", "sqlalchemy", "cgv_push_bot.db", "cgv_push_bot.alerts"),
        ),
    ],
)
def test_core_packages_do_not_load_presentation_or_infrastructure(
    module: str,
    forbidden: tuple[str, ...],
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys\n"
            "importlib.import_module(sys.argv[1])\n"
            "for prefix in sys.argv[2:]:\n"
            "    loaded = [name for name in sys.modules "
            "if name == prefix or name.startswith(prefix + '.') ]\n"
            "    assert not loaded, loaded\n",
            module,
            *forbidden,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
