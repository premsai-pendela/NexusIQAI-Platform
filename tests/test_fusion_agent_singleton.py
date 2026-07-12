import threading
import unittest
from unittest.mock import patch

import agents.fusion_agent as fusion_agent_module
from agents.fusion_agent import get_fusion_agent


class ConcurrentColdStartTest(unittest.TestCase):
    """Regression test for the cold-start race in get_fusion_agent().

    Before the fix: `if key not in _fusion_instances: _fusion_instances[key] =
    FusionAgent(...)` was unguarded, so several concurrent callers hitting a
    fresh cache (e.g. multiple health-check probes racing a cold container
    start) could each see the key missing and each build their own full
    FusionAgent — multiplying an already-slow construction (embedding model
    download) instead of sharing one.
    """

    def setUp(self):
        # Use a cache key this test owns exclusively so it can't collide
        # with any real context another test or the app itself has warmed.
        self.key = "test-concurrent-cold-start"
        fusion_agent_module._fusion_instances.pop(self.key, None)

    def tearDown(self):
        fusion_agent_module._fusion_instances.pop(self.key, None)

    def test_only_one_instance_built_under_concurrent_cold_start(self):
        build_count = {"n": 0}
        build_lock = threading.Lock()
        release_builders = threading.Event()

        class SlowFakeAgent:
            def __init__(self, _data_context):
                with build_lock:
                    build_count["n"] += 1
                # Hold every concurrent caller here at once, the way a real
                # embedding-model download would, so the race window is
                # actually exercised rather than resolved by luck.
                release_builders.wait(timeout=5)

        with patch.object(fusion_agent_module, "FusionAgent", SlowFakeAgent), \
             patch.object(fusion_agent_module, "get_data_context", lambda k: k):

            threads = [
                threading.Thread(target=get_fusion_agent, args=(self.key,))
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            # Give every thread a chance to reach (or block inside) the
            # constructor before letting any of them finish.
            threading.Event().wait(0.05)
            release_builders.set()
            for t in threads:
                t.join(timeout=5)

        self.assertEqual(
            build_count["n"], 1,
            "get_fusion_agent() built the agent more than once under "
            "concurrent cold-start access — the singleton lock regressed.",
        )
        self.assertIsInstance(
            fusion_agent_module._fusion_instances[self.key], SlowFakeAgent
        )


if __name__ == "__main__":
    unittest.main()
