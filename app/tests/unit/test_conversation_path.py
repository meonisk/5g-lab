"""scripts/profile/conversation.py --5g: разговор UE1 -> UE2 через rfsim без стенда."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / p) for p in ("scripts/lib", "scripts", "scripts/profile")]
import conversation  # noqa: E402
import ue5g  # noqa: E402

SETTINGS = {"UE2_MSISDN": "1002", "IMS_DOMAIN": "ims.test", "SIPUE2_IMSI": "102"}


class RadioPath(unittest.TestCase):
    def setUp(self):
        self.run = patch.object(conversation.subprocess, "run").start()
        self.sh = patch.object(conversation, "sh").start()
        patch.object(conversation, "prepare_jail").start()
        self.addCleanup(patch.stopall)

    def test_starts_and_stops_radio_only_when_it_was_down(self):
        for tunnels, expected in ((None, True), ("10.0.9.2", False)):
            with self.subTest(radio_running=bool(tunnels)):
                self.run.reset_mock()
                with patch.object(conversation, "tunnel_ip", return_value=tunnels):
                    path = conversation.RadioPath(SETTINGS)
                    path.install("/work")
                    path.stop()
                commands = [c.args[0][1] for c in self.run.call_args_list
                            if c.args[0][0] == str(conversation.RFSIM)]  # fmt: skip
                self.assertEqual(commands, ["up", "down"] if expected else [])

    def test_conversation_wavs_go_into_pjsua_root(self):
        with patch.object(conversation, "tunnel_ip", return_value="10.0.9.2"):
            conversation.RadioPath(SETTINGS).install("/work")
        copied = [c.args[-1] for c in self.sh.call_args_list if c.args[:2] == ("sudo", "cp")]
        self.assertEqual(
            copied, [str(conversation.JAIL / "tmp" / name) for name in conversation.WAVS.values()]
        )

    def test_each_ue_plays_its_own_side_and_ue1_calls_ue2(self):
        clients = [MagicMock(), MagicMock()]
        with (
            patch.object(conversation, "tunnel_ip", side_effect=["10.0.9.2", "10.0.9.3"]),
            patch.object(conversation, "Client", side_effect=clients) as client,
        ):
            path = conversation.RadioPath(SETTINGS)
            path.start()
            path.dial()
        self.assertEqual(
            client.call_args_list,
            [call(1, "10.0.9.2", SETTINGS, play_file="/tmp/conversation-ue1.wav"),
             call(2, "10.0.9.3", SETTINGS, play_file="/tmp/conversation-ue2.wav")],
        )  # fmt: skip
        clients[0].send.assert_called_once_with("m\nsip:1002@ims.test\n")
        for c in clients:
            c.registered_ms.assert_called_once()

    def test_players_switch_on_and_off_on_the_same_ports(self):
        path = conversation.RadioPath(SETTINGS)
        path.clients = [MagicMock(), MagicMock()]
        for number, c in enumerate(path.clients):
            c.player_ports.return_value = (str(number), "9")
        path.players(connect=True)
        path.players(connect=False)
        for number, c in enumerate(path.clients):
            c.player_ports.assert_called_once()
            self.assertEqual(
                c.switch_player.call_args_list,
                [call((str(number), "9"), True), call((str(number), "9"), False)],
            )

    def test_missing_tunnel_is_a_clear_error(self):
        with patch.object(conversation, "tunnel_ip", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "UE1 без адреса туннеля"):
                conversation.RadioPath(SETTINGS).start()


class UeClient(unittest.TestCase):
    def test_play_file_reaches_pjsua(self):
        with (
            patch.object(ue5g, "sh"),
            patch.object(ue5g.subprocess, "Popen") as popen,
            patch("builtins.open"),
        ):
            settings = {"UE1_IMSI": "1", "UE1_IMS_K": "k", "IMS_DOMAIN": "d",
                        "SIP_UE_CODEC": "PCMU", "PCSCF_IP": "p", "PCSCF_SIP_PORT": "5060"}  # fmt: skip
            ue5g.Client(1, "10.0.9.2", settings, play_file="/tmp/talk.wav")
        self.assertIn("--play-file=/tmp/talk.wav", popen.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
