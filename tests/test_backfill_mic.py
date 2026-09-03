import inspect
import unittest

from backfill import mic
from backfill.mic import ChosenInput, choose_input_device


def _dev(name, in_ch=2, sr=44100, hostapi=0):
    return {
        "name": name,
        "max_input_channels": in_ch,
        "default_samplerate": sr,
        "hostapi": hostapi,
    }


class TestChooseInputDevice(unittest.TestCase):
    def test_a_name_override_wins_and_skips_probing(self):
        devices = [_dev("Microphone (Pimax AirLink)"), _dev("Microphone (Realtek(R) Audio)")]
        probed = []

        chosen = choose_input_device(
            devices, lambda i: probed.append(i) or 1.0, override="realtek"
        )

        self.assertEqual(chosen, ChosenInput(1, "Microphone (Realtek(R) Audio)"))
        self.assertEqual(probed, [])  # an explicit choice never listens to anything

    def test_the_liveliest_input_is_chosen_over_a_silent_default(self):
        devices = [_dev("Dead VR mic"), _dev("Real Mic", in_ch=1), _dev("Speakers", in_ch=0)]
        levels = {0: 0.00001, 1: 0.02}  # VR silent, real mic hears the room

        chosen = choose_input_device(devices, lambda i: levels[i])

        self.assertEqual(chosen, ChosenInput(1, "Real Mic"))

    def test_the_liveliest_is_taken_even_when_the_whole_room_is_quiet(self):
        """A real mic's self-noise still beats a disconnected virtual device, so a
        silent room never falls back to the dead default."""
        devices = [_dev("Dead VR mic"), _dev("Real Mic", in_ch=1)]
        levels = {0: 0.00001, 1: 0.0003}

        chosen = choose_input_device(devices, lambda i: levels[i])

        self.assertEqual(chosen, ChosenInput(1, "Real Mic"))

    def test_a_device_that_fails_to_open_is_skipped(self):
        devices = [_dev("Broken"), _dev("Good", in_ch=1)]

        def probe(i):
            if i == 0:
                raise OSError("cannot open device")
            return 0.01

        self.assertEqual(choose_input_device(devices, probe), ChosenInput(1, "Good"))

    def test_each_physical_mic_is_probed_only_once(self):
        """Windows lists the same mic several times; probing each is slow and noisy."""
        devices = [_dev("Realtek", sr=44100), _dev("Realtek", sr=48000), _dev("Realtek", sr=16000)]
        probed = []

        choose_input_device(devices, lambda i: probed.append(i) or 0.01)

        self.assertEqual(probed, [0])

    def test_output_only_devices_are_never_considered(self):
        devices = [_dev("Headphones", in_ch=0)]
        probed = []

        chosen = choose_input_device(devices, lambda i: probed.append(i) or 1.0)

        self.assertIsNone(chosen)
        self.assertEqual(probed, [])

    def test_only_devices_on_the_requested_host_api_are_considered(self):
        """Some host-API duplicates (WDM-KS) can't be opened for blocking reads, so
        selection sticks to the API the OS default already uses."""
        devices = [
            _dev("Realtek (WDM-KS)", hostapi=3),
            _dev("Realtek (MME)", hostapi=0),
        ]
        probed = []

        chosen = choose_input_device(
            devices, lambda i: probed.append(i) or 0.01, hostapi=0
        )

        self.assertEqual(chosen, ChosenInput(1, "Realtek (MME)"))
        self.assertEqual(probed, [1])  # the wrong-host-API entry isn't even opened

    def test_a_device_returning_a_non_finite_level_is_ignored(self):
        devices = [_dev("Glitchy"), _dev("Good", in_ch=1)]

        def probe(i):
            return float("inf") if i == 0 else 0.01  # a garbage buffer can read absurdly loud

        self.assertEqual(choose_input_device(devices, probe), ChosenInput(1, "Good"))

    def test_an_override_that_matches_nothing_falls_through_to_probing(self):
        """Pinning a mic that is not plugged in today must not leave the tool
        deaf; the name is a preference, not a requirement."""
        devices = [_dev("Realtek")]

        chosen = choose_input_device(devices, lambda i: 0.01, override="pimax")

        self.assertEqual(chosen, ChosenInput(0, "Realtek"))

    def test_an_empty_override_is_no_override(self):
        """config.VOICE_DEVICE_NAME is empty when the user has pinned nothing."""
        devices = [_dev("Realtek")]

        chosen = choose_input_device(devices, lambda i: 0.01, override="   ")

        self.assertEqual(chosen, ChosenInput(0, "Realtek"))


class TestTheProbeContract(unittest.TestCase):
    def test_the_probe_takes_an_index_and_nothing_else(self):
        """`choose_input_device` calls the probe as `probe(index)`, so a probe
        with a second knob has no way to be told about it — and the one real
        implementation is the only thing that is ever injected in production."""
        self.assertEqual(list(inspect.signature(mic.probe_input_device).parameters), ["index"])


if __name__ == "__main__":
    unittest.main()


class TestTheProbeContract(unittest.TestCase):
    def test_the_probe_takes_an_index_and_nothing_else(self):
        """`choose_input_device` calls the probe as `probe(index)`, so a probe
        with a second knob has no way to be told about it — and the one real
        implementation is the only thing that is ever injected in production."""
        self.assertEqual(list(inspect.signature(mic.probe_input_device).parameters), ["index"])
