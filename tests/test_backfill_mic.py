import unittest

from backfill.mic import choose_input_device


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

        index, name = choose_input_device(
            devices, lambda i: probed.append(i) or 1.0, override="realtek"
        )

        self.assertEqual((index, name), (1, "Microphone (Realtek(R) Audio)"))
        self.assertEqual(probed, [])  # an explicit choice never listens to anything

    def test_the_liveliest_input_is_chosen_over_a_silent_default(self):
        devices = [_dev("Dead VR mic"), _dev("Real Mic", in_ch=1), _dev("Speakers", in_ch=0)]
        levels = {0: 0.00001, 1: 0.02}  # VR silent, real mic hears the room

        index, name = choose_input_device(devices, lambda i: levels[i])

        self.assertEqual((index, name), (1, "Real Mic"))

    def test_the_liveliest_is_taken_even_when_the_whole_room_is_quiet(self):
        """A real mic's self-noise still beats a disconnected virtual device, so a
        silent room never falls back to the dead default."""
        devices = [_dev("Dead VR mic"), _dev("Real Mic", in_ch=1)]
        levels = {0: 0.00001, 1: 0.0003}

        index, name = choose_input_device(devices, lambda i: levels[i])

        self.assertEqual((index, name), (1, "Real Mic"))

    def test_a_device_that_fails_to_open_is_skipped(self):
        devices = [_dev("Broken"), _dev("Good", in_ch=1)]

        def probe(i):
            if i == 0:
                raise OSError("cannot open device")
            return 0.01

        self.assertEqual(choose_input_device(devices, probe), (1, "Good"))

    def test_each_physical_mic_is_probed_only_once(self):
        """Windows lists the same mic several times; probing each is slow and noisy."""
        devices = [_dev("Realtek", sr=44100), _dev("Realtek", sr=48000), _dev("Realtek", sr=16000)]
        probed = []

        choose_input_device(devices, lambda i: probed.append(i) or 0.01)

        self.assertEqual(probed, [0])

    def test_output_only_devices_are_never_considered(self):
        devices = [_dev("Headphones", in_ch=0)]
        probed = []

        index, name = choose_input_device(devices, lambda i: probed.append(i) or 1.0)

        self.assertEqual((index, name), (None, None))
        self.assertEqual(probed, [])

    def test_only_devices_on_the_requested_host_api_are_considered(self):
        """Some host-API duplicates (WDM-KS) can't be opened for blocking reads, so
        selection sticks to the API the OS default already uses."""
        devices = [
            _dev("Realtek (WDM-KS)", hostapi=3),
            _dev("Realtek (MME)", hostapi=0),
        ]
        probed = []

        index, name = choose_input_device(
            devices, lambda i: probed.append(i) or 0.01, hostapi=0
        )

        self.assertEqual((index, name), (1, "Realtek (MME)"))
        self.assertEqual(probed, [1])  # the wrong-host-API entry isn't even opened

    def test_a_device_returning_a_non_finite_level_is_ignored(self):
        devices = [_dev("Glitchy"), _dev("Good", in_ch=1)]

        def probe(i):
            return float("inf") if i == 0 else 0.01  # a garbage buffer can read absurdly loud

        self.assertEqual(choose_input_device(devices, probe), (1, "Good"))


if __name__ == "__main__":
    unittest.main()
