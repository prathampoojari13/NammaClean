"""
Unit tests for in-memory RateLimiter and IP resolution.
"""

import unittest
from unittest.mock import MagicMock
import asyncio
import time
from fastapi import HTTPException, Request

from app.core.rate_limit import RateLimiter, get_client_ip


class TestGetClientIp(unittest.TestCase):
    def test_extract_from_x_forwarded_for_single(self):
        req = MagicMock(spec=Request)
        req.headers = {"X-Forwarded-For": "203.0.113.195"}
        self.assertEqual(get_client_ip(req), "203.0.113.195")

    def test_extract_from_x_forwarded_for_multi(self):
        req = MagicMock(spec=Request)
        req.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
        self.assertEqual(get_client_ip(req), "203.0.113.195")

    def test_extract_from_client_host(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.client.host = "192.168.1.100"
        self.assertEqual(get_client_ip(req), "192.168.1.100")

    def test_fallback_to_localhost(self):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.client = None
        self.assertEqual(get_client_ip(req), "127.0.0.1")


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.limiter = RateLimiter(max_requests=3, window_seconds=2, key_prefix="test")

    def tearDown(self):
        self.limiter.reset()

    def _make_mock_request(self, ip="10.0.0.1"):
        req = MagicMock(spec=Request)
        req.headers = {}
        req.client.host = ip
        return req

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            RateLimiter(max_requests=0, window_seconds=60)
        with self.assertRaises(ValueError):
            RateLimiter(max_requests=5, window_seconds=0)

    async def test_requests_within_limit_pass(self):
        req = self._make_mock_request()
        await self.limiter(req)
        await self.limiter(req)
        await self.limiter(req)
        # 3 requests allowed within 2 seconds

    async def test_exceeding_limit_raises_429(self):
        req = self._make_mock_request()
        await self.limiter(req)
        await self.limiter(req)
        await self.limiter(req)

        with self.assertRaises(HTTPException) as ctx:
            await self.limiter(req)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)
        self.assertIn("Too many requests", ctx.exception.detail)

    async def test_different_ips_tracked_independently(self):
        req1 = self._make_mock_request("10.0.0.1")
        req2 = self._make_mock_request("10.0.0.2")

        # Exceed limit for req1
        for _ in range(3):
            await self.limiter(req1)

        with self.assertRaises(HTTPException):
            await self.limiter(req1)

        # req2 should still be allowed
        await self.limiter(req2)
        await self.limiter(req2)

    async def test_window_sliding_recovery(self):
        fast_limiter = RateLimiter(max_requests=2, window_seconds=1, key_prefix="fast")
        req = self._make_mock_request()

        await fast_limiter(req)
        await fast_limiter(req)

        # Exceeded
        with self.assertRaises(HTTPException):
            await fast_limiter(req)

        # Sleep to pass window
        await asyncio.sleep(1.05)

        # Now should be permitted again
        await fast_limiter(req)

    async def test_reset(self):
        req = self._make_mock_request()
        for _ in range(3):
            await self.limiter(req)

        with self.assertRaises(HTTPException):
            await self.limiter(req)

        self.limiter.reset()

        # Should succeed after reset
        await self.limiter(req)


if __name__ == "__main__":
    unittest.main()
