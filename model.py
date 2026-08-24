import csv
import os

PACKAGES = [
    "aiohttp",
    "httpx_async",
    "httpx_sync",
    "httpx2_async",
    "httpx2_sync",
    "niquests_async",
    "niquests_sync",
    "pycurl",
    "requests",
    "urllib3",
]
ASYNC_PACKAGES = frozenset(
    name for name in PACKAGES if name.endswith("_async") or name == "aiohttp"
)
METRICS = ["req_sec", "total", "conn_avg", "tls_avg"]
CSV_METADATA = ["start_time", "end_time", "num_requests"]
LEGACY_PACKAGE_RENAMES = {
    "httpx": "httpx_async",
    "httpx2": "httpx2_async",
    "niquests": "niquests_sync",
}


class BenchmarkResult:
    def __init__(self, requests_per_sec, total_time, avg_conn_time, avg_tls_time=None):
        self.requests_per_sec = requests_per_sec
        self.total_time = total_time
        self.avg_conn_time = avg_conn_time
        self.avg_tls_time = avg_tls_time


def csv_fieldnames():
    return CSV_METADATA + [f"{metric}_{pkg}" for metric in METRICS for pkg in PACKAGES]


def remap_legacy_column(name):
    for metric in METRICS:
        prefix = f"{metric}_"
        if name.startswith(prefix):
            package = name[len(prefix):]
            if package in LEGACY_PACKAGE_RENAMES:
                return f"{prefix}{LEGACY_PACKAGE_RENAMES[package]}"
            break
    return name


def read_result_records(path, fieldnames=None):
    fieldnames = fieldnames or csv_fieldnames()
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    records = []
    for row in body:
        if len(row) == len(fieldnames):
            record = dict(zip(fieldnames, row))
        else:
            record = dict(zip(header, row))
        records.append({remap_legacy_column(key): value for key, value in record.items()})
    return records


def migrate_results_csv(path, fieldnames=None):
    fieldnames = fieldnames or csv_fieldnames()
    if not os.path.isfile(path):
        return
    with open(path, newline="") as f:
        header = next(csv.reader(f), [])
    if header == fieldnames:
        return
    records = read_result_records(path, fieldnames)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in fieldnames})
