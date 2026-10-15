import pandas as pd
import pytest

import ingest


def test_reads_all_three_source_formats(raw_dir, tmp_path):
    df = ingest.ingest(raw_dir, tmp_path / "interim")
    assert set(df.source) == {"ceda", "datagov", "agmarknet"}
    assert (tmp_path / "interim" / "raw_prices.parquet").exists()
    assert len(df[df.source == "agmarknet"]) == 120          # HTML .xls with title rows was parsed


def test_dates_parse_from_every_format(raw_dir, tmp_path):
    df = ingest.ingest(raw_dir, tmp_path / "interim")
    assert df.price_date.notna().all()
    assert df.price_date.min() == pd.Timestamp("2024-01-01")
    # 05/01/2024 in the data.gov.in file is 5 January (day first), not 1 May
    kolar = df[df.market == "Kolar"].sort_values("price_date")
    assert kolar.price_date.iloc[4] == pd.Timestamp("2024-01-05")


def test_state_inferred_for_agmarknet_reports(raw_dir, tmp_path):
    df = ingest.ingest(raw_dir, tmp_path / "interim")
    assert set(df[df.source == "agmarknet"].state) == {"Uttar Pradesh"}


def test_prices_are_numeric_and_arrivals_kept(raw_dir, tmp_path):
    df = ingest.ingest(raw_dir, tmp_path / "interim")
    assert pd.api.types.is_float_dtype(df.modal_price)
    assert df[df.source == "ceda"].arrivals_tonnes.notna().all()


def test_per_kg_columns_are_converted_to_quintal():
    raw = pd.DataFrame({"Market": ["X"], "Commodity": ["Onion"], "Date": ["2024-01-01"],
                        "Modal Price (Rs/kg)": ["18.5"]})
    out = ingest.standardise(raw, "test", "f.csv")
    assert out.modal_price.iloc[0] == pytest.approx(1850)


def test_unknown_layout_explains_itself():
    raw = pd.DataFrame({"foo": [1], "bar": [2]})
    with pytest.raises(ingest.UnknownLayout, match="Columns found"):
        ingest.standardise(raw, "test", "mystery.csv")


def test_no_files_gives_a_helpful_message(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit, match="DATA.md"):
        ingest.ingest(tmp_path / "empty", tmp_path / "interim")
