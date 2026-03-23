"""
fetch_bls.py
------------
Fetches Job Openings data from the US Bureau of Labor Statistics (BLS) JOLTS API.

What JOLTS is:
    Job Openings and Labor Turnover Survey. Published monthly by the US government.
    It tells us how many job openings exist by industry sector.
    We use this to measure "recovery" — are more jobs opening up in sectors
    that had big layoffs? That's the recovery index.

What this script does:
    1. Calls the BLS public API v2 (free, requires free API key)
    2. Fetches monthly job openings for 8 major tech-adjacent sectors
    3. Parses the response into a clean DataFrame
    4. Uploads as JSON to S3 raw/bls/

BLS API docs: https://www.bls.gov/developers/api_signature_v2.htm

Get your free API key at: https://data.bls.gov/registrationEngine/

Run this script: python ingestion/fetch_bls.py
"""

import os
import json
import logging
from datetime import datetime, timezone

import boto3
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- BLS Series IDs ---
# Each series ID maps to job openings in a specific industry sector.
# Format: JTS + industry code + "000000000" + "JO" (job openings)
# Full list: https://www.bls.gov/jlt/jltover.htm
SERIES_IDS = {
    "JTS540099000000000JO": "information_technology",
    "JTS510000000000000JO": "finance_insurance",
    "JTS600000000000000JO": "professional_business_services",
    "JTS620000000000000JO": "education_health",
    "JTS700000000000000JO": "leisure_hospitality",
    "JTS400000000000000JO": "trade_transportation",
    "JTS200000000000000JO": "construction",
    "JTS000000000000000JO": "total_nonfarm",
}

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Fetch last 3 years of data (BLS allows max 20 years per call)
CURRENT_YEAR = datetime.now().year
START_YEAR = CURRENT_YEAR - 3
END_YEAR = CURRENT_YEAR

S3_BUCKET = os.getenv("S3_BUCKET_NAME")
S3_KEY = f"raw/bls/jolts_{datetime.now().strftime('%Y-%m-%d')}.json"


def fetch_bls_data(series_ids: list, start_year: int, end_year: int) -> dict:
    """
    Calls the BLS API v2 to get monthly job openings for multiple series.

    Why v2 instead of v1:
        v2 requires an API key but allows fetching multiple series in one call
        and returns more data. v1 is anonymous but limited to 25 series/day.
    """
    api_key = os.getenv("BLS_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "BLS_API_KEY not set in .env. "
            "Get a free key at: https://data.bls.gov/registrationEngine/"
        )

    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": api_key,
        # annualaverage=True adds a yearly average row — useful for dashboards
        "annualaverage": True,
        "catalog": True,
    }

    logger.info(f"Calling BLS API for {len(series_ids)} series, {start_year}–{end_year}")

    response = requests.post(
        BLS_API_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    response.raise_for_status()

    data = response.json()

    # BLS returns a status field — check it before trusting the data
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(
            f"BLS API returned non-success status: {data.get('status')}. "
            f"Message: {data.get('message', 'No message')}"
        )

    logger.info(f"BLS API call succeeded. Series returned: {len(data['Results']['series'])}")
    return data


def parse_bls_response(raw_data: dict, series_map: dict) -> pd.DataFrame:
    """
    Converts the nested BLS API response into a flat DataFrame.

    BLS response structure:
        data['Results']['series'] → list of series
            series['seriesID'] → e.g. "JTS540099000000000JO"
            series['data'] → list of monthly observations
                {'year': '2024', 'period': 'M01', 'value': '123456', ...}
    """
    rows = []

    for series in raw_data["Results"]["series"]:
        series_id = series["seriesID"]
        sector_name = series_map.get(series_id, series_id)

        for obs in series["data"]:
            # Skip annual averages (period M13) for our monthly analysis
            if obs["period"] == "M13":
                continue

            # Convert period "M01" → month number 1
            month_num = int(obs["period"].replace("M", ""))

            rows.append({
                "series_id": series_id,
                "sector": sector_name,
                "year": int(obs["year"]),
                "month": month_num,
                # BLS stores values as strings with commas — convert to int
                "job_openings_thousands": int(obs["value"].replace(",", "")),
                "footnote": obs.get("footnotes", [{}])[0].get("code", ""),
                "ingested_at": datetime.now(timezone.utc).isoformat()
            })

    df = pd.DataFrame(rows)

    # Create a proper date column for time-series analysis
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01"
    )

    # Sort chronologically
    df = df.sort_values(["sector", "date"]).reset_index(drop=True)

    logger.info(f"Parsed {len(df):,} monthly observations across {df['sector'].nunique()} sectors")
    return df


def upload_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    """Uploads DataFrame as JSON to S3."""
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )

    # Convert to JSON — orient="records" gives [{col: val}, ...] format
    # This is the most readable format for downstream processing
    json_str = df.to_json(orient="records", date_format="iso", indent=2)

    logger.info(f"Uploading {len(df):,} rows to s3://{bucket}/{key}")

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json_str.encode("utf-8"),
        ContentType="application/json"
    )

    logger.info(f"Upload complete: s3://{bucket}/{key}")


def main():
    logger.info("=== BLS JOLTS ingestion started ===")

    series_list = list(SERIES_IDS.keys())

    raw_data = fetch_bls_data(series_list, START_YEAR, END_YEAR)
    df = parse_bls_response(raw_data, SERIES_IDS)

    if not S3_BUCKET:
        raise EnvironmentError("S3_BUCKET_NAME not set in .env")

    upload_to_s3(df, S3_BUCKET, S3_KEY)

    logger.info("=== BLS JOLTS ingestion complete ===")
    logger.info(f"Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    logger.info(f"Sectors: {', '.join(df['sector'].unique())}")


if __name__ == "__main__":
    main()
