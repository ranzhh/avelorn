"""The command line's own behaviour: what it parses, prints, and exits with."""

import pytest

from avelorn.cli.main import main


def test_a_datasheet_goes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    """The corpus is read out on stdout, for a shell to page or grep."""
    assert main(["units", "show", "sisters-of-avelorn"]) == 0
    assert "Sisters of Avelorn  (sisters-of-avelorn)" in capsys.readouterr().out


def test_a_refused_question_exits_two_and_says_so_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown slug is a message on stderr, never a traceback or stdout noise."""
    assert main(["units", "show", "wood-elves"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: no unit 'wood-elves'" in captured.err


def test_a_command_is_required() -> None:
    """`avelorn` with nothing to do is a parse error, not an empty success."""
    with pytest.raises(SystemExit):
        main([])
