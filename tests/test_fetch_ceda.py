"""fetch_ceda.py against a fake CEDA API (no network): ids -> names, market-level rows, ingest-ready output."""

import pandas as pd

import fetch_ceda
import ingest


class FakeResponse:
    def __init__(self, data, status=200):
        self.status_code = status
        self._data = data
        self.headers = {}

    def json(self):
        return {"output": {"type": "success", "message": "ok", "data": self._data}}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeCeda:
    """Mimics the CEDA v1 endpoints the script uses."""

    def __init__(self, with_quantities=True):
        self.headers = {}
        self.calls = []
        self.with_quantities = with_quantities

    def request(self, method, url, json=None, timeout=None):
        path = url.replace(fetch_ceda.BASE_URL, "")
        self.calls.append((method, path, json))
        if path == "/agmarknet/commodities":
            return FakeResponse([{"commodity_id": 23, "commodity_name": "Onion"},
                                 {"commodity_id": 65, "commodity_name": "Tomato"}])
        if path == "/agmarknet/geographies":
            return FakeResponse([
                {"census_state_id": 27, "census_state_name": "Maharashtra", "census_district_id": 516,
                 "census_district_name": "Nashik"},
                {"census_state_id": 27, "census_state_name": "Maharashtra", "census_district_id": 521,
                 "census_district_name": "Pune"},
            ])
        if path == "/agmarknet/markets":
            names = {516: [(1001, "Lasalgaon"), (1002, "Pimpalgaon")], 521: [(2001, "Pune")]}
            return FakeResponse([{"market_id": m, "market_name": n} for m, n in names[json["district_id"]]])
        if path == "/agmarknet/prices":
            rows = []
            for d, (dist, mkt) in enumerate([(516, 1001), (516, 1002), (521, 2001)]):
                if dist in json["district_id"]:
                    for day in ["2024-01-01T00:00:00", "2024-01-02T00:00:00"]:
                        rows.append({"date": day, "commodity_id": 23, "census_state_id": 27,
                                     "census_district_id": dist, "market_id": mkt,
                                     "min_price": 1500 + d, "max_price": 2100 + d, "modal_price": 1800 + d})
            rows.append({"date": "2024-01-01T00:00:00", "commodity_id": 23, "census_state_id": 27,
                         "min_price": 1, "max_price": 2, "modal_price": 1.5})   # state aggregate row
            return FakeResponse(rows)
        if path == "/agmarknet/quantities" and self.with_quantities:
            rows = [{"date": "2024-01-01T00:00:00", "census_district_id": 516, "market_id": 1001, "quantity": 950.0}]
            return FakeResponse([r for r in rows if r["census_district_id"] in json["district_id"]])
        return FakeResponse([], status=404)


def test_fetch_year_returns_named_market_rows():
    api = fetch_ceda.Ceda("key", session=FakeCeda(), pause=0)
    df = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert set(df.market) == {"Lasalgaon", "Pimpalgaon", "Pune"}
    assert set(df.district) == {"Nashik", "Pune"}
    assert len(df) == 6                                     # state-average row dropped
    assert df.date.iloc[0] == "2024-01-01"
    las = df[(df.market == "Lasalgaon") & (df.date == "2024-01-01")]
    assert las.arrivals_tonnes.iloc[0] == 950.0


def test_works_without_quantity_endpoint():
    api = fetch_ceda.Ceda("key", session=FakeCeda(with_quantities=False), pause=0)
    df = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert "arrivals_tonnes" not in df and len(df) == 6


def test_requests_every_district_of_the_state():
    fake = FakeCeda()
    api = fetch_ceda.Ceda("key", session=fake, pause=0)
    fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    price_calls = [body for _, path, body in fake.calls if path == "/agmarknet/prices"]
    assert sorted(d for b in price_calls for d in b["district_id"]) == [516, 521]
    assert all(b["from_date"] == "2024-01-01" for b in price_calls)


def test_output_is_read_by_ingest(tmp_path):
    api = fetch_ceda.Ceda("key", session=FakeCeda(), pause=0)
    df = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    (tmp_path / "raw" / "ceda").mkdir(parents=True)
    df.to_csv(tmp_path / "raw" / "ceda" / "onion_maharashtra_2024.csv", index=False)
    out = ingest.ingest(tmp_path / "raw", tmp_path / "interim")
    assert len(out) == 6
    assert out.price_date.min() == pd.Timestamp("2024-01-01")
    assert out.arrivals_tonnes.notna().sum() == 1


def test_key_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CEDA_API_KEY", raising=False)
    monkeypatch.setattr(fetch_ceda, "ROOT", tmp_path)
    (tmp_path / ".env").write_text('CEDA_API_KEY="abc123"\n')
    assert fetch_ceda.load_key() == "abc123"


class SlowCeda(FakeCeda):
    """Times out whenever Nashik (a big onion district) is asked for more than ~2 months at once."""

    def request(self, method, url, json=None, timeout=None):
        import requests
        if url.endswith("/agmarknet/prices"):
            span = (pd.Timestamp(json["to_date"]) - pd.Timestamp(json["from_date"])).days
            if 516 in json["district_id"] and span > 62:
                self.calls.append((method, "TIMEOUT", json))
                raise requests.ReadTimeout("too slow")
        return super().request(method, url, json, timeout)


def test_slow_requests_are_split_until_they_succeed():
    fake = SlowCeda()
    api = fetch_ceda.Ceda("key", session=fake, pause=0)
    df = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert set(df.market) == {"Lasalgaon", "Pimpalgaon", "Pune"}
    ok = [b for _, p, b in fake.calls if p == "/agmarknet/prices"]
    assert all(len(b["district_id"]) == 1 for b in ok)
    assert any(c[1] == "TIMEOUT" for c in fake.calls)
    pune = [b for b in ok if b["district_id"] == [521]]
    assert len(pune) == 1                                   # fast district: one request for the whole range


def test_whole_period_asked_in_one_request_per_district():
    fake = FakeCeda()
    api = fetch_ceda.Ceda("key", session=fake, pause=0)
    fetch_ceda.fetch(api, "Onion", "Maharashtra", "2019-01-01", "2024-12-31")
    price_calls = [b for _, p, b in fake.calls if p == "/agmarknet/prices"]
    assert len(price_calls) == 2
    assert {(b["from_date"], b["to_date"]) for b in price_calls} == {("2019-01-01", "2024-12-31")}


def test_split_range():
    assert fetch_ceda.split_range("2019-03-01", "2021-12-31") == [
        ("2019-03-01", "2019-12-31"), ("2020-01-01", "2020-12-31"), ("2021-01-01", "2021-12-31")]
    assert fetch_ceda.split_range("2024-01-01", "2024-12-31") == [("2024-01-01", "2024-07-01"),
                                                                    ("2024-07-02", "2024-12-31")]
    assert fetch_ceda.split_range("2024-01-01", "2024-01-20") == []


def test_rerun_uses_cache_and_skips_slow_requests(tmp_path):
    first = SlowCeda()
    api = fetch_ceda.Ceda("key", session=first, pause=0, cache_dir=tmp_path / "cache")
    df1 = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert any(c[1] == "TIMEOUT" for c in first.calls)

    again = SlowCeda()                                      # e.g. the run was stopped by a rate limit
    api2 = fetch_ceda.Ceda("key", session=again, pause=0, cache_dir=tmp_path / "cache")
    df2 = fetch_ceda.fetch(api2, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert again.calls == []                                # nothing asked twice, no repeated timeouts
    pd.testing.assert_frame_equal(df1, df2)


def test_rate_limit_waits_and_continues(monkeypatch):
    class Limited(FakeCeda):
        def __init__(self):
            super().__init__()
            self.limited = False

        def request(self, method, url, json=None, timeout=None):
            if url.endswith("/agmarknet/prices") and not self.limited:
                self.limited = True
                r = FakeResponse([], status=429)
                r.headers = {"Retry-After": "3"}
                return r
            return super().request(method, url, json, timeout)

    slept = []
    monkeypatch.setattr(fetch_ceda.time, "sleep", slept.append)
    api = fetch_ceda.Ceda("key", session=Limited(), pause=0)
    df = fetch_ceda.fetch(api, "Onion", "Maharashtra", "2024-01-01", "2024-12-31")
    assert len(df) == 6 and 4 in slept


def test_download_writes_one_file_per_year(tmp_path):
    api = fetch_ceda.Ceda("key", session=FakeCeda(), pause=0)
    n = fetch_ceda.download(api, ["Onion"], ["Maharashtra"], pd.Timestamp("2023-06-01"),
                            pd.Timestamp("2024-12-31"), tmp_path)
    assert n == 6
    assert (tmp_path / "onion_maharashtra_2024.csv").exists()
    assert not (tmp_path / "onion_maharashtra_2023.csv").exists()     # fake has no 2023 rows
