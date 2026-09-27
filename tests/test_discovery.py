"""Bluetooth discovery matching tests."""

from __future__ import annotations

import unittest

from custom_components.amaran.discovery import (
    MESH_PROXY_SERVICE_UUID,
    advertised_network_id,
    network_id_for_key,
)


class DiscoveryTest(unittest.TestCase):
    def test_network_id_matches_mesh_spec_sample(self) -> None:
        # Mesh Profile 1.0.1, 8.1.5 k3 sample data.
        self.assertEqual(
            network_id_for_key("f7a2a44f8e8a8029064f173ddc1e2b00").hex(),
            "ff046958233db014",
        )

    def test_reads_network_id_and_ignores_node_identity(self) -> None:
        network = bytes.fromhex("1676538330d379ef")

        self.assertEqual(
            advertised_network_id({MESH_PROXY_SERVICE_UUID: b"\x00" + network}),
            network,
        )
        self.assertIsNone(
            advertised_network_id({MESH_PROXY_SERVICE_UUID: b"\x01" + bytes(16)})
        )
        self.assertIsNone(advertised_network_id({}))


if __name__ == "__main__":
    unittest.main()
