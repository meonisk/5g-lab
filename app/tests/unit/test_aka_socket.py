"""Exact UE RTP UDP socket readback tests."""

import unittest
from unittest.mock import patch

from app.tests.integration.aka_socket import (
    SocketEvidenceError,
    bound_count,
    require_exact_bind,
)

TABLE = """   sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
  123: 0700000A:1B58 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 12345 2 0000000000000000 0
  124: 00000000:1B58 00000000:0000 07 00000000:00000000 00:00000000 00000000 0 0 12346 2 0000000000000000 0
"""


class SocketTests(unittest.TestCase):
    def test_exact_ip_and_port(self):
        self.assertEqual(bound_count(TABLE, "10.0.0.7", 7000), 1)
        self.assertEqual(bound_count(TABLE, "10.0.0.8", 7000), 0)
        self.assertEqual(bound_count(TABLE, "10.0.0.7", 7001), 0)

    def test_malformed_fails_closed(self):
        with self.assertRaises(SocketEvidenceError):
            bound_count(TABLE.replace("0700000A", "BADHEX00"), "10.0.0.7", 7000)
        with self.assertRaises(SocketEvidenceError):
            bound_count("not a proc table", "10.0.0.7", 7000)

    @patch("app.tests.integration.aka_socket.subprocess.run")
    def test_read_only_docker_invocation(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = TABLE
        self.assertEqual(require_exact_bind("callee", "10.0.0.7", 7000)["exact_bind_count"], 1)
        self.assertEqual(
            run.call_args.args[0], ["docker", "exec", "callee", "cat", "/proc/net/udp"]
        )
        with self.assertRaises(SocketEvidenceError):
            require_exact_bind("callee", "10.0.0.8", 7000)
