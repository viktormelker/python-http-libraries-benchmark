import asyncio
import csv
import os
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import benchmark
import factory
from factory import Httpx2Package, HttpxPackage, NiquestsPackage, PackageFactory
from model import ASYNC_PACKAGES, csv_fieldnames, migrate_results_csv


class TestMockedBenchmarks(unittest.TestCase):

    @patch("benchmark.PackageFactory.get_package")
    def test_run_package_dispatches_async_and_sync_identities(self, mock_get_package):
        mock_result = MagicMock()
        mock_result.requests_per_sec = 100.0
        mock_result.total_time = 2.0
        mock_result.avg_conn_time = 0.02
        mock_result.avg_tls_time = 0.01

        mock_package = MagicMock()
        mock_package.run_sync.return_value = mock_result
        mock_package.run_async = AsyncMock(return_value=mock_result)
        mock_get_package.return_value = mock_package

        for name in ("aiohttp", "httpx_async", "niquests_async"):
            mock_package.reset_mock()
            result = asyncio.run(benchmark.run_package(name))
            self.assertEqual(result.requests_per_sec, 100.0)
            mock_package.run_async.assert_awaited()
            mock_package.run_sync.assert_not_called()

        for name in ("httpx_sync", "niquests_sync", "requests"):
            mock_package.reset_mock()
            result = asyncio.run(benchmark.run_package(name))
            self.assertEqual(result.avg_tls_time, 0.01)
            mock_package.run_sync.assert_called()
            mock_package.run_async.assert_not_called()

    @patch("benchmark.run_package")
    @patch("benchmark.PackageFactory.get_package")
    def test_run_benchmarks_mocked(self, mock_get_package, mock_run_package):
        mock_result = MagicMock()
        mock_result.requests_per_sec = 99.0
        mock_result.total_time = 1.5
        mock_result.avg_conn_time = 0.015
        mock_result.avg_tls_time = 0.005

        mock_run_package.return_value = mock_result

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "results.csv")
            with patch("benchmark.CSV_FILE", csv_path), patch("benchmark.range", return_value=range(2)):
                benchmark.run_benchmarks()

        self.assertTrue(mock_run_package.called)


class TestPackageIdentities(unittest.TestCase):

    def test_csv_fieldnames_include_sync_and_async_variants(self):
        fieldnames = csv_fieldnames()
        for name in (
            "req_sec_httpx_async",
            "req_sec_httpx_sync",
            "req_sec_httpx2_async",
            "req_sec_httpx2_sync",
            "req_sec_niquests_async",
            "req_sec_niquests_sync",
        ):
            self.assertIn(name, fieldnames)
        self.assertNotIn("req_sec_httpx", fieldnames)
        self.assertNotIn("req_sec_niquests", fieldnames)

    def test_async_packages_derived_from_suffix_and_aiohttp(self):
        self.assertIn("aiohttp", ASYNC_PACKAGES)
        self.assertIn("httpx_async", ASYNC_PACKAGES)
        self.assertIn("niquests_async", ASYNC_PACKAGES)
        self.assertNotIn("httpx_sync", ASYNC_PACKAGES)
        self.assertNotIn("niquests_sync", ASYNC_PACKAGES)
        self.assertNotIn("requests", ASYNC_PACKAGES)

    def test_factory_maps_dual_mode_identities(self):
        self.assertIsInstance(PackageFactory.get_package("httpx_async"), HttpxPackage)
        self.assertIsInstance(PackageFactory.get_package("httpx_sync"), HttpxPackage)
        self.assertIsInstance(PackageFactory.get_package("httpx2_async"), Httpx2Package)
        self.assertIsInstance(PackageFactory.get_package("httpx2_sync"), Httpx2Package)
        self.assertIsInstance(PackageFactory.get_package("niquests_async"), NiquestsPackage)
        self.assertIsInstance(PackageFactory.get_package("niquests_sync"), NiquestsPackage)


class TestMigrateResultsCsv(unittest.TestCase):

    def test_remaps_legacy_columns_and_adds_empty_variants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "results.csv")
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "start_time",
                        "end_time",
                        "num_requests",
                        "req_sec_aiohttp",
                        "req_sec_httpx",
                        "req_sec_httpx2",
                        "req_sec_niquests",
                        "req_sec_pycurl",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "start_time": "t0",
                    "end_time": "t1",
                    "num_requests": "100",
                    "req_sec_aiohttp": "1800",
                    "req_sec_httpx": "950",
                    "req_sec_httpx2": "900",
                    "req_sec_niquests": "1100",
                    "req_sec_pycurl": "2000",
                })

            migrate_results_csv(path)

            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["req_sec_httpx_async"], "950")
            self.assertEqual(row["req_sec_httpx2_async"], "900")
            self.assertEqual(row["req_sec_niquests_sync"], "1100")
            self.assertEqual(row["req_sec_httpx_sync"], "")
            self.assertEqual(row["req_sec_httpx2_sync"], "")
            self.assertEqual(row["req_sec_niquests_async"], "")
            self.assertEqual(row["req_sec_aiohttp"], "1800")
            self.assertNotIn("req_sec_httpx", row)
            self.assertNotIn("req_sec_niquests", row)


class TestNiquestsAsyncHang(unittest.IsolatedAsyncioTestCase):

    async def test_run_async_completes_beyond_connection_pool_size(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), SimpleHTTPRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with patch.object(factory, "TEST_URL", url), patch.object(factory, "NUM_REQUESTS_PER_PACKAGE_RUN", 15):
                result = await asyncio.wait_for(NiquestsPackage().run_async(), timeout=8)
            self.assertGreater(result.requests_per_sec, 0)
            self.assertGreater(result.total_time, 0)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
