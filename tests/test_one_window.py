"""One window of a kind at a time: the stats and queue windows' lifetime, held once."""
from __future__ import annotations

from unittest.mock import MagicMock

from gui.one_window import OneWindow


def _window(*, visible: bool) -> MagicMock:
    window = MagicMock()
    window.isVisible.return_value = visible
    return window


class TestOneWindow:
    def test_the_first_show_builds_the_window_and_shows_it(self):
        window = _window(visible=False)
        one = OneWindow()

        one.show(lambda: window)

        assert one.current is window
        window.show.assert_called_once_with()

    def test_the_one_still_up_is_raised_rather_than_replaced(self):
        up = _window(visible=True)
        one = OneWindow()
        one.show(lambda: up)
        build_again = MagicMock()

        one.show(build_again)

        build_again.assert_not_called()
        assert one.current is up
        up.raise_.assert_called_once_with()
        up.activateWindow.assert_called_once_with()

    def test_one_since_closed_is_taken_down_before_the_next_is_built(self):
        """Parented to the main window, one replaced without being taken down
        stays alive for the process's whole life."""
        closed, replacement = _window(visible=False), _window(visible=False)
        one = OneWindow()
        one.show(lambda: closed)

        one.show(lambda: replacement)

        closed.close.assert_called_once_with()
        closed.deleteLater.assert_called_once_with()
        assert one.current is replacement
        replacement.show.assert_called_once_with()

    def test_show_answers_the_window_it_built_and_nothing_when_one_was_raised(self):
        built = _window(visible=True)
        one = OneWindow()

        assert one.show(lambda: built) is built
        assert one.show(MagicMock()) is None

    def test_it_is_on_screen_only_while_a_window_is_up(self):
        one = OneWindow()
        assert not one.is_on_screen

        one.show(lambda: _window(visible=True))
        assert one.is_on_screen

        one.current.isVisible.return_value = False
        assert not one.is_on_screen
